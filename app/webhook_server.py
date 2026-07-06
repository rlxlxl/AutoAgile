import hashlib
import hmac
import logging

from fastapi import FastAPI, Request

from app.api import YOUGileAPI
from app.checklist import find_task_for_branch, markdown_checklist_to_items
from app.config import load_webhook_settings
from app.github_client import GitHubClient, verify_signature
from app.sync_guard import guard
from app.webhook_sync import (
    apply_yougile_to_github,
    build_yougile_checklist_payload,
    checklist_state_hash,
    markdown_states_by_title,
    yougile_states_by_title,
)
from gitlab.client import GitLabClient, verify_webhook_token

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook_sync")

app = FastAPI(title="Git platform MR/PR <-> YouGile checklist sync")

settings = load_webhook_settings()
yougile_api = YOUGileAPI(settings["yougile_token"]) if settings["yougile_token"] else None
github_client = (
    GitHubClient(settings["github_token"], settings["github_repo"])
    if settings["github_token"] and settings["github_repo"]
    else None
)
gitlab_client = (
    GitLabClient(settings["gitlab_token"], settings["gitlab_project_id"])
    if settings["gitlab_token"] and settings["gitlab_project_id"]
    else None
)


def _resolve_task_by_branch(branch: str) -> dict | None:
    """Resolve a YouGile task from a PR/MR head branch (feature/<shortId>-...)."""
    return find_task_for_branch(
        yougile_api,
        branch,
        column_id=settings.get("yougile_column_id") or None,
        board_id=settings.get("yougile_board_id") or None,
    )


def _extract_yougile_task_ids(payload) -> list[str]:
    """Pull task ids from a YouGile webhook payload (object or list of events)."""
    events = payload if isinstance(payload, list) else [payload]
    task_ids: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        inner = event.get("payload") if isinstance(event.get("payload"), dict) else event
        for key in ("id", "taskId", "task_id"):
            value = inner.get(key)
            if value:
                task_ids.append(str(value))
                break
    return task_ids


def _sync_git_platform_from_yougile(task_id: str, task: dict, prefix: str) -> list[dict]:
    """Push YouGile checklist state to configured GitHub PR and/or GitLab MR."""
    results: list[dict] = []

    if github_client is not None:
        pull = github_client.find_pull_by_branch_prefix(prefix)
        if not pull:
            results.append({"task_id": task_id, "platform": "github", "skipped": "pr_not_found"})
        else:
            number = pull.get("number")
            current_body = pull.get("body") or ""
            new_body = apply_yougile_to_github(current_body, task)
            if new_body == current_body:
                results.append({"task_id": task_id, "platform": "github", "number": number, "status": "noop"})
            else:
                github_client.update_pull_body(number, new_body)
                new_states = markdown_states_by_title(markdown_checklist_to_items(new_body))
                guard.remember("github", str(number), checklist_state_hash(new_states))
                logger.info("Synced YouGile task %s -> GitHub PR #%s", task_id, number)
                results.append({"task_id": task_id, "platform": "github", "number": number, "status": "synced"})

    if gitlab_client is not None:
        mr = gitlab_client.find_mr_by_branch_prefix(prefix)
        if not mr:
            results.append({"task_id": task_id, "platform": "gitlab", "skipped": "mr_not_found"})
        else:
            iid = mr.get("iid")
            current_description = mr.get("description") or ""
            new_description = apply_yougile_to_github(current_description, task)
            if new_description == current_description:
                results.append({"task_id": task_id, "platform": "gitlab", "iid": iid, "status": "noop"})
            else:
                gitlab_client.update_merge_request_description(iid, new_description)
                new_states = markdown_states_by_title(markdown_checklist_to_items(new_description))
                guard.remember("gitlab", str(iid), checklist_state_hash(new_states))
                logger.info("Synced YouGile task %s -> GitLab MR !%s", task_id, iid)
                results.append({"task_id": task_id, "platform": "gitlab", "iid": iid, "status": "synced"})

    return results


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "yougile": bool(yougile_api),
        "github": bool(github_client),
        "gitlab": bool(gitlab_client),
    }


