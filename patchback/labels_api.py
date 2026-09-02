"""
Wrappers around repository and issue label APIs
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from gidgethub.abc import GitHubAPI

from patchback._utils import strip_nones


class RepoLabelsAPI:
    def __init__(self, *, api: GitHubAPI, repo_slug: str) -> None:
        self._api: GitHubAPI = api
        self._labels_api = f"/repos/{repo_slug}/labels"

    async def create_label(
        self, name: str, description: str | None = None, color: str | None = None
    ) -> dict[str, Any]:
        return await self._api.post(
            self._labels_api,
            data=strip_nones(
                {"name": name, "description": description, "color": color}
            ),
        )

    def list_labels(self) -> AsyncIterator[dict[str, Any]]:
        return self._api.getiter(self._labels_api)

    async def get_label(self, name: str) -> dict[str, Any]:
        return await self._api.getitem(f"{self._labels_api}/{name}")


class IssueLabelsAPI:
    def __init__(self, *, api: GitHubAPI, repo_slug: str, number: int) -> None:
        self._api: GitHubAPI = api
        self._issue_labels_api = f"/repos/{repo_slug}/issues/{number}/labels"

    async def add_labels(self, *labels: str) -> list[dict[str, Any]]:
        return await self._api.post(
            self._issue_labels_api,
            data={"labels": labels},
        )

    def list_labels(self) -> AsyncIterator[dict[str, Any]]:
        return self._api.getiter(self._issue_labels_api)

    async def remove_label(self, label: str) -> None:
        return await self._api.delete(f"{self._issue_labels_api}/{label}")
