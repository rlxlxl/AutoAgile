import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from app.api import YOUGileAPI
from app.checklist import checklist_to_markdown, find_task_for_branch
from app.config import load_yougile_settings

GITLAB_API = "https://gitlab.com/api/v4"


def _encode_project_id(project_id: str) -> str:
    project_id = str(project_id).strip()
    if project_id.isdigit():
        return project_id
    return urllib.parse.quote(project_id, safe="")


def _gitlab_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    headers = {
        "PRIVATE-TOKEN": token,
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request) as response:
        body = response.read().decode()
        return json.loads(body) if body else {}


def _find_existing_mr(project_id: str, branch: str, token: str) -> dict | None:
    encoded = _encode_project_id(project_id)
    query = urllib.parse.urlencode({"state": "opened", "source_branch": branch})
    url = f"{GITLAB_API}/projects/{encoded}/merge_requests?{query}"
    mrs = _gitlab_request("GET", url, token)
    return mrs[0] if mrs else None


def main() -> int:
    project_id = os.environ.get("GITLAB_PROJECT_ID") or os.environ.get("CI_PROJECT_ID", "")
    branch = (
        os.environ.get("BRANCH")
        or os.environ.get("CI_COMMIT_REF_NAME")
        or os.environ.get("CI_COMMIT_BRANCH", "")
    )
    gitlab_token = os.environ.get("GITLAB_TOKEN", "")
    settings = load_yougile_settings()
    yougile_token = settings["token"]
    column_id = settings["column_id"] or None
    board_id = settings["board_id"] or None

    missing = [
        name
        for name, value in (
            ("GITLAB_PROJECT_ID/CI_PROJECT_ID", project_id),
            ("BRANCH/CI_COMMIT_REF_NAME", branch),
            ("GITLAB_TOKEN", gitlab_token),
        )
        if not value
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        return 1

    checklist_md = ""
    if not yougile_token:
        print(
            "YouGile token is not configured; creating MR without checklist.",
            file=sys.stderr,
        )
    else:
        try:
            api = YOUGileAPI(yougile_token)
            task = find_task_for_branch(api, branch, column_id=column_id, board_id=board_id)
            if task:
                checklist_md = checklist_to_markdown(task)
                print(
                    f"Found YouGile task {task.get('id')} "
                    f"with {checklist_md.count('- [')} checklist items."
                )
            else:
                print(
                    f"YouGile task for branch '{branch}' was not found "
                    f"(columnId={column_id}, boardId={board_id}).",
                    file=sys.stderr,
                )
        except Exception as error:
            print(f"Failed to load YouGile checklist: {error}", file=sys.stderr)

    description = "Auto MR after CI success" + checklist_md
    title = f"Auto MR: {branch} → dev"
    encoded = _encode_project_id(project_id)

    try:
        existing_mr = _find_existing_mr(project_id, branch, gitlab_token)
        if existing_mr:
            iid = existing_mr["iid"]
            url = f"{GITLAB_API}/projects/{encoded}/merge_requests/{iid}"
            updated = _gitlab_request(
                "PUT",
                url,
                gitlab_token,
                {"description": description, "title": title},
            )
            print(json.dumps(updated, ensure_ascii=False))
            return 0

        url = f"{GITLAB_API}/projects/{encoded}/merge_requests"
        created = _gitlab_request(
            "POST",
            url,
            gitlab_token,
            {
                "title": title,
                "source_branch": branch,
                "target_branch": "dev",
                "description": description,
            },
        )
        print(json.dumps(created, ensure_ascii=False))
        return 0
    except urllib.error.HTTPError as error:
        print(error.read().decode(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
