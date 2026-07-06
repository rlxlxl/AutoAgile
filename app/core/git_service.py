import os
import re
import subprocess
import unicodedata
from urllib.parse import quote, urlparse, urlunparse

from app.core.config import get_git_provider, get_git_remote, get_scm_token

_GIT_TIMEOUT_SEC = 120


class GitService:
    def __init__(self, base_branch: str = "dev", remote: str | None = None):
        self.base_branch = base_branch
        self.remote = remote or get_git_remote()
        self.provider = get_git_provider()

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

    @staticmethod
    def _git_env() -> dict[str, str]:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    @staticmethod
    def _inject_token(url: str, token: str, provider: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or "@" in parsed.netloc:
            return url
        username = "oauth2" if provider == "gitlab" else "x-access-token"
        host = parsed.hostname or ""
        netloc = f"{username}:{quote(token, safe='')}@{host}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))

    def _run_git(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        display_args = " ".join(args)
        if any("://" in arg and "@" in arg for arg in args):
            display_args = re.sub(r"://[^/@]+@", "://***@", display_args)
        print(f"  → git {display_args}")

        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            env=self._git_env(),
            timeout=_GIT_TIMEOUT_SEC,
        )
        if check and result.returncode != 0:
            error_message = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"git {' '.join(args[:3])}... failed: {error_message}")
        return result

    def _remote_url(self, *, authenticated: bool = True) -> str:
        result = self._run_git(["remote", "get-url", self.remote], check=True)
        url = result.stdout.strip()
        if not authenticated:
            return url
        token = get_scm_token()
        if not token:
            return url
        return self._inject_token(url, token, self.provider)

    def _is_git_repo(self) -> bool:
        result = self._run_git(["rev-parse", "--is-inside-work-tree"], check=False)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def _remote_configured(self) -> bool:
        result = self._run_git(["remote", "get-url", self.remote], check=False)
        return result.returncode == 0

    def _branch_exists(self, branch_name: str) -> bool:
        local = self._run_git(["show-ref", "--verify", f"refs/heads/{branch_name}"], check=False)
        if local.returncode == 0:
            return True

        remote = self._run_git(
            ["show-ref", "--verify", f"refs/remotes/{self.remote}/{branch_name}"],
            check=False,
        )
        return remote.returncode == 0

    def create_and_push_branch(self, branch_name: str) -> None:
        if not self._is_git_repo():
            raise RuntimeError("Текущая директория не является git-репозиторием.")

        if not self._remote_configured():
            raise RuntimeError(
                f"Git remote '{self.remote}' не настроен. "
                f"Добавьте remote для провайдера '{self.provider}' "
                f"(или задайте GIT_REMOTE в .env)."
            )

        if self._branch_exists(branch_name):
            print(f"Ветка уже существует: {branch_name}")
            return

        remote_url = self._remote_url()
        if not get_scm_token():
            print(
                f"  ⚠ Токен для {self.provider} не задан — git может зависнуть на запросе пароля. "
                f"Добавьте {'GITLAB_TOKEN' if self.provider == 'gitlab' else 'GITHUB_TOKEN'} в .env."
            )

        self._run_git(["fetch", remote_url])
        self._run_git(["checkout", self.base_branch])
        self._run_git(["pull", remote_url, self.base_branch])
        self._run_git(["checkout", "-b", branch_name])
        self._run_git(["push", "-u", remote_url, f"HEAD:{branch_name}"])
        self._run_git(["branch", "--set-upstream-to", f"{self.remote}/{branch_name}", branch_name], check=False)
        print(f"Создана и отправлена ветка: {branch_name} → remote '{self.remote}' ({self.provider})")
