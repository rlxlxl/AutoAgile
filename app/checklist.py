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


def markdown_checklist_to_items(body: str) -> list[dict[str, bool]]:
    items: list[dict[str, bool]] = []
    for line in body.splitlines():
        match = re.match(r"^\s*[-*]\s+\[([ xX])\]\s+(.*\S)\s*$", line)
        if not match:
            continue
        checked = match.group(1).lower() == "x"
        title = match.group(2).strip()
        if not title:
            continue
        items.append({"title": title, "checked": checked})
    return items


def normalize_checklist_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())


def apply_checklist_states_to_markdown(
    body: str,
    states_by_title: dict[str, bool],
) -> str:
    """Rewrite ``- [ ]`` / ``- [x]`` lines in ``body`` to match YouGile states.

    Items are matched by normalized text. Lines whose title is not present in
    ``states_by_title`` are left untouched, so any non-checklist content in the
    body is preserved verbatim.
    """
    line_pattern = re.compile(r"^(\s*[-*]\s+\[)([ xX])(\]\s+)(.*\S)(\s*)$")

    def _replace(match: re.Match) -> str:
        prefix, _mark, middle, title, trailing = match.groups()
        normalized = normalize_checklist_title(title)
        if normalized not in states_by_title:
            return match.group(0)
        mark = "x" if states_by_title[normalized] else " "
        return f"{prefix}{mark}{middle}{title}{trailing}"

    updated_lines = [line_pattern.sub(_replace, line) for line in body.splitlines()]
    result = "\n".join(updated_lines)
    if body.endswith("\n"):
        result += "\n"
    return result


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
