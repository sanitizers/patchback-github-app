"""Tests for the Checks-API-vs-comment fallback in the PR reporter."""

import asyncio
import unittest

from patchback.github_reporter import PullRequestReporter


class FakeChecksAPI:
    """A Checks API double that records what it was asked to do."""

    check_run_name = 'Backport to stable-1'

    def __init__(self, create_error=None):
        self._create_error = create_error
        self.created_for = []
        self.updates = []

    async def create_check(self, commit_sha):
        if self._create_error is not None:
            raise self._create_error
        self.created_for.append(commit_sha)

    async def update_check(self, **kwargs):
        self.updates.append(kwargs)


class FakeCommentsAPI:
    def __init__(self):
        self.created = []
        self.updated = []

    async def create_comment(self, body):
        self.created.append(body)

    async def update_comment(self, body):
        self.updated.append(body)


class FakeLockingAPI:
    def __init__(self):
        self.calls = []

    async def lock_pr(self):
        self.calls.append('lock')

    async def unlock_pr(self):
        self.calls.append('unlock')


def make_reporter(create_error=None):
    checks_api = FakeChecksAPI(create_error=create_error)
    comments_api = FakeCommentsAPI()
    locking_api = FakeLockingAPI()
    reporter = PullRequestReporter(
        checks_api=checks_api,
        comments_api=comments_api,
        locking_api=locking_api,
        branch_name='stable-1',
    )
    return reporter, checks_api, comments_api, locking_api


def start(reporter):
    return asyncio.run(
        reporter.start_reporting(
            pr_head_sha='deadbeef',
            pr_number=42,
            pr_merge_commit='cafe1234',
        ),
    )


class TestStartReporting(unittest.TestCase):
    def test_unlocks_and_announces_the_target_branch(self):
        reporter, _checks, comments, locking = make_reporter()

        start(reporter)

        self.assertEqual(locking.calls, ['unlock'])
        self.assertEqual(len(comments.created), 1)
        self.assertIn('`stable-1`', comments.created[0])

    def test_enables_the_checks_api_when_the_check_run_is_created(self):
        reporter, checks, _comments, _locking = make_reporter()

        start(reporter)

        self.assertEqual(checks.created_for, ['deadbeef'])
        self.assertEqual(checks.updates, [{}])

    def test_survives_insufficient_privileges(self):
        reporter, checks, comments, _locking = make_reporter(
            create_error=PermissionError('Resource not accessible'),
        )

        start(reporter)

        self.assertEqual(checks.updates, [])
        self.assertEqual(len(comments.created), 1)


class TestProgressReporting(unittest.TestCase):
    """The PR comment is updated even when Checks API is unavailable."""

    def test_comment_is_updated_without_the_checks_api(self):
        reporter, checks, comments, _locking = make_reporter(
            create_error=PermissionError('nope'),
        )
        start(reporter)

        asyncio.run(
            reporter.update_progress(
                subtitle='cherry-picking',
                text='some details',
                summary='a summary',
            ),
        )

        self.assertEqual(checks.updates, [])
        self.assertEqual(len(comments.updated), 1)
        self.assertIn('a summary', comments.updated[0])
        self.assertIn('some details', comments.updated[0])

    def test_check_run_is_updated_when_available(self):
        reporter, checks, _comments, _locking = make_reporter()
        start(reporter)

        asyncio.run(
            reporter.update_progress(
                subtitle='cherry-picking',
                text='some details',
                summary='a summary',
            ),
        )

        self.assertEqual(
            checks.updates[-1],
            {
                'status': 'in_progress',
                'output': {
                    'title': 'Backport to stable-1: cherry-picking',
                    'text': 'some details',
                    'summary': 'a summary',
                },
            },
        )


class TestFinishReporting(unittest.TestCase):
    def test_pr_is_locked_even_without_the_checks_api(self):
        reporter, checks, comments, locking = make_reporter(
            create_error=PermissionError('nope'),
        )
        start(reporter)

        asyncio.run(reporter.finish_reporting(summary='done'))

        self.assertEqual(locking.calls, ['unlock', 'lock'])
        self.assertEqual(checks.updates, [])
        self.assertEqual(len(comments.updated), 1)

    def test_conclusion_is_forwarded_to_the_check_run(self):
        reporter, checks, _comments, locking = make_reporter()
        start(reporter)

        asyncio.run(
            reporter.finish_reporting(summary='done', conclusion='failure'),
        )

        self.assertEqual(locking.calls, ['unlock', 'lock'])
        self.assertEqual(checks.updates[-1]['status'], 'completed')
        self.assertEqual(checks.updates[-1]['conclusion'], 'failure')

    def test_missing_details_become_empty_strings(self):
        reporter, checks, _comments, _locking = make_reporter()
        start(reporter)

        asyncio.run(reporter.finish_reporting())

        self.assertEqual(
            checks.updates[-1]['output'],
            {'title': 'Backport to stable-1', 'text': '', 'summary': ''},
        )
