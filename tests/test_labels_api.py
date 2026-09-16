"""Tests for the pull request label API wrapper."""

import asyncio

import pytest

from patchback.labels_api import LabelsAPI


class FakeGitHubAPI:
    def __init__(self):
        self.calls = []

    async def post(self, url, *, data):
        self.calls.append(('POST', url, data))

    async def delete(self, url):
        self.calls.append(('DELETE', url, None))


@pytest.fixture
def api():
    return FakeGitHubAPI()


@pytest.fixture
def labels_api(api):
    return LabelsAPI(api=api, repo_slug='sanitizers/patchback', pr_number=42)


def test_add_label(api, labels_api):
    asyncio.run(labels_api.add_label('backported-3.8'))
    assert api.calls == [
        (
            'POST',
            '/repos/sanitizers/patchback/issues/42/labels',
            {'labels': ['backported-3.8']},
        ),
    ]


def test_remove_label(api, labels_api):
    asyncio.run(labels_api.remove_label('backport-3.8'))
    assert api.calls == [
        (
            'DELETE',
            '/repos/sanitizers/patchback/issues/42/labels/backport-3.8',
            None,
        ),
    ]


@pytest.mark.parametrize(
    ('label', 'expected_path_segment'),
    (
        ('backport-stable/2.0', 'backport-stable%2F2.0'),
        ('needs backport', 'needs%20backport'),
        ('🏷 backport', '%F0%9F%8F%B7%20backport'),
    ),
)
def test_remove_label_escapes_the_path_segment(
        api, labels_api, label, expected_path_segment,
):
    """Slashes in a label name must not become extra path segments."""
    asyncio.run(labels_api.remove_label(label))
    _method, url, _data = api.calls[0]
    assert url == (
        f'/repos/sanitizers/patchback/issues/42/labels/{expected_path_segment}'
    )
