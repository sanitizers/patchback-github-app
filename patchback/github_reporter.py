import logging


_logger = logging.getLogger(__name__)


class PullRequestReporter:
    def __init__(self, checks_api):
        self._checks_api = checks_api
        self._use_checks_api = False

    async def start_reporting(self, pr_head_sha, pr_number, pr_merge_commit):
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
        if not self._use_checks_api:
            return

        await self._checks_api.update_check(
            status='in_progress',
            output=self._make_output_from_details(subtitle, text, summary),
        )

    async def finish_reporting(
            self,
            *,
            subtitle=None, text=None, summary=None,
            conclusion='neutral',
    ):
        if not self._use_checks_api:
            return

        await self._checks_api.update_check(
            status='completed',
            conclusion=conclusion,
            output=self._make_output_from_details(subtitle, text, summary),
        )

    def _make_output_from_details(self, subtitle, text, summary):
        title = self._checks_api.check_run_name
        if subtitle:
            title = f'{title}: {subtitle!s}'
        return {
            'title': title,
            'text': text or '',
            'summary': summary or '',
        }
