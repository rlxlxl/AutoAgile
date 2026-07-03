import sys

from app.api import YOUGileAPI
from app.models import MonitorConfig, YouGileItem


def _print_items(items: list[YouGileItem], label: str) -> None:
    print(f"\n{label}:")
    for index, item in enumerate(items, start=1):
        print(f"{index}. {item.title}: {item.id}")


def _prompt_choice(count: int, label: str) -> int:
    while True:
        raw_value = input(f"Выберите {label} (номер): ").strip()
        if not raw_value.isdigit():
            print("Введите число из списка.")
            continue

        choice = int(raw_value)
        if 1 <= choice <= count:
            return choice - 1

        print(f"Введите число от 1 до {count}.")


def _select_item(items: list[YouGileItem], label: str) -> YouGileItem:
    if not items:
        print(f"Список пуст: {label}.")
        sys.exit(1)

    _print_items(items, label)
    index = _prompt_choice(len(items), label.lower())
    return items[index]


def select_project(api: YOUGileAPI) -> YouGileItem:
    return _select_item(api.get_projects(), "Проекты")


def select_board(api: YOUGileAPI, project_id: str) -> YouGileItem:
    return _select_item(api.get_boards(project_id), "Доски")


def select_column(api: YOUGileAPI, board_id: str) -> YouGileItem:
    return _select_item(api.get_columns(board_id), "Колонки")


def run_setup(api: YOUGileAPI) -> MonitorConfig:
    project = select_project(api)
    board = select_board(api, project.id)
    column = select_column(api, board.id)

    print(
        f"\nВыбрано: проект '{project.title}', "
        f"доска '{board.title}', колонка '{column.title}'."
    )

    return MonitorConfig(
        column_id=column.id,
        project_id=project.id,
        board_id=board.id,
    )
