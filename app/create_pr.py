import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

from app.api import YOUGileAPI
from app.checklist import checklist_to_markdown, find_task_for_branch
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


def _find_existing_pr(repo: str, branch: str, token: str) -> dict | None:
    owner = repo.split("/")[0]
    query = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open"})
    url = f"https://api.github.com/repos/{repo}/pulls?{query}"
    pulls = _github_request("GET", url, token)
    return pulls[0] if pulls else None


def main() -> int:
    github_repo = os.environ.get("GITHUB_REPOSITORY", "")
    branch = (
        os.environ.get("BRANCH")
        or os.environ.get("GITHUB_REF_NAME")
        or os.environ.get("GITHUB_REF", "").split("/")[-1]
    )
    github_token = os.environ.get("GITHUB_TOKEN", "")
    settings = load_yougile_settings()
    yougile_token = settings["token"]
    column_id = settings["column_id"] or None
    board_id = settings["board_id"] or None

    missing = [
        name
        for name, value in (
            ("GITHUB_REPOSITORY", github_repo),
            ("BRANCH/GITHUB_REF_NAME", branch),
            ("GITHUB_TOKEN", github_token),
        )
        if not value
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        return 1

    checklist_md = ""
    if not yougile_token:
        print("YouGile token is not configured in yougile.env; creating PR without checklist.", file=sys.stderr)
    else:
        try:
            api = YOUGileAPI(yougile_token)
            task = find_task_for_branch(api, branch, column_id=column_id, board_id=board_id)
            if task:
                checklist_md = checklist_to_markdown(task)
                print(f"Found YouGile task {task.get('id')} with {checklist_md.count('- [')} checklist items.")
            else:
                print(
                    f"YouGile task for branch '{branch}' was not found "
                    f"(columnId={column_id}, boardId={board_id}).",
                    file=sys.stderr,
                )
        except Exception as error:
            print(f"Failed to load YouGile checklist: {error}", file=sys.stderr)

    body = "Auto PR after CI success" + checklist_md
    title = f"Auto PR: {branch} → dev"

    try:
        existing_pr = _find_existing_pr(github_repo, branch, github_token)
        if existing_pr:
            pr_number = existing_pr["number"]
            url = f"https://api.github.com/repos/{github_repo}/pulls/{pr_number}"
            updated = _github_request("PATCH", url, github_token, {"body": body, "title": title})
            print(json.dumps(updated, ensure_ascii=False))
            return 0

        url = f"https://api.github.com/repos/{github_repo}/pulls"
        created = _github_request(
            "POST",
            url,
            github_token,
            {"title": title, "head": branch, "base": "dev", "body": body},
        )
        print(json.dumps(created, ensure_ascii=False))
        return 0
    except urllib.error.HTTPError as error:
        print(error.read().decode(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
