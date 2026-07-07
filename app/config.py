import os

from dotenv import dotenv_values, load_dotenv

from app.models import MonitorConfig

load_dotenv()

ENV_KEYS = (
    "YOUGILE_BEARER_TOKEN",
    "YOUGILE_PROJECT_ID",
    "YOUGILE_BOARD_ID",
    "YOUGILE_COLUMN_ID",
    "YOUGILE_POLL_INTERVAL",
)


def get_env_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    return os.path.join(root_dir, ".env")


def get_yougile_env_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    return os.path.join(root_dir, "yougile.env")


def _read_env_file(path: str) -> dict[str, str]:
    if not os.path.exists(path):
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value}


def _read_env_values() -> dict[str, str]:
    return _read_env_file(get_env_path())


def _read_yougile_env_values() -> dict[str, str]:
    return _read_env_file(get_yougile_env_path())


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
    """Load settings needed by the two-way webhook sync server.

    Values are read from the environment first, then from ``.env`` /
    ``yougile.env`` as a fallback, so deployments can override via real env vars.
    """
    values = _read_yougile_env_values()
    values.update(_read_env_values())

    def pick(*keys: str) -> str:
        for key in keys:
            env_value = os.environ.get(key, "").strip()
            if env_value:
                return env_value
        for key in keys:
            file_value = values.get(key, "").strip()
            if file_value:
                return file_value
        return ""

    yougile = load_yougile_settings()
    return {
        "yougile_token": yougile["token"],
        "yougile_column_id": yougile["column_id"],
        "yougile_board_id": yougile["board_id"],
        "github_token": pick("GITHUB_TOKEN", "GH_TOKEN"),
        "github_repo": pick("GITHUB_REPO", "GITHUB_REPOSITORY"),
        "github_webhook_secret": pick("GITHUB_WEBHOOK_SECRET"),
        "gitlab_token": pick("GITLAB_TOKEN"),
        "gitlab_project_id": pick("GITLAB_PROJECT_ID", "CI_PROJECT_ID"),
        "gitlab_webhook_secret": pick("GITLAB_WEBHOOK_SECRET"),
        "yougile_webhook_secret": pick("YOUGILE_WEBHOOK_SECRET"),
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
            print("Токен из .env проверен и работает.")
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


def load_git_settings() -> dict[str, str]:
    """Load git settings for the poller (branch creation target repo)."""
    values = _read_yougile_env_values()
    values.update(_read_env_values())

    def pick(*keys: str) -> str:
        for key in keys:
            env_value = os.environ.get(key, "").strip()
            if env_value:
                return env_value
        for key in keys:
            file_value = values.get(key, "").strip()
            if file_value:
                return file_value
        return ""

    repo_path = pick("TARGET_REPO_PATH")
    if repo_path:
        repo_path = os.path.abspath(os.path.expanduser(repo_path))

    return {
        "repo_path": repo_path,
        "base_branch": pick("GIT_BASE_BRANCH") or "dev",
    }


def load_monitor_config() -> MonitorConfig:
    settings = load_yougile_settings()
    poll_interval = int(settings["poll_interval"] or "10")

    return MonitorConfig(
        column_id=settings["column_id"],
        project_id=settings["project_id"],
        board_id=settings["board_id"],
        poll_interval=poll_interval,
    )
