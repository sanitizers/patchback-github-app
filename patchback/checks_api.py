import http
from datetime import datetime


class ChecksAPI:
    def __init__(self, *, api, repo_slug, branch_name):
        self._api = api
        self._check_run_name = f'Backport to {branch_name}'
        self._check_runs_base_uri = f'/repos/{repo_slug}/check-runs'
        self._check_runs_updates_uri = None
        self._preview_api_version = 'antiope'

    @property
    def check_run_name(self):
        return self._check_run_name

    async def create_check(self, commit_sha):
        try:
            checks_resp = await self._api.post(
                self._check_runs_base_uri,
                preview_api_version=self._preview_api_version,
                data={
                    'name': self._check_run_name,
                    # NOTE: We don't use "pr_merge_commit" because then the
                    # NOTE: check would only show up on the merge commit but
                    # NOTE: not in PR. PRs only show checks from PR branch
                    # NOTE: HEAD. This is a bit imprecise but
                    # NOTE: it is what it is.
                    'head_sha': commit_sha,
                    'status': 'queued',
                    'started_at': f'{datetime.utcnow().isoformat()}Z',
                },
            )
        except BadRequest as bad_req_err:
            err_msg = str(bad_req_err)
            if (
                    bad_req_err.status_code != http.client.FORBIDDEN or
                    err_msg != 'Resource not accessible by integration'
            ):
                raise

            raise PermissionError(err_msg) from bad_req_err
        else:
            self._check_runs_updates_uri = (
                f'{self._check_runs_base_uri}/{checks_resp["id"]:d}'
            )

    async def update_check(self, **extra_params):
        payload = {
            'name': self._check_run_name,
            'status': 'in_progress',
        }
        if extra_params.get('status') == 'completed':
            payload['completed_at'] = f'{datetime.utcnow().isoformat()}Z'
        await self._api.patch(
            self._check_runs_updates_uri,
            preview_api_version=self._preview_api_version,
            data=dict(payload, **extra_params),
        )
