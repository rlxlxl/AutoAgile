import hmac
import urllib.parse
from typing import Mapping

import requests

from app.providers.base import GitProvider, PullRequest, WebhookEvent


class GitLabProvider(GitProvider):
    """GitLab REST client (``/api/v4``) for the Merge Requests used by the sync.

    A GitLab Merge Request maps onto the provider-neutral :class:`PullRequest`:
    ``iid`` -> number, ``source_branch`` -> branch, ``description`` -> body.
    """

    name = "gitlab"

    def __init__(self, token: str, project_id: str, base_url: str = "http://localhost:8929"):
        self.token = token
        # project_id can be numeric ("42") or a namespaced path ("group/project").
        self.project_id = urllib.parse.quote(str(project_id), safe="")
        self.api_url = f"{base_url.rstrip('/')}/api/v4"
        self.headers = {
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        }

    def _handle(self, response: requests.Response) -> dict:
        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except ValueError:
                return {}
        raise Exception(
            f"GitLab request failed with status {response.status_code}: {response.text}"
        )

    def _mr_url(self, iid: str | int | None = None) -> str:
        base = f"{self.api_url}/projects/{self.project_id}/merge_requests"
        return f"{base}/{iid}" if iid is not None else base

    @staticmethod
    def _to_pr(data: dict) -> PullRequest:
        return PullRequest(
            number=str(data.get("iid")),
            branch=data.get("source_branch") or "",
            body=data.get("description") or "",
        )

    def find_pr_by_branch(self, branch: str) -> PullRequest | None:
        response = requests.get(
            self._mr_url(),
            headers=self.headers,
            params={"state": "opened", "source_branch": branch},
            timeout=30,
        )
        data = self._handle(response)
        if isinstance(data, list) and data:
            return self._to_pr(data[0])
        return None

    def find_pr_by_branch_prefix(self, prefix: str) -> PullRequest | None:
        response = requests.get(
            self._mr_url(),
            headers=self.headers,
            params={"state": "opened", "per_page": 100},
            timeout=30,
        )
        data = response.json() if 200 <= response.status_code < 300 else []
        if not isinstance(data, list):
            return None
        for mr in data:
            if (mr.get("source_branch") or "").startswith(prefix):
                return self._to_pr(mr)
        return None

    def create_pr(self, *, title: str, source: str, target: str, body: str) -> PullRequest:
        payload = {
            "source_branch": source,
            "target_branch": target,
            "title": title,
            "description": body,
        }
        response = requests.post(self._mr_url(), headers=self.headers, json=payload, timeout=30)
        return self._to_pr(self._handle(response))

    def update_pr(self, number: str, *, title: str | None = None, body: str | None = None) -> PullRequest:
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["description"] = body
        response = requests.put(self._mr_url(number), headers=self.headers, json=payload, timeout=30)
        return self._to_pr(self._handle(response))

    def verify_webhook(self, secret: str, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        """GitLab does not sign the body; it sends the secret verbatim in a header."""
        if not secret:
            return True
        token = headers.get("X-Gitlab-Token")
        return hmac.compare_digest(secret, token or "")

    def parse_webhook(self, payload: dict) -> WebhookEvent | None:
        if payload.get("object_kind") != "merge_request":
            return None
        attrs = payload.get("object_attributes") or {}
        action_map = {"open": "opened", "reopen": "opened", "update": "updated"}
        action = action_map.get(attrs.get("action"), "ignored")
        return WebhookEvent(
            number=str(attrs.get("iid")),
            branch=attrs.get("source_branch") or "",
            body=attrs.get("description") or "",
            action=action,
        )
