import requests

from app.models import YouGileItem


class YOUGileAPI:
    base_url = "https://ru.yougile.com/api-v2"

    def __init__(self, bearer_token: str):
        self.headers = {
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
        }

    def _handle_response(self, response: requests.Response):
        # Accept 200/201 with JSON body, 204 no content
        if response.status_code in (200, 201):
            try:
                return response.json()
            except ValueError:
                return {}
        if response.status_code == 204:
            return {}
        raise Exception(
            f"API request failed with status code {response.status_code}: {response.text}"
        )

    @staticmethod
    def _parse_list(response_data) -> list[YouGileItem]:
        if isinstance(response_data, list):
            items = response_data
        elif isinstance(response_data, dict):
            items = response_data.get("content", [])
        else:
            items = []

        result = []
        for item in items:
            item_id = item.get("id")
            title = item.get("title", "")
            if item_id:
                result.append(YouGileItem(id=item_id, title=title))
        return result

    def _get(self, resource: str, params: dict | None = None) -> list[YouGileItem]:
        url = f"{self.base_url}/{resource}"
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        return self._parse_list(self._handle_response(response))

    def validate_token(self) -> bool:
        try:
            self.get_projects()
            return True
        except Exception:
            return False

    def get_projects(self) -> list[YouGileItem]:
        return self._get("projects")

    def get_boards(self, project_id: str) -> list[YouGileItem]:
        return self._get("boards", params={"projectId": project_id})

    def get_columns(self, board_id: str) -> list[YouGileItem]:
        return self._get("columns", params={"boardId": board_id})

    def get_tasks(self, column_id: str) -> list[YouGileItem]:
        return self._get("tasks", params={"columnId": column_id})

    def list_tasks(
        self,
        column_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict:
        params: dict[str, str | int] = {"limit": limit, "offset": offset}
        if column_id:
            params["columnId"] = column_id

        url = f"{self.base_url}/task-list"
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        return self._handle_response(response)

    def get_task(self, task_id: str) -> dict:
        url = f"{self.base_url}/tasks/{task_id}"
        response = requests.get(url, headers=self.headers, timeout=30)
        return self._handle_response(response)

    def create_task(
        self,
        title: str,
        column_id: str,
        description: str | None = None,
        checklists: list | None = None,
    ) -> dict:
        payload: dict = {"title": title, "columnId": column_id}
        if description:
            payload["description"] = description
        if checklists:
            payload["checklists"] = checklists

        url = f"{self.base_url}/tasks"
        response = requests.post(url, headers=self.headers, json=payload, timeout=30)
        return self._handle_response(response)

    def update_task(self, task_id: str, **fields) -> dict:
        url = f"{self.base_url}/tasks/{task_id}"
        response = requests.patch(url, headers=self.headers, json=fields, timeout=30)
        if response.status_code == 404:
            # Some deployments don't support PATCH; fetch current, merge and PUT
            current = self.get_task(task_id)
            if not isinstance(current, dict):
                raise Exception(f"Unexpected task payload for {task_id}: {current}")
            merged = {**current, **fields}
            # Remove read-only/server-managed keys that cause 400 Bad Request
            readonly_keys = {"id", "timestamp", "createdBy", "type", "createdAt", "updatedAt"}
            for k in list(merged.keys()):
                if k in readonly_keys:
                    merged.pop(k, None)

            response = requests.put(url, headers=self.headers, json=merged, timeout=30)

        return self._handle_response(response)
