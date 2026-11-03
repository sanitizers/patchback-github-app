"""Tests for how the reporter surfaces repo config warnings."""

import asyncio
import unittest

from patchback.github_reporter import PullRequestReporter


class FakeChecksAPI:
    check_run_name = 'Backport to stable-1'

    def __init__(self):
        self.updates = []

    async def create_check(self, _pr_head_sha):
        return None

    async def update_check(self, **kwargs):
        self.updates.append(kwargs)


class FakeCommentsAPI:
    def __init__(self):
        self.comments = []

    async def create_comment(self, body):
        self.comments.append(body)

    async def update_comment(self, body):
        self.comments.append(body)


class FakeLockingAPI:
    async def lock_pr(self):
        return None

    async def unlock_pr(self):
        return None


def make_reporter(config_warnings=()):
    checks_api = FakeChecksAPI()
    comments_api = FakeCommentsAPI()
    reporter = PullRequestReporter(
        checks_api=checks_api,
        comments_api=comments_api,
        locking_api=FakeLockingAPI(),
        branch_name='stable-1',
        config_warnings=config_warnings,
    )
    return reporter, checks_api, comments_api


def run_backport_report(reporter, **finish_kwargs):
    async def scenario():
        await reporter.start_reporting('deadbeef', 42, 'cafebabe')
        await reporter.finish_reporting(**finish_kwargs)

    asyncio.run(scenario())


class ConfigWarningReportingTestCase(unittest.TestCase):
    def test_summary_is_untouched_without_warnings(self):
        reporter, checks_api, _comments = make_reporter()

        run_backport_report(reporter, summary='✅ all good')

        self.assertEqual(
            checks_api.updates[-1]['output']['summary'], '✅ all good',
        )

    def test_warnings_are_appended_to_the_summary(self):
        reporter, checks_api, _comments = make_reporter(
            ('Ignoring unknown option `nope`.',),
        )

        run_backport_report(reporter, summary='✅ all good')

        self.assertEqual(
            checks_api.updates[-1]['output']['summary'],
            '✅ all good\n\n⚠️ Ignoring unknown option `nope`.',
        )

    def test_warnings_show_up_without_a_summary_to_hang_off(self):
        reporter, checks_api, _comments = make_reporter(('bad option',))

        run_backport_report(reporter)

        self.assertEqual(
            checks_api.updates[-1]['output']['summary'], '⚠️ bad option',
        )

    def test_every_warning_is_listed(self):
        reporter, checks_api, _comments = make_reporter(('first', 'second'))

        run_backport_report(reporter, summary='x')

        self.assertEqual(
            checks_api.updates[-1]['output']['summary'],
            'x\n\n⚠️ first\n⚠️ second',
        )

    def test_warnings_reach_the_pr_comment_too(self):
        reporter, _checks, comments_api = make_reporter(('bad option',))

        run_backport_report(reporter, summary='💔 failed')

        self.assertIn('⚠️ bad option', comments_api.comments[-1])

    def test_warnings_are_reported_on_a_failing_run(self):
        # The cherry-pick failure paths end the run early, so the warnings
        # must ride along on the failure report rather than a success one.
        reporter, checks_api, _comments = make_reporter(('bad option',))

        run_backport_report(
            reporter,
            subtitle='💔 cherry-picking failed',
            summary='❌ nope',
            conclusion='failure',
        )

        last_update = checks_api.updates[-1]
        self.assertEqual(last_update['conclusion'], 'failure')
        self.assertIn('⚠️ bad option', last_update['output']['summary'])

    def test_warnings_are_reported_on_interim_progress(self):
        reporter, checks_api, _comments = make_reporter(('bad option',))

        async def scenario():
            await reporter.start_reporting('deadbeef', 42, 'cafebabe')
            await reporter.update_progress(
                subtitle='cherry-pick succeeded', text='', summary='ok',
            )

        asyncio.run(scenario())

        self.assertIn(
            '⚠️ bad option', checks_api.updates[-1]['output']['summary'],
        )

    def test_reporting_still_works_when_checks_api_is_unavailable(self):
        reporter, checks_api, comments_api = make_reporter(('bad option',))

        async def deny(_pr_head_sha):
            raise PermissionError('no checks for you')

        checks_api.create_check = deny

        run_backport_report(reporter, summary='💔 failed')

        self.assertEqual(checks_api.updates, [])
        self.assertIn('⚠️ bad option', comments_api.comments[-1])


if __name__ == '__main__':
    unittest.main()
