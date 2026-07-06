import hashlib
import hmac
import logging

from fastapi import FastAPI, Request

from app.api import YOUGileAPI
from app.checklist import (
    markdown_checklist_to_items,
    markdown_to_yougile_checklists,
    parse_task_marker,
)
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

app = FastAPI(title="GitHub <-> YouGile checklist sync")

settings = load_webhook_settings()
yougile_api = YOUGileAPI(settings["yougile_token"]) if settings["yougile_token"] else None
github_client = (
    GitHubClient(settings["github_token"], settings["github_repo"])
    if settings["github_token"] and settings["github_repo"]
    else None
)


def _looks_like_full_id(marker: str) -> bool:
    return len(marker) >= 32 and marker.count("-") >= 4


def _resolve_task(marker: str) -> dict | None:
    """Resolve a YouGile task from a title marker (full id or short prefix)."""
    if _looks_like_full_id(marker):
        try:
            return yougile_api.get_task(marker)
        except Exception as error:
            logger.warning("Could not fetch YouGile task %s: %s", marker, error)
            return None

    board_id = settings.get("yougile_board_id")
    column_ids: list[str] = []
    if board_id:
        column_ids = [column.id for column in yougile_api.get_columns(board_id)]
    elif settings.get("yougile_column_id"):
        column_ids = [settings["yougile_column_id"]]

    for column_id in column_ids:
        offset = 0
        while True:
            page = yougile_api.list_tasks(column_id=column_id, limit=100, offset=offset)
            items = page.get("content", []) if isinstance(page, dict) else []
            for item in items:
                task_id = item.get("id", "")
                if task_id.startswith(marker):
                    return yougile_api.get_task(task_id)
            paging = page.get("paging", {}) if isinstance(page, dict) else {}
            if not paging.get("next") and len(items) < 100:
                break
            offset += 100
    return None


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


def _handle_issue_opened(payload: dict) -> dict:
    """Create a linked YouGile task for a brand-new GitHub Issue."""
    issue = payload.get("issue") or {}
    number = issue.get("number")
    title = issue.get("title", "") or ""
    body = issue.get("body", "") or ""

    if parse_task_marker(title):
        return {"skipped": "already_linked"}

    column_id = settings.get("yougile_column_id")
    if not column_id:
        return {"skipped": "no_column_configured"}

    repo = settings.get("github_repo", "")
    description = f"GitHub-Issue: {repo}#{number}"
    checklists = markdown_to_yougile_checklists(body)

    try:
        task = yougile_api.create_task(
            title=title,
            column_id=column_id,
            description=description,
            checklists=checklists or None,
        )
    except Exception as error:
        logger.warning("Could not create YouGile task for issue #%s: %s", number, error)
        return {"skipped": "create_failed"}

    task_id = task.get("id")
    if not task_id:
        return {"skipped": "no_task_id_returned"}

    if github_client is not None:
        try:
            github_client.update_issue_title(number, f"[{task_id}] {title}")
        except Exception as error:
            logger.warning("Could not update issue #%s title: %s", number, error)

    logger.info("Created YouGile task %s from GitHub issue #%s", task_id, number)
    return {"status": "created", "task_id": task_id, "number": number}


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
    action = payload.get("action")

    if action == "opened":
        return _handle_issue_opened(payload)

    if action != "edited":
        return {"skipped": "action_not_edited"}

    issue = payload.get("issue") or {}
    number = issue.get("number")
    title = issue.get("title", "")
    comment = payload.get("comment") or {}
    body = comment.get("body") if comment else issue.get("body", "")
    body = body or ""

    marker = parse_task_marker(title)
    if not marker:
        return {"skipped": "no_task_marker"}

    md_items = markdown_checklist_to_items(body)
    if not md_items:
        return {"skipped": "no_checklist_items"}

    md_states = markdown_states_by_title(md_items)
    incoming_hash = checklist_state_hash(md_states)
    if guard.seen("github", str(number), incoming_hash):
        logger.info("Ignoring echo GitHub webhook for issue #%s", number)
        return {"skipped": "echo"}

    task = _resolve_task(marker)
    if not task:
        return {"skipped": "task_not_found", "marker": marker}

    task_payload = build_yougile_checklist_payload(task, md_states)
    if not task_payload:
        return {"status": "noop", "reason": "already_in_sync"}

    yougile_api.update_task(task["id"], **task_payload)
    resulting_hash = checklist_state_hash(
        yougile_states_by_title({"checklists": task_payload["checklists"]})
    )
    guard.remember("yougile", task["id"], resulting_hash)
    logger.info("Synced GitHub issue #%s -> YouGile task %s", number, task["id"])
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

        issue = github_client.find_issue_by_marker(task_id)
        if not issue:
            results.append({"task_id": task_id, "skipped": "issue_not_found"})
            continue

        number = issue.get("number")
        current_body = issue.get("body") or ""
        new_body = apply_yougile_to_github(current_body, task)
        if new_body == current_body:
            results.append({"task_id": task_id, "number": number, "status": "noop"})
            continue

        github_client.update_issue_body(number, new_body)
        new_states = markdown_states_by_title(markdown_checklist_to_items(new_body))
        guard.remember("github", str(number), checklist_state_hash(new_states))
        logger.info("Synced YouGile task %s -> GitHub issue #%s", task_id, number)
        results.append({"task_id": task_id, "number": number, "status": "synced"})

    return {"results": results}
