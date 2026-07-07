import os
import re
import subprocess
import unicodedata


class GitService:
    def __init__(self, base_branch: str = "dev", repo_path: str | None = None):
        self.base_branch = base_branch
        self.repo_path = (
            os.path.abspath(os.path.expanduser(repo_path)) if repo_path else None
        )

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
            cwd=self.repo_path,
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

    def current_head_sha(self) -> str | None:
        result = self._run_git(["rev-parse", "--verify", "HEAD"], check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    def create_and_push_branch(self, branch_name: str) -> None:
        if not self._is_git_repo():
            location = self.repo_path or "текущая директория"
            raise RuntimeError(f"{location} не является git-репозиторием.")

        if self._branch_exists(branch_name):
            print(f"Ветка уже существует: {branch_name}")
            return

        self._run_git(["fetch", "origin"])
        self._run_git(["checkout", self.base_branch])
        self._run_git(["pull", "origin", self.base_branch])
        self._run_git(["checkout", "-b", branch_name])
        self._run_git(["push", "-u", "origin", branch_name])
        target = self.repo_path or os.getcwd()
        print(f"Создана и отправлена ветка: {branch_name} ({target})")
