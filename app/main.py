import sys

from app.api import YOUGileAPI
from app import config, menu
from app.github_client import GitHubClient
from app.poller import TaskPoller


def main() -> None:
    token = config.load_bearer_token(YOUGileAPI)
    api = YOUGileAPI(token)

    if not config.has_saved_monitor_config() or "--reconfigure" in sys.argv:
        monitor_config = menu.run_setup(api)
        config.save_monitor_config(
            column_id=monitor_config.column_id,
            project_id=monitor_config.project_id,
            board_id=monitor_config.board_id,
            poll_interval=monitor_config.poll_interval,
        )
    else:
        monitor_config = config.load_monitor_config()

    webhook_settings = config.load_webhook_settings()
    github_client = None
    if webhook_settings["github_token"] and webhook_settings["github_repo"]:
        github_client = GitHubClient(
            webhook_settings["github_token"],
            webhook_settings["github_repo"],
        )
        print(f"GitHub Issues auto-creation enabled for {webhook_settings['github_repo']}.")
    else:
        print("GitHub token/repo не заданы — авто-создание Issues отключено.")

    poller = TaskPoller(
        api=api,
        column_id=monitor_config.column_id,
        interval=monitor_config.poll_interval,
        github_client=github_client,
    )
    poller.initialize()
    print(
        f"Мониторинг колонки {monitor_config.column_id} "
        f"каждые {monitor_config.poll_interval} сек. Ctrl+C для остановки."
    )
    poller.run()


if __name__ == "__main__":
    main()
