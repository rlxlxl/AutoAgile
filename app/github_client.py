import hashlib
import hmac

import requests


class GitHubClient:
    """Minimal GitHub REST client for the Pull Requests used by the webhook sync."""

    base_url = "https://api.github.com"

    def __init__(self, token: str, repo: str):
        self.repo = repo
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _handle_response(self, response: requests.Response) -> dict:
        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except ValueError:
                return {}
        raise Exception(
            f"GitHub request failed with status {response.status_code}: {response.text}"
        )

    def get_pull(self, number: int | str) -> dict:
        url = f"{self.base_url}/repos/{self.repo}/pulls/{number}"
        response = requests.get(url, headers=self.headers, timeout=30)
        return self._handle_response(response)

    def update_pull_body(self, number: int | str, body: str) -> dict:
        url = f"{self.base_url}/repos/{self.repo}/pulls/{number}"
        response = requests.patch(url, headers=self.headers, json={"body": body}, timeout=30)
        return self._handle_response(response)

    def find_pull_by_branch_prefix(self, prefix: str) -> dict | None:
        """Find an open PR whose head branch name starts with ``prefix``."""
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
                return pull
        return None


def verify_signature(secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """Verify a GitHub ``X-Hub-Signature-256`` header against ``secret``.

    Returns True when no secret is configured (verification disabled).
    """
    if not secret:
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)
