import json
import os
import sys
import urllib.error
import urllib.request

from app.api import YOUGileAPI
from app.checklist import (
    find_task_for_branch,
    markdown_checklist_to_items,
    normalize_checklist_title,
    task_id_prefix_from_branch,
)
from app.config import load_yougile_settings


def _github_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request) as response:
        body = response.read().decode()
        return json.loads(body) if body else {}


def _get_pr_body(repo: str, pull_number: str, token: str) -> str:
    url = f"https://api.github.com/repos/{repo}/pulls/{pull_number}"
    pr = _github_request("GET", url, token)
    return pr.get("body", "") or ""


def _build_checklist_payload(task: dict, pr_items: list[dict[str, bool]]) -> dict | None:
    yougile_items = []
    for checklist in task.get("checklists", []) or []:
        for item in checklist.get("items", []) or []:
            title = item.get("title") or item.get("text") or item.get("name")
            if not title:
                continue
            yougile_items.append({
                "id": item.get("id"),
                "title": normalize_checklist_title(title),
                "checked": bool(item.get("isCompleted") or item.get("isChecked")),
            })

    if not yougile_items:
        return None

    updated_checklists = []
    for checklist in task.get("checklists", []) or []:
        updated_items = []
        for item in checklist.get("items", []) or []:
            title = item.get("title") or item.get("text") or item.get("name")
            if not title:
                updated_items.append(item)
                continue

            normalized_title = normalize_checklist_title(title)
            found = next((pr_item for pr_item in pr_items if normalize_checklist_title(pr_item["title"]) == normalized_title), None)
            if found is None:
                updated_items.append(item)
                continue

            updated_item = dict(item)
            updated_item.pop("isChecked", None)
            updated_item["isCompleted"] = found["checked"]
            updated_items.append(updated_item)

        updated_checklists.append({**checklist, "items": updated_items})

    if updated_checklists == task.get("checklists", []):
        return None

    return {"checklists": updated_checklists}


def main() -> int:
    github_repo = os.environ.get("GITHUB_REPOSITORY", "")
    github_token = os.environ.get("GITHUB_TOKEN", "")
    pull_request_number = os.environ.get("PULL_REQUEST_NUMBER", "")
    branch = os.environ.get("BRANCH") or os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_REF", "").split("/")[-1]

    missing = [
        name
        for name, value in (
            ("GITHUB_REPOSITORY", github_repo),
            ("GITHUB_TOKEN", github_token),
            ("PULL_REQUEST_NUMBER", pull_request_number),
            ("BRANCH", branch),
        )
        if not value
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        return 1

    settings = load_yougile_settings()
    yougile_token = settings["token"]
    column_id = settings["column_id"] or None
    board_id = settings["board_id"] or None

    if not yougile_token:
        print("YouGile token is not configured; cannot sync checklist.", file=sys.stderr)
        return 1

    pr_body = _get_pr_body(github_repo, pull_request_number, github_token)
    pr_items = markdown_checklist_to_items(pr_body)
    if not pr_items:
        print("No checklist items found in PR body.")
        return 0

    api = YOUGileAPI(yougile_token)
    task = find_task_for_branch(api, branch, column_id=column_id, board_id=board_id)
    if not task:
        print(f"YouGile task for branch '{branch}' was not found.", file=sys.stderr)
        return 1

    payload = _build_checklist_payload(task, pr_items)
    if not payload:
        print("YouGile checklist already matches PR body or task has no checklist.")
        return 0

    try:
        updated = api.update_task(task["id"], **payload)
        print(f"YouGile task {task['id']} updated with checklist sync.")
        return 0
    except Exception as error:
        print(f"Failed to update YouGile task: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
