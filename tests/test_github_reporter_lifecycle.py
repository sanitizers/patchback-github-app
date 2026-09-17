"""Tests for the failure-safety guarantees of ``PullRequestReporter``.

``patchback.github_reporter`` and ``patchback.comments_api`` import nothing
but the stdlib, so these run against the real classes with hand-rolled
API doubles -- no third-party test dependencies needed.
"""

import pytest

from patchback.comments_api import CommentsAPI
from patchback.github_reporter import PullRequestReporter


class FakeAPI:
    """A gidgethub-ish client recording calls, optionally failing."""

    def __init__(self, *, fail_on_patch=False):
        self.calls = []
        self._fail_on_patch = fail_on_patch

    async def post(self, uri, **kwargs):
        self.calls.append(('post', uri))
        return {'url': f'{uri}/1', 'id': 1}

    async def patch(self, uri, **kwargs):
        self.calls.append(('patch', uri))
        if self._fail_on_patch:
            raise RuntimeError('Server disconnected')
        return {}

    async def put(self, uri, **kwargs):
        self.calls.append(('put', uri))
        return {}

    async def delete(self, uri, **kwargs):
        self.calls.append(('delete', uri))
        return {}


class FakeLockingAPI:
    """Records lock/unlock so the restoration can be asserted on."""

    def __init__(self, *, is_locked):
        # NOTE: Mirrors the real API: it only touches the lock when the PR
        # NOTE: was locked at webhook time.
        self._was_locked = is_locked
        self.is_locked = is_locked
        self.events = []

    async def lock_pr(self):
        self.events.append('lock')
        if self._was_locked:
            self.is_locked = True

    async def unlock_pr(self):
        self.events.append('unlock')
        if self._was_locked:
            self.is_locked = False


class FakeChecksAPI:
    check_run_name = 'Backport to stable'

    def __init__(self):
        self.updates = []

    async def create_check(self, commit_sha):
        raise PermissionError('Resource not accessible by integration')

    async def update_check(self, **extra_params):
        self.updates.append(extra_params)


def make_reporter(*, comments_api, locking_api):
    return PullRequestReporter(
        checks_api=FakeChecksAPI(),
        comments_api=comments_api,
        locking_api=locking_api,
        branch_name='stable',
    )


@pytest.mark.parametrize('was_locked', (True, False))
def test_lock_is_restored_when_the_comment_update_fails(was_locked):
    """A failing comment update must not leave the PR unlocked.

    ``start_reporting()`` unlocks a deliberately locked PR. If the terminal
    comment update then explodes, the lock must still be put back.
    """
    import asyncio

    locking_api = FakeLockingAPI(is_locked=was_locked)
    comments_api = CommentsAPI(
        api=FakeAPI(fail_on_patch=True), repo_slug='o/r', pr_number=1,
    )
    # Pretend the tracking comment exists so `update_comment()` runs.
    comments_api._comment_uri = '/repos/o/r/issues/comments/1'
    reporter = make_reporter(
        comments_api=comments_api, locking_api=locking_api,
    )

    with pytest.raises(RuntimeError, match='Server disconnected'):
        asyncio.run(reporter.finish_reporting(subtitle='boom'))

    assert 'lock' in locking_api.events
    assert locking_api.is_locked is was_locked


def test_lock_is_restored_on_the_happy_path():
    """The pre-existing locking behaviour is unchanged."""
    import asyncio

    locking_api = FakeLockingAPI(is_locked=True)
    api = FakeAPI()
    comments_api = CommentsAPI(api=api, repo_slug='o/r', pr_number=1)
    reporter = make_reporter(
        comments_api=comments_api, locking_api=locking_api,
    )

    asyncio.run(reporter.start_reporting('deadbeef', 1, 'cafe'))
    asyncio.run(reporter.finish_reporting(conclusion='success'))

    assert locking_api.events == ['unlock', 'lock']
    assert locking_api.is_locked is True


def test_update_comment_is_a_noop_without_a_tracking_comment():
    """Reporting must not explode when the tracking comment is missing.

    ``create_comment()`` may never have run, leaving ``_comment_uri`` unset.
    Patching ``None`` used to be sent to the API as a URI.
    """
    import asyncio

    api = FakeAPI()
    comments_api = CommentsAPI(api=api, repo_slug='o/r', pr_number=1)

    asyncio.run(comments_api.update_comment('anything'))

    assert api.calls == []


def test_finish_reporting_survives_a_missing_tracking_comment():
    """A terminal report works even if the start comment never landed."""
    import asyncio

    locking_api = FakeLockingAPI(is_locked=True)
    api = FakeAPI()
    comments_api = CommentsAPI(api=api, repo_slug='o/r', pr_number=1)
    reporter = make_reporter(
        comments_api=comments_api, locking_api=locking_api,
    )

    asyncio.run(reporter.finish_reporting(subtitle='💔 failed'))

    assert ('patch', None) not in api.calls
    assert locking_api.events == ['lock']
