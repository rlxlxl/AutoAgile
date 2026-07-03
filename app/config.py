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


def _read_env_values() -> dict[str, str]:
    env_path = get_env_path()
    if not os.path.exists(env_path):
        return {}
    return {key: value for key, value in dotenv_values(env_path).items() if value}


def _write_env_values(values: dict[str, str]) -> None:
    env_path = get_env_path()
    merged = _read_env_values()
    merged.update(values)

    lines = [f"{key}={merged[key]}" for key in ENV_KEYS if key in merged and merged[key]]
    with open(env_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + ("\n" if lines else ""))

    print(f"Настройки сохранены в {env_path}")


def save_bearer_token(token: str) -> None:
    _write_env_values({"YOUGILE_BEARER_TOKEN": token})


def prompt_bearer_token() -> str:
    while True:
        token = input("Enter your Bearer Token: ").strip()
        if token:
            save_bearer_token(token)
            return token
        print("Bearer Token cannot be empty. Please try again.")


def load_bearer_token(api_factory) -> str:
    env_values = _read_env_values()
    token = env_values.get("YOUGILE_BEARER_TOKEN", "").strip()

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
    _write_env_values(
        {
            "YOUGILE_PROJECT_ID": project_id,
            "YOUGILE_BOARD_ID": board_id,
            "YOUGILE_COLUMN_ID": column_id,
            "YOUGILE_POLL_INTERVAL": str(poll_interval),
        }
    )


def has_saved_monitor_config() -> bool:
    env_values = _read_env_values()
    return bool(env_values.get("YOUGILE_COLUMN_ID", "").strip())


def load_monitor_config() -> MonitorConfig:
    env_values = _read_env_values()
    poll_interval = int(env_values.get("YOUGILE_POLL_INTERVAL", "10") or "10")

    return MonitorConfig(
        column_id=env_values.get("YOUGILE_COLUMN_ID", "").strip(),
        project_id=env_values.get("YOUGILE_PROJECT_ID", "").strip(),
        board_id=env_values.get("YOUGILE_BOARD_ID", "").strip(),
        poll_interval=poll_interval,
    )
