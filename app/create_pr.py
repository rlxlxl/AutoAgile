import json
import os
import sys
import urllib.error

from app.config import load_yougile_settings
from app.github_pr import create_or_update_pull_request, get_github_repo


def main() -> int:
    github_repo = os.environ.get("GITHUB_REPOSITORY", "").strip() or get_github_repo()
    branch = (
        os.environ.get("BRANCH")
        or os.environ.get("GITHUB_REF_NAME")
        or os.environ.get("GITHUB_REF", "").split("/")[-1]
    )
    github_token = os.environ.get("GITHUB_TOKEN", "").strip() or load_yougile_settings()["github_token"]
    body_prefix = os.environ.get("PR_BODY_PREFIX", "Auto PR after branch creation")

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

    try:
        result = create_or_update_pull_request(
            github_repo,
            branch,
            github_token,
            body_prefix=body_prefix,
        )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except urllib.error.HTTPError as error:
        print(error.read().decode(), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
