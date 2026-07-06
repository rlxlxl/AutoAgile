"""Git hosting provider abstraction.

The rest of the app talks to GitHub or GitLab only through :class:`GitProvider`.
A concrete provider is chosen at runtime by :func:`get_provider` based on the
``git_provider`` setting (``github`` or ``gitlab``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping


@dataclass
class PullRequest:
    """Provider-neutral view of a GitHub Pull Request / GitLab Merge Request."""

    number: str  # PR number (GitHub) / MR iid (GitLab)
    branch: str  # source branch
    body: str  # PR body (GitHub) / MR description (GitLab)


@dataclass
class WebhookEvent:
    """Normalized incoming PR/MR webhook event."""

    number: str
    branch: str
    body: str
    action: str  # normalized: "opened" | "updated" | "ignored"


class GitProvider(ABC):
    name: str

    @abstractmethod
    def find_pr_by_branch(self, branch: str) -> PullRequest | None:
        """Return the open PR/MR whose source branch equals ``branch``."""

    @abstractmethod
    def find_pr_by_branch_prefix(self, prefix: str) -> PullRequest | None:
        """Return the first open PR/MR whose source branch starts with ``prefix``."""

    @abstractmethod
    def create_pr(self, *, title: str, source: str, target: str, body: str) -> PullRequest:
        """Create a PR/MR from ``source`` into ``target``."""

    @abstractmethod
    def update_pr(self, number: str, *, title: str | None = None, body: str | None = None) -> PullRequest:
        """Update the title and/or body of an existing PR/MR."""

    @abstractmethod
    def verify_webhook(self, secret: str, raw_body: bytes, headers: Mapping[str, str]) -> bool:
        """Verify an incoming webhook. Returns True when no secret is configured."""

    @abstractmethod
    def parse_webhook(self, payload: dict) -> WebhookEvent | None:
        """Parse a provider webhook payload into a normalized event.

        Returns None when the payload is not a PR/MR event.
        """


def get_provider(settings: Mapping[str, str]) -> GitProvider:
    provider = (settings.get("git_provider") or "github").strip().lower()

    if provider == "gitlab":
        from app.providers.gitlab.client import GitLabProvider

        return GitLabProvider(
            token=settings.get("gitlab_token", ""),
            project_id=settings.get("gitlab_project_id", ""),
            base_url=settings.get("gitlab_url", "") or "http://localhost:8929",
        )

    from app.providers.github.client import GitHubProvider

    return GitHubProvider(
        token=settings.get("github_token", ""),
        repo=settings.get("github_repo", ""),
    )