@app.post("/webhook/github")
async def webhook_github(request: Request) -> dict:
    raw_body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(settings["github_webhook_secret"], raw_body, signature):
        return {"skipped": "invalid_signature"}

    if yougile_api is None:
        return {"skipped": "yougile_not_configured"}

    payload = await request.json()

    pull = payload.get("pull_request")
    if not isinstance(pull, dict):
        return {"skipped": "not_a_pull_request"}

    if payload.get("action") not in ("opened", "edited"):
        return {"skipped": "action_ignored"}

    number = pull.get("number")
    branch = (pull.get("head") or {}).get("ref") or ""
    body = pull.get("body") or ""

    md_items = markdown_checklist_to_items(body)
    if not md_items:
        return {"skipped": "no_checklist_items"}

    md_states = markdown_states_by_title(md_items)
    incoming_hash = checklist_state_hash(md_states)
    if guard.seen("github", str(number), incoming_hash):
        logger.info("Ignoring echo GitHub webhook for PR #%s", number)
        return {"skipped": "echo"}

    task = _resolve_task_by_branch(branch)
    if not task:
        return {"skipped": "task_not_found", "branch": branch}

    task_payload = build_yougile_checklist_payload(task, md_states)
    if not task_payload:
        return {"status": "noop", "reason": "already_in_sync"}

    yougile_api.update_task(task["id"], **task_payload)
    resulting_hash = checklist_state_hash(
        yougile_states_by_title({"checklists": task_payload["checklists"]})
    )
    guard.remember("yougile", task["id"], resulting_hash)
    logger.info("Synced GitHub PR #%s -> YouGile task %s", number, task["id"])
    return {"status": "synced", "task_id": task["id"]}


@app.post("/webhook/gitlab")
async def webhook_gitlab(request: Request) -> dict:
    token_header = request.headers.get("X-Gitlab-Token")
    if not verify_webhook_token(settings["gitlab_webhook_secret"], token_header):
        return {"skipped": "invalid_signature"}

    if yougile_api is None:
        return {"skipped": "yougile_not_configured"}

    payload = await request.json()

    if payload.get("object_kind") != "merge_request":
        return {"skipped": "not_a_merge_request"}

    attrs = payload.get("object_attributes") or {}
    if attrs.get("action") not in ("open", "update"):
        return {"skipped": "action_ignored"}

    iid = attrs.get("iid")
    branch = attrs.get("source_branch") or ""
    description = attrs.get("description") or ""

    md_items = markdown_checklist_to_items(description)
    if not md_items:
        return {"skipped": "no_checklist_items"}

    md_states = markdown_states_by_title(md_items)
    incoming_hash = checklist_state_hash(md_states)
    if guard.seen("gitlab", str(iid), incoming_hash):
        logger.info("Ignoring echo GitLab webhook for MR !%s", iid)
        return {"skipped": "echo"}

    task = _resolve_task_by_branch(branch)
    if not task:
        return {"skipped": "task_not_found", "branch": branch}

    task_payload = build_yougile_checklist_payload(task, md_states)
    if not task_payload:
        return {"status": "noop", "reason": "already_in_sync"}

    yougile_api.update_task(task["id"], **task_payload)
    resulting_hash = checklist_state_hash(
        yougile_states_by_title({"checklists": task_payload["checklists"]})
    )
    guard.remember("yougile", task["id"], resulting_hash)
    logger.info("Synced GitLab MR !%s -> YouGile task %s", iid, task["id"])
    return {"status": "synced", "task_id": task["id"]}


@app.post("/webhook/yougile")
async def webhook_yougile(request: Request) -> dict:
    raw_body = await request.body()
    secret = settings["yougile_webhook_secret"]
    if secret:
        signature = request.headers.get("X-Yougile-Signature") or request.headers.get(
            "X-Signature"
        )
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        provided = (signature or "").removeprefix("sha256=")
        if not hmac.compare_digest(expected, provided):
            return {"skipped": "invalid_signature"}

    if yougile_api is None or (github_client is None and gitlab_client is None):
        return {"skipped": "not_configured"}

    payload = await request.json()
    task_ids = _extract_yougile_task_ids(payload)
    if not task_ids:
        return {"skipped": "no_task_id"}

    results = []
    for task_id in task_ids:
        try:
            task = yougile_api.get_task(task_id)
        except Exception as error:
            logger.warning("Could not fetch YouGile task %s: %s", task_id, error)
            results.append({"task_id": task_id, "skipped": "fetch_failed"})
            continue

        yg_states = yougile_states_by_title(task)
        if not yg_states:
            results.append({"task_id": task_id, "skipped": "no_checklist"})
            continue

        incoming_hash = checklist_state_hash(yg_states)
        if guard.seen("yougile", task_id, incoming_hash):
            logger.info("Ignoring echo YouGile webhook for task %s", task_id)
            results.append({"task_id": task_id, "skipped": "echo"})
            continue

        prefix = f"feature/{task_id.split('-')[0]}-"
        platform_results = _sync_git_platform_from_yougile(task_id, task, prefix)
        if platform_results:
            results.extend(platform_results)
        else:
            results.append({"task_id": task_id, "skipped": "no_git_platform_configured"})

    return {"results": results}
