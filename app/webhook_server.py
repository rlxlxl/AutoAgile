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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook_sync")

app = FastAPI(title="GitHub PR <-> YouGile checklist sync")

settings = load_webhook_settings()
yougile_api = YOUGileAPI(settings["yougile_token"]) if settings["yougile_token"] else None
github_client = (
    GitHubClient(settings["github_token"], settings["github_repo"])
    if settings["github_token"] and settings["github_repo"]
    else None
)


def _resolve_task_by_branch(branch: str) -> dict | None:
    """Resolve a YouGile task from a PR head branch (feature/<shortId>-...)."""
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


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "yougile": bool(yougile_api),
        "github": bool(github_client),
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

    if yougile_api is None or github_client is None:
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
        pull = github_client.find_pull_by_branch_prefix(prefix)
        if not pull:
            results.append({"task_id": task_id, "skipped": "pr_not_found"})
            continue

        number = pull.get("number")
        current_body = pull.get("body") or ""
        new_body = apply_yougile_to_github(current_body, task)
        if new_body == current_body:
            results.append({"task_id": task_id, "number": number, "status": "noop"})
            continue

        github_client.update_pull_body(number, new_body)
        new_states = markdown_states_by_title(markdown_checklist_to_items(new_body))
        guard.remember("github", str(number), checklist_state_hash(new_states))
        logger.info("Synced YouGile task %s -> GitHub PR #%s", task_id, number)
        results.append({"task_id": task_id, "number": number, "status": "synced"})

    return {"results": results}
