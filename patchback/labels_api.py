"""Pull request label manipulation."""

from urllib.parse import quote


class LabelsAPI:
    def __init__(self, *, api, repo_slug, pr_number):
        self._api = api
        self._labels_uri = f'/repos/{repo_slug}/issues/{pr_number}/labels'

    async def add_label(self, label):
        await self._api.post(self._labels_uri, data={'labels': [label]})

    async def remove_label(self, label):
        # NOTE: Labels may contain slashes and spaces, neither of which can
        # NOTE: be dropped into the path as-is.
        await self._api.delete(f'{self._labels_uri}/{quote(label, safe="")}')
