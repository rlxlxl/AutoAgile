import hashlib
import json

from app.checklist import (
    apply_checklist_states_to_markdown,
    normalize_checklist_title,
)


def _item_title(item: dict) -> str | None:
    return item.get("title") or item.get("text") or item.get("name")


def _item_checked(item: dict) -> bool:
    return bool(item.get("isCompleted") or item.get("isChecked"))


def yougile_states_by_title(task: dict) -> dict[str, bool]:
    """Map normalized checklist item text -> checked, across all checklists."""
    states: dict[str, bool] = {}
    for checklist in task.get("checklists", []) or []:
        for item in checklist.get("items", []) or []:
            title = _item_title(item)
            if not title:
                continue
            states[normalize_checklist_title(title)] = _item_checked(item)
    return states


def markdown_states_by_title(md_items: list[dict]) -> dict[str, bool]:
    """Map normalized text -> checked from parsed markdown checklist items."""
    return {
        normalize_checklist_title(item["title"]): bool(item["checked"])
        for item in md_items
    }


def checklist_state_hash(states_by_title: dict[str, bool]) -> str:
    """Stable hash of a normalized title -> checked map (order-independent)."""
    canonical = json.dumps(
        {title: bool(checked) for title, checked in sorted(states_by_title.items())},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_yougile_checklist_payload(
    task: dict,
    md_states: dict[str, bool],
) -> dict | None:
    """Build a ``{"checklists": [...]}`` payload applying markdown states.

    Items are matched by normalized text. Returns None when the task has no
    checklist items or when nothing actually changes.
    """
    checklists = task.get("checklists", []) or []
    if not checklists:
        return None

    updated_checklists = []
    for checklist in checklists:
        updated_items = []
        for item in checklist.get("items", []) or []:
            title = _item_title(item)
            if not title:
                updated_items.append(item)
                continue

            normalized = normalize_checklist_title(title)
            if normalized not in md_states:
                updated_items.append(item)
                continue

            updated_item = dict(item)
            updated_item.pop("isChecked", None)
            updated_item["isCompleted"] = md_states[normalized]
            updated_items.append(updated_item)

        updated_checklists.append({**checklist, "items": updated_items})

    if updated_checklists == checklists:
        return None
    return {"checklists": updated_checklists}


def apply_yougile_to_github(body: str, task: dict) -> str:
    """Return the issue body rewritten to reflect YouGile checklist states."""
    return apply_checklist_states_to_markdown(body, yougile_states_by_title(task))
