import hashlib
import hmac
import logging

from fastapi import FastAPI, Request

from app.core.api import YOUGileAPI
from app.core.checklist import find_task_for_branch, markdown_checklist_to_items
from app.core.checklist_sync import (
    apply_yougile_to_markdown,
    build_yougile_checklist_payload,
    checklist_state_hash,
    markdown_states_by_title,
    yougile_states_by_title,
)
from app.core.config import load_webhook_settings
from app.core.sync_guard import guard
from app.providers.base import get_provider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webhook_sync")

app = FastAPI(title="SCM (GitHub/GitLab) <-> YouGile checklist sync")

settings = load_webhook_settings()
yougile_api = YOUGileAPI(settings["yougile_token"]) if settings["yougile_token"] else None
provider = get_provider(settings) if settings.get("provider_configured") else None


def _resolve_task_by_branch(branch: str) -> dict | None:
    """Resolve a YouGile task from a PR/MR source branch (feature/<shortId>-...)."""
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
        "provider": settings.get("git_provider"),
        "yougile": bool(yougile_api),
        "scm": bool(provider),
    }


async def _handle_scm_webhook(request: Request) -> dict:
    """Direction: PR/MR checklist edit -> YouGile task checklist."""
    raw_body = await request.body()
    if not provider.verify_webhook(settings["webhook_secret"], raw_body, request.headers):
        return {"skipped": "invalid_signature"}

    if yougile_api is None:
        return {"skipped": "yougile_not_configured"}

    payload = await request.json()
    event = provider.parse_webhook(payload)
    if event is None:
        return {"skipped": "not_a_merge_request"}

    if event.action not in ("opened", "updated"):
        return {"skipped": "action_ignored"}

    md_items = markdown_checklist_to_items(event.body)
    if not md_items:
        return {"skipped": "no_checklist_items"}

    md_states = markdown_states_by_title(md_items)
    incoming_hash = checklist_state_hash(md_states)
    if guard.seen("scm", event.number, incoming_hash):
        logger.info("Ignoring echo SCM webhook for PR/MR #%s", event.number)
        return {"skipped": "echo"}

    task = _resolve_task_by_branch(event.branch)
    if not task:
        return {"skipped": "task_not_found", "branch": event.branch}

    task_payload = build_yougile_checklist_payload(task, md_states)
    if not task_payload:
        return {"status": "noop", "reason": "already_in_sync"}

    yougile_api.update_task(task["id"], **task_payload)
    resulting_hash = checklist_state_hash(
        yougile_states_by_title({"checklists": task_payload["checklists"]})
    )
    guard.remember("yougile", task["id"], resulting_hash)
    logger.info("Synced SCM PR/MR #%s -> YouGile task %s", event.number, task["id"])
    return {"status": "synced", "task_id": task["id"]}


@app.post("/webhook/scm")
async def webhook_scm(request: Request) -> dict:
    if provider is None:
        return {"skipped": "not_configured"}
    return await _handle_scm_webhook(request)


@app.post("/webhook/github")
async def webhook_github(request: Request) -> dict:
    """Alias kept for backwards compatibility with existing GitHub webhooks."""
    if provider is None:
        return {"skipped": "not_configured"}
    return await _handle_scm_webhook(request)


@app.post("/webhook/gitlab")
async def webhook_gitlab(request: Request) -> dict:
    if provider is None:
        return {"skipped": "not_configured"}
    return await _handle_scm_webhook(request)


@app.post("/webhook/yougile")
async def webhook_yougile(request: Request) -> dict:
    """Direction: YouGile task checklist -> PR/MR body."""
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

    if yougile_api is None or provider is None:
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
        pull = provider.find_pr_by_branch_prefix(prefix)
        if not pull:
            results.append({"task_id": task_id, "skipped": "pr_not_found"})
            continue

        current_body = pull.body or ""
        new_body = apply_yougile_to_markdown(current_body, task)
        if new_body == current_body:
            results.append({"task_id": task_id, "number": pull.number, "status": "noop"})
            continue

        provider.update_pr(pull.number, body=new_body)
        new_states = markdown_states_by_title(markdown_checklist_to_items(new_body))
        guard.remember("scm", pull.number, checklist_state_hash(new_states))
        logger.info("Synced YouGile task %s -> SCM PR/MR #%s", task_id, pull.number)
        results.append({"task_id": task_id, "number": pull.number, "status": "synced"})

    return {"results": results}
