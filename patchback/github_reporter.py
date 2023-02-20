import logging


_logger = logging.getLogger(__name__)


COMMENT_SIGNATURE = """
<sub><sup>
--
🤖 @patchback
I'm built with [octomachinery](https://octomachinery.dev) and
my source is open — https://github.com/sanitizers/patchback-github-app.
</sup></sub>
"""


PROCESS_START_COMMENT = f"""
Beep beep boop!
🤖 Hi, I'm @patchback — your friendly neighborhood robot!

Somebody's just asked me to create a backport of this pull request
into the `{{branch_name}}` branch. So in this comment I report that
I'm on it!

*Please, expect to see further updates regarding my progress in updates
to this comment. Stay tuned!*

If you think I'm experiencing problems, ping `@webknjaz` — my creator.


{COMMENT_SIGNATURE}
"""


PROGRESS_COMMENT = f"""
### {{title!s}}

{{summary}}

{{text}}


{COMMENT_SIGNATURE}
"""


class PullRequestReporter:
    def __init__(self, *, checks_api, comments_api, locking_api, branch_name):
        self._branch_name = branch_name
        self._checks_api = checks_api
        self._comments_api = comments_api
        self._locking_api = locking_api
        self._use_checks_api = False

    async def start_reporting(self, pr_head_sha, pr_number, pr_merge_commit):
        await self._locking_api.unlock_pr()
        await self._comments_api.create_comment(
            PROCESS_START_COMMENT.format(branch_name=self._branch_name),
        )

        try:
            await self._checks_api.create_check(pr_head_sha)
        except PermissionError as perm_err:
            _logger.info(
                'Failed to report PR #%d (commit `%s`) backport status '
                'updates via Checks API because '
                'of insufficient GitHub App Installation privileges to '
                'create pull requests: %s',
                pr_number, pr_merge_commit, perm_err,
            )
        else:
            self._use_checks_api = True
            _logger.info('Checks API is available')

            await self._checks_api.update_check()

    async def update_progress(
            self,
            *,
            subtitle, text, summary,
    ):
        checks_output = await self._make_comment_from_details(
            subtitle, text, summary,
        )

        if not self._use_checks_api:
            return

        await self._checks_api.update_check(
            status='in_progress',
            output=checks_output,
        )

    async def finish_reporting(
            self,
            *,
            subtitle=None, text=None, summary=None,
            conclusion='neutral',
    ):
        checks_output = await self._make_comment_from_details(
            subtitle, text, summary,
        )
        await self._locking_api.lock_pr()

        if not self._use_checks_api:
            return

        await self._checks_api.update_check(
            status='completed',
            conclusion=conclusion,
            output=checks_output,
        )

    async def _make_comment_from_details(self, subtitle, text, summary):
        title = self._checks_api.check_run_name
        if subtitle:
            title = f'{title}: {subtitle!s}'

        checks_output = {
            'title': title,
            'text': text or '',
            'summary': summary or '',
        }

        await self._comments_api.update_comment(
            PROGRESS_COMMENT.format_map(checks_output),
        )

        return checks_output
