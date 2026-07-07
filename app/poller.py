import time

from app.api import YOUGileAPI
from app.git_service import GitService
from app.models import YouGileItem


class TaskPoller:
    def __init__(
        self,
        api: YOUGileAPI,
        column_id: str,
        git_service: GitService | None = None,
        interval: int = 10,
    ):
        self.api = api
        self.column_id = column_id
        self.git_service = git_service or GitService()
        self.interval = interval
        self.known_tasks: set[str] = set()
        self._tasks_by_id: dict[str, YouGileItem] = {}

    def initialize(self) -> None:
        tasks = self.api.get_tasks(self.column_id)
        self._register_tasks(tasks, notify=False)
        print(f"Инициализация завершена. Известных задач: {len(self.known_tasks)}")

    def _register_tasks(self, tasks: list[YouGileItem], notify: bool) -> None:
        for task in tasks:
            self._tasks_by_id[task.id] = task
            if task.id not in self.known_tasks:
                self.known_tasks.add(task.id)
                if notify:
                    self._handle_new_task(task)

    def _handle_new_task(self, task: YouGileItem) -> None:
        branch_name = self.git_service.branch_name(task.id, task.title)
        print(f"Новая задача: {task.title} ({task.id})")

        try:
            self.git_service.create_and_push_branch(branch_name)
        except Exception as error:
            print(f"Не удалось создать ветку для задачи {task.id}: {error}")
        else:
            sha = self.git_service.current_head_sha()

            try:
                task_data = self.api.get_task(task.id)
                current_desc = task_data.get("description", "") or ""
                append = f"Branch: {branch_name}"
                if sha:
                    append += f" | Commit: {sha}"
                if append not in current_desc:
                    new_desc = current_desc + ("\n" if current_desc else "") + append
                    try:
                        self.api.update_task(task.id, description=new_desc)
                        print(f"Updated YouGile task {task.id} with {append}")
                    except Exception as err:
                        print(f"Не удалось обновить задачу {task.id} в YouGile: {err}")
            except Exception as err:
                print(f"Не удалось получить данные задачи {task.id} из YouGile: {err}")

    def poll_once(self) -> None:
        tasks = self.api.get_tasks(self.column_id)
        current_ids = {task.id for task in tasks}

        for task in tasks:
            if task.id not in self.known_tasks:
                self._handle_new_task(task)

        self.known_tasks = current_ids
        for task in tasks:
            self._tasks_by_id[task.id] = task

    def run(self) -> None:
        try:
            while True:
                try:
                    self.poll_once()
                except Exception as error:
                    print(f"Ошибка при опросе задач: {error}")

                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\nМониторинг остановлен.")
