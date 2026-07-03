import re


def task_id_prefix_from_branch(branch: str) -> str | None:
    match = re.match(r"^feature/([^-]+)-", branch)
    return match.group(1) if match else None


def checklist_to_markdown(task: dict) -> str:
    checks: list[str] = []
    for checklist in task.get("checklists", []) or []:
        for item in checklist.get("items", []) or []:
            title = item.get("title") or item.get("text") or item.get("name")
            if not title:
                continue
            is_done = item.get("isCompleted") or item.get("isChecked")
            mark = "x" if is_done else " "
            checks.append(f"- [{mark}] {title}")

    if not checks:
        return ""
    return "\n\n" + "\n".join(checks)


def find_task_for_branch(
    api,
    branch: str,
    column_id: str | None = None,
    board_id: str | None = None,
) -> dict | None:
    prefix = task_id_prefix_from_branch(branch)
    if not prefix:
        return None

    column_ids: list[str] = []
    if board_id:
        column_ids = [column.id for column in api.get_columns(board_id)]
    elif column_id:
        column_ids.append(column_id)

    for current_column_id in column_ids:
        task = _find_task_in_column(api, prefix, branch, current_column_id)
        if task:
            return task
    return None


def _find_task_in_column(api, prefix: str, branch: str, column_id: str) -> dict | None:
    offset = 0
    limit = 100

    while True:
        page = api.list_tasks(column_id=column_id, limit=limit, offset=offset)
        items = page.get("content", []) if isinstance(page, dict) else []
        for item in items:
            task_id = item.get("id", "")
            if not task_id.startswith(prefix):
                continue

            return api.get_task(task_id)

        paging = page.get("paging", {}) if isinstance(page, dict) else {}
        if not paging.get("next") and len(items) < limit:
            break
        offset += limit

    return None
