import json
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request

from app.api import YOUGileAPI
from app.checklist import checklist_to_markdown, find_task_for_branch
from app.config import load_yougile_settings


def github_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
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


def find_existing_pr(repo: str, branch: str, token: str) -> dict | None:
    owner = repo.split("/")[0]
    query = urllib.parse.urlencode({"head": f"{owner}:{branch}", "state": "open"})
    url = f"https://api.github.com/repos/{repo}/pulls?{query}"
    pulls = github_request("GET", url, token)
    return pulls[0] if pulls else None


def get_github_repo() -> str:
    settings = load_yougile_settings()
    if settings["github_repository"]:
        return settings["github_repository"]

    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return ""

    remote = result.stdout.strip()
    match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", remote)
    if not match:
        return ""

    return f"{match.group('owner')}/{match.group('repo')}"


def _load_checklist_markdown(
    branch: str,
    yougile_task: dict | None = None,
) -> str:
    if yougile_task:
        return checklist_to_markdown(yougile_task)

    settings = load_yougile_settings()
    yougile_token = settings["token"]
    if not yougile_token:
        return ""

    api = YOUGileAPI(yougile_token)
    task = find_task_for_branch(
        api,
        branch,
        column_id=settings["column_id"] or None,
        board_id=settings["board_id"] or None,
    )
    if not task:
        return ""

    return checklist_to_markdown(task)


def create_or_update_pull_request(
    repo: str,
    branch: str,
    github_token: str,
    *,
    yougile_task: dict | None = None,
    body_prefix: str = "Auto PR after branch creation",
    base_branch: str = "dev",
) -> dict:
    checklist_md = _load_checklist_markdown(branch, yougile_task=yougile_task)
    body = body_prefix + checklist_md
    title = f"Auto PR: {branch} → {base_branch}"

    existing_pr = find_existing_pr(repo, branch, github_token)
    if existing_pr:
        pr_number = existing_pr["number"]
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        return github_request("PATCH", url, github_token, {"body": body, "title": title})

    url = f"https://api.github.com/repos/{repo}/pulls"
    return github_request(
        "POST",
        url,
        github_token,
        {"title": title, "head": branch, "base": base_branch, "body": body},
    )
