import os
import sys

from app.core.api import YOUGileAPI
from app.core.checklist import checklist_to_markdown, find_task_for_branch
from app.core.config import load_webhook_settings
from app.providers.base import get_provider


def _resolve_branch() -> str:
    return (
        os.environ.get("BRANCH")
        or os.environ.get("GITHUB_REF_NAME")
        or os.environ.get("CI_COMMIT_REF_NAME")
        or os.environ.get("GITHUB_REF", "").split("/")[-1]
    )


def main() -> int:
    settings = load_webhook_settings()
    provider_name = settings.get("git_provider")
    branch = _resolve_branch()
    target = os.environ.get("TARGET_BRANCH", "dev")

    if not branch:
        print(
            "Branch is not set (BRANCH / GITHUB_REF_NAME / CI_COMMIT_REF_NAME).",
            file=sys.stderr,
        )
        return 1

    if not settings.get("provider_configured"):
        print(
            f"Git provider '{provider_name}' is not configured "
            "(check tokens / repo / project id).",
            file=sys.stderr,
        )
        return 1

    provider = get_provider(settings)

    yougile_token = settings["yougile_token"]
    column_id = settings.get("yougile_column_id") or None
    board_id = settings.get("yougile_board_id") or None

    checklist_md = ""
    if not yougile_token:
        print(
            "YouGile token is not configured; creating PR/MR without checklist.",
            file=sys.stderr,
        )
    else:
        try:
            api = YOUGileAPI(yougile_token)
            task = find_task_for_branch(api, branch, column_id=column_id, board_id=board_id)
            if task:
                checklist_md = checklist_to_markdown(task)
                print(
                    f"Found YouGile task {task.get('id')} with "
                    f"{checklist_md.count('- [')} checklist items."
                )
            else:
                print(
                    f"YouGile task for branch '{branch}' was not found "
                    f"(columnId={column_id}, boardId={board_id}).",
                    file=sys.stderr,
                )
        except Exception as error:
            print(f"Failed to load YouGile checklist: {error}", file=sys.stderr)

    body = "Auto PR after CI success" + checklist_md
    title = f"Auto PR: {branch} → {target}"

    try:
        existing = provider.find_pr_by_branch(branch)
        if existing:
            updated = provider.update_pr(existing.number, title=title, body=body)
            print(f"Updated {provider.name} PR/MR #{updated.number} for branch '{branch}'.")
            return 0

        created = provider.create_pr(title=title, source=branch, target=target, body=body)
        print(f"Created {provider.name} PR/MR #{created.number} for branch '{branch}'.")
        return 0
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
