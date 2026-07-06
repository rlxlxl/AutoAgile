import hashlib
import hmac
from typing import Mapping

import requests

from app.providers.base import GitProvider, PullRequest, WebhookEvent


class GitHubProvider(GitProvider):
    """GitHub REST client for the Pull Requests used by the sync."""

    name = "github"
    base_url = "https://api.github.com"

    def __init__(self, token: str, repo: str):
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _handle(self, response: requests.Response) -> dict:
        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except ValueError:
                return {}
        raise Exception(
            f"GitHub request failed with status {response.status_code}: {response.text}"
        )

    @staticmethod
    def _to_pr(data: dict) -> PullRequest:
        return PullRequest(
            number=str(data.get("number")),
            branch=((data.get("head") or {}).get("ref")) or "",
            body=data.get("body") or "",
        )

    def find_pr_by_branch(self, branch: str) -> PullRequest | None:
        owner = self.repo.split("/")[0]
        url = f"{self.base_url}/repos/{self.repo}/pulls"
        response = requests.get(
            url,
            headers=self.headers,
            params={"head": f"{owner}:{branch}", "state": "open"},
            timeout=30,
        )
        data = self._handle(response)
        if isinstance(data, list) and data:
            return self._to_pr(data[0])
        return None

    def find_pr_by_branch_prefix(self, prefix: str) -> PullRequest | None:
        url = f"{self.base_url}/repos/{self.repo}/pulls"
        response = requests.get(
            url,
            headers=self.headers,
            params={"state": "open", "per_page": 100},
            timeout=30,
        )
        data = response.json() if 200 <= response.status_code < 300 else []
        if not isinstance(data, list):
            return None
        for pull in data:
            head_ref = ((pull.get("head") or {}).get("ref")) or ""
            if head_ref.startswith(prefix):
                return self._to_pr(pull)
        return None

    def create_pr(self, *, title: str, source: str, target: str, body: str) -> PullRequest:
        url = f"{self.base_url}/repos/{self.repo}/pulls"
        response = requests.post(
            url,
            headers=self.headers,
            json={"title": title, "head": source, "base": target, "body": body},
            timeout=30,
        )
        return self._to_pr(self._handle(response))

    def update_pr(self, number: str, *, title: str | None = None, body: str | None = None) -> PullRequest:
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        url = f"{self.base_url}/repos/{self.repo}/pulls/{number}"
        response = requests.patch(url, headers=self.headers, json=payload, timeout=30)
        return self._to_pr(self._handle(response))

    def verify_webhook(self, secret: str, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        """Verify the ``X-Hub-Signature-256`` header against ``secret``."""
        if not secret:
            return True
        signature = headers.get("X-Hub-Signature-256")
        if not signature or not signature.startswith("sha256="):
            return False
        expected = "sha256=" + hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook(self, payload: dict) -> WebhookEvent | None:
        pull = payload.get("pull_request")
        if not isinstance(pull, dict):
            return None
        action_map = {"opened": "opened", "edited": "updated", "synchronize": "updated"}
        action = action_map.get(payload.get("action"), "ignored")
        return WebhookEvent(
            number=str(pull.get("number")),
            branch=(pull.get("head") or {}).get("ref") or "",
            body=pull.get("body") or "",
            action=action,
        )
