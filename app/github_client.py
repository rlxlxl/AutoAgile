import hashlib
import hmac

import requests


class GitHubClient:
    """Minimal GitHub REST client for the Issues used by the webhook sync."""

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

    def get_issue(self, number: int | str) -> dict:
        url = f"{self.base_url}/repos/{self.repo}/issues/{number}"
        response = requests.get(url, headers=self.headers, timeout=30)
        return self._handle_response(response)

    def update_issue_body(self, number: int | str, body: str) -> dict:
        return self.update_issue(number, body=body)

    def update_issue_title(self, number: int | str, title: str) -> dict:
        return self.update_issue(number, title=title)

    def update_issue(self, number: int | str, **fields) -> dict:
        url = f"{self.base_url}/repos/{self.repo}/issues/{number}"
        response = requests.patch(url, headers=self.headers, json=fields, timeout=30)
        return self._handle_response(response)

    def create_issue(self, title: str, body: str = "") -> dict:
        url = f"{self.base_url}/repos/{self.repo}/issues"
        response = requests.post(
            url, headers=self.headers, json={"title": title, "body": body}, timeout=30
        )
        return self._handle_response(response)

    def find_issue_by_marker(self, task_id: str) -> dict | None:
        """Find an issue whose title contains the ``[task_id]`` marker."""
        query = f'repo:{self.repo} in:title "[{task_id}]"'
        url = f"{self.base_url}/search/issues"
        response = requests.get(
            url,
            headers=self.headers,
            params={"q": query, "per_page": 20},
            timeout=30,
        )
        data = self._handle_response(response)
        marker = f"[{task_id}]"
        for item in data.get("items", []) or []:
            if marker in (item.get("title") or ""):
                return item
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
