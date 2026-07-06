import os
from urllib.parse import urlparse

from dotenv import dotenv_values, load_dotenv

from app.core.models import MonitorConfig

# In GitLab/GitHub CI all secrets come from pipeline variables, not .env files.
if not os.environ.get("CI"):
    load_dotenv()

ENV_KEYS = (
    "YOUGILE_BEARER_TOKEN",
    "YOUGILE_PROJECT_ID",
    "YOUGILE_BOARD_ID",
    "YOUGILE_COLUMN_ID",
    "YOUGILE_POLL_INTERVAL",
)


def _project_root() -> str:
    # this file lives in <root>/app/core/config.py -> walk up three levels
    core_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(core_dir)
    return os.path.dirname(app_dir)


def get_env_path() -> str:
    return os.path.join(_project_root(), ".env")


def get_yougile_env_path() -> str:
    return os.path.join(_project_root(), "yougile.env")


def _read_env_file(path: str) -> dict[str, str]:
    if not os.path.exists(path):
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value}


def _read_env_values() -> dict[str, str]:
    return _read_env_file(get_env_path())


def _read_yougile_env_values() -> dict[str, str]:
    return _read_env_file(get_yougile_env_path())


def _merged_env_values() -> dict[str, str]:
    values = _read_yougile_env_values()
    values.update(_read_env_values())
    return values


def _pick_env(*keys: str, values: dict[str, str] | None = None) -> str:
    merged = values if values is not None else _merged_env_values()
    for key in keys:
        env_value = os.environ.get(key, "").strip()
        if env_value:
            return env_value
    for key in keys:
        file_value = merged.get(key, "").strip()
        if file_value:
            return file_value
    return ""


def normalize_gitlab_url(url: str) -> str:
    """Return the GitLab API base URL (scheme + host), stripping project paths."""
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        return "http://localhost:8929"
    parsed = urlparse(cleaned)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return cleaned


def get_git_provider() -> str:
    return (_pick_env("GIT_PROVIDER") or "github").lower()


def get_git_remote() -> str:
    """Git remote name used by the poller when creating and pushing branches.

    ``GIT_REMOTE`` overrides the default mapping: ``origin`` for GitHub,
    ``gitlab`` for GitLab.
    """
    explicit = _pick_env("GIT_REMOTE")
    if explicit:
        return explicit
    return "gitlab" if get_git_provider() == "gitlab" else "origin"


def get_scm_token() -> str:
    """Personal access token for the active Git hosting provider."""
    if get_git_provider() == "gitlab":
        return _pick_env("GITLAB_TOKEN", "GITLAB_ACCESS_TOKEN", "CI_JOB_TOKEN")
    return _pick_env("GITHUB_TOKEN", "GH_TOKEN")


def load_yougile_settings() -> dict[str, str]:
    values = _read_yougile_env_values()
    values.update(_read_env_values())

    token = (
        os.environ.get("YOUGILE_TOKEN", "").strip()
        or os.environ.get("YOUGILE_BEARER_TOKEN", "").strip()
        or values.get("YOUGILE_BEARER_TOKEN", "").strip()
    )
    return {
        "token": token,
        "project_id": (
            os.environ.get("YOUGILE_PROJECT_ID", "").strip()
            or values.get("YOUGILE_PROJECT_ID", "").strip()
        ),
        "board_id": (
            os.environ.get("YOUGILE_BOARD_ID", "").strip()
            or values.get("YOUGILE_BOARD_ID", "").strip()
        ),
        "column_id": (
            os.environ.get("YOUGILE_COLUMN_ID", "").strip()
            or values.get("YOUGILE_COLUMN_ID", "").strip()
        ),
        "poll_interval": (
            os.environ.get("YOUGILE_POLL_INTERVAL", "").strip()
            or values.get("YOUGILE_POLL_INTERVAL", "10").strip()
            or "10"
        ),
    }


