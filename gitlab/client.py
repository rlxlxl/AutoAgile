import hmac
from urllib.parse import quote

import requests


class GitLabClient:
    """Minimal GitLab REST client for Merge Requests used by the webhook sync."""

    base_url = "https://gitlab.com/api/v4"

    def __init__(self, token: str, project_id: str):
        self.project_id = self._encode_project_id(project_id)
        self.headers = {
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _encode_project_id(project_id: str) -> str:
        project_id = str(project_id).strip()
        if project_id.isdigit():
            return project_id
        return quote(project_id, safe="")

    def _handle_response(self, response: requests.Response) -> dict:
        if 200 <= response.status_code < 300:
            try:
                return response.json()
            except ValueError:
                return {}
        raise Exception(
            f"GitLab request failed with status {response.status_code}: {response.text}"
        )

    def get_merge_request(self, iid: int | str) -> dict:
        url = f"{self.base_url}/projects/{self.project_id}/merge_requests/{iid}"
        response = requests.get(url, headers=self.headers, timeout=30)
        return self._handle_response(response)

    def update_merge_request_description(self, iid: int | str, description: str) -> dict:
        url = f"{self.base_url}/projects/{self.project_id}/merge_requests/{iid}"
        response = requests.put(
            url,
            headers=self.headers,
            json={"description": description},
            timeout=30,
        )
        return self._handle_response(response)

    def find_mr_by_branch_prefix(self, prefix: str) -> dict | None:
        """Find an open MR whose source branch name starts with ``prefix``."""
        url = f"{self.base_url}/projects/{self.project_id}/merge_requests"
        response = requests.get(
            url,
            headers=self.headers,
            params={"state": "opened", "per_page": 100},
            timeout=30,
        )
        data = response.json() if 200 <= response.status_code < 300 else []
        if not isinstance(data, list):
            return None
        for mr in data:
            source_branch = mr.get("source_branch") or ""
            if source_branch.startswith(prefix):
                return mr
        return None


def verify_webhook_token(secret: str, token_header: str | None) -> bool:
    """Verify GitLab ``X-Gitlab-Token`` header against ``secret``.

    Returns True when no secret is configured (verification disabled).
    """
    if not secret:
        return True
    if not token_header:
        return False
    return hmac.compare_digest(secret, token_header)
