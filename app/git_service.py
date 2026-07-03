import re
import subprocess
import unicodedata


class GitService:
    def __init__(self, base_branch: str = "dev"):
        self.base_branch = base_branch

    @staticmethod
    def slugify(title: str, max_length: int = 40) -> str:
        normalized = unicodedata.normalize("NFKD", title)
        ascii_title = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_title.lower()).strip("-")

        if not slug:
            slug = "task"

        if len(slug) > max_length:
            slug = slug[:max_length].rstrip("-")

        return slug or "task"

    def branch_name(self, task_id: str, task_title: str) -> str:
        slug = self.slugify(task_title)
        short_id = task_id.split("-")[0]
        return f"feature/{short_id}-{slug}"

    def _run_git(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            error_message = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"git {' '.join(args)} failed: {error_message}")
        return result

    def _is_git_repo(self) -> bool:
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _branch_exists(self, branch_name: str) -> bool:
        local = self._run_git(["show-ref", "--verify", f"refs/heads/{branch_name}"], check=False)
        if local.returncode == 0:
            return True

        remote = self._run_git(
            ["show-ref", "--verify", f"refs/remotes/origin/{branch_name}"],
            check=False,
        )
        return remote.returncode == 0

    def create_and_push_branch(self, branch_name: str) -> None:
        if not self._is_git_repo():
            raise RuntimeError("Текущая директория не является git-репозиторием.")

        if self._branch_exists(branch_name):
            print(f"Ветка уже существует: {branch_name}")
            return

        self._run_git(["fetch", "origin"])
        self._run_git(["checkout", self.base_branch])
        self._run_git(["pull", "origin", self.base_branch])
        self._run_git(["checkout", "-b", branch_name])
        self._run_git(["push", "-u", "origin", branch_name])
        print(f"Создана и отправлена ветка: {branch_name}")