def load_webhook_settings() -> dict[str, str]:
    """Load settings needed by the two-way sync (webhook server and CI create_pr).

    Values are read from the environment first, then from ``.env`` /
    ``yougile.env`` as a fallback, so deployments can override via real env vars.
    The active Git hosting provider is selected via ``GIT_PROVIDER``
    (``github`` or ``gitlab``, default ``github``).
    """
    merged = _merged_env_values()
    yougile = load_yougile_settings()

    git_provider = get_git_provider()

    github_token = _pick_env("GITHUB_TOKEN", "GH_TOKEN", values=merged)
    github_repo = _pick_env("GITHUB_REPO", "GITHUB_REPOSITORY", values=merged)
    github_webhook_secret = _pick_env("GITHUB_WEBHOOK_SECRET", values=merged)

    gitlab_token = _pick_env("GITLAB_TOKEN", "GITLAB_ACCESS_TOKEN", "CI_JOB_TOKEN", values=merged)
    gitlab_url = normalize_gitlab_url(_pick_env("GITLAB_URL", "CI_SERVER_URL", values=merged))
    gitlab_project_id = _pick_env("GITLAB_PROJECT_ID", "CI_PROJECT_ID", values=merged)
    gitlab_webhook_token = _pick_env("GITLAB_WEBHOOK_TOKEN", values=merged)
    git_remote = get_git_remote()

    if git_provider == "gitlab":
        provider_configured = bool(gitlab_token and gitlab_project_id)
        webhook_secret = gitlab_webhook_token
    else:
        provider_configured = bool(github_token and github_repo)
        webhook_secret = github_webhook_secret

    return {
        "yougile_token": yougile["token"],
        "yougile_column_id": yougile["column_id"],
        "yougile_board_id": yougile["board_id"],
        "git_provider": git_provider,
        "git_remote": git_remote,
        "github_token": github_token,
        "github_repo": github_repo,
        "github_webhook_secret": github_webhook_secret,
        "gitlab_token": gitlab_token,
        "gitlab_url": gitlab_url,
        "gitlab_project_id": gitlab_project_id,
        "gitlab_webhook_token": gitlab_webhook_token,
        "webhook_secret": webhook_secret,
        "provider_configured": provider_configured,
        "yougile_webhook_secret": _pick_env("YOUGILE_WEBHOOK_SECRET", values=merged),
    }


def _write_env_values(values: dict[str, str]) -> None:
    env_path = get_env_path()
    merged = _read_env_values()
    merged.update(values)

    lines = [f"{key}={merged[key]}" for key in ENV_KEYS if key in merged and merged[key]]
    with open(env_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + ("\n" if lines else ""))

    print(f"Настройки сохранены в {env_path}")


def _write_yougile_env_values(values: dict[str, str]) -> None:
    yougile_path = get_yougile_env_path()
    merged = _read_yougile_env_values()
    merged.update(values)

    lines = [f"{key}={merged[key]}" for key in ENV_KEYS if key in merged and merged[key]]
    with open(yougile_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + ("\n" if lines else ""))

    print(f"Настройки сохранены в {yougile_path}")


def save_bearer_token(token: str) -> None:
    _write_env_values({"YOUGILE_BEARER_TOKEN": token})
    _write_yougile_env_values({"YOUGILE_BEARER_TOKEN": token})


def prompt_bearer_token() -> str:
    while True:
        token = input("Enter your Bearer Token: ").strip()
        if token:
            save_bearer_token(token)
            return token
        print("Bearer Token cannot be empty. Please try again.")


def load_bearer_token(api_factory) -> str:
    settings = load_yougile_settings()
    token = settings["token"]

    if token:
        api = api_factory(token)
        if api.validate_token():
            print("Токен из конфигурации проверен и работает.")
            return token

        print("Токен из .env не работает. Введите новый Bearer Token.")

    while True:
        token = prompt_bearer_token()
        api = api_factory(token)
        if api.validate_token():
            print("Новый токен проверен и работает.")
            return token
        print("Токен не работает. Попробуйте снова.")


def save_monitor_config(
    column_id: str,
    project_id: str = "",
    board_id: str = "",
    poll_interval: int = 10,
) -> None:
    values = {
        "YOUGILE_PROJECT_ID": project_id,
        "YOUGILE_BOARD_ID": board_id,
        "YOUGILE_COLUMN_ID": column_id,
        "YOUGILE_POLL_INTERVAL": str(poll_interval),
    }
    _write_env_values(values)
    _write_yougile_env_values(values)


def has_saved_monitor_config() -> bool:
    settings = load_yougile_settings()
    return bool(settings["column_id"])


def load_monitor_config() -> MonitorConfig:
    settings = load_yougile_settings()
    poll_interval = int(settings["poll_interval"] or "10")

    return MonitorConfig(
        column_id=settings["column_id"],
        project_id=settings["project_id"],
        board_id=settings["board_id"],
        poll_interval=poll_interval,
    )
