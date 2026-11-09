"""GitHub Git Data REST API wrapper for signed commit creation."""

import http.client
import logging

from gidgethub import BadRequest


logger = logging.getLogger(__name__)


def _handle_bad_request(bad_req_err: BadRequest) -> None:
    """Re-raise as ``PermissionError`` if the request was denied."""
    if (
            bad_req_err.status_code != http.client.FORBIDDEN or
            str(bad_req_err) != 'Resource not accessible by integration'
    ):
        raise

    raise PermissionError(str(bad_req_err)) from bad_req_err


class GitAPI:
    """Git Data API for creating signed commits and branch refs."""

    def __init__(self, *, api, repo_slug: str) -> None:
        """Initialize a GitAPI instance for a given repo."""
        self._api = api
        self._repo_slug = repo_slug

    async def get_branch_head_sha(self, branch_name: str) -> str:
        """Return the HEAD commit SHA of a branch."""
        try:
            ref = await self._api.getitem(
                f'/repos/{self._repo_slug}/git/ref/heads/{branch_name}',
            )
        except BadRequest as bad_req_err:
            _handle_bad_request(bad_req_err)
        return ref['object']['sha']

    async def create_commit(
            self, *, tree_sha: str, message: str, parent_sha: str,
    ) -> str:
        """Create a commit and return its SHA.

        Commits created through the Git Data API are automatically
        signed by GitHub's web-flow GPG key.
        """
        try:
            resp = await self._api.post(
                f'/repos/{self._repo_slug}/git/commits',
                data={
                    'message': message,
                    'tree': tree_sha,
                    'parents': [parent_sha],
                },
            )
        except BadRequest as bad_req_err:
            _handle_bad_request(bad_req_err)
        return resp['sha']

    async def create_branch(
            self, *, branch_name: str, sha: str,
    ) -> None:
        """Create a branch ref pointing to the given commit SHA."""
        try:
            await self._api.post(
                f'/repos/{self._repo_slug}/git/refs',
                data={
                    'ref': f'refs/heads/{branch_name}',
                    'sha': sha,
                },
            )
        except BadRequest as bad_req_err:
            _handle_bad_request(bad_req_err)

    async def create_signed_branch(
            self, *,
            tree_sha: str,
            message: str,
            parent_branch: str,
            branch_name: str,
    ) -> str:
        """Create a signed commit on a new branch.

        Fetches the parent branch HEAD, creates a signed commit from
        the given tree, and points a new branch at it. Returns the
        signed commit SHA.
        """
        parent_sha = await self.get_branch_head_sha(parent_branch)
        commit_sha = await self.create_commit(
            tree_sha=tree_sha,
            message=message,
            parent_sha=parent_sha,
        )
        logger.info('Created signed commit `%s`', commit_sha)
        await self.create_branch(branch_name=branch_name, sha=commit_sha)
        logger.info('Created branch `%s`', branch_name)
        return commit_sha
