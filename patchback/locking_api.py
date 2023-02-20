"""Module dedicated to managing PR/issue locking API."""


class LockingAPI:
    """PR/issue locking API."""

    def __init__(self, *, api, repo_slug, pr_number, is_locked, lock_reason):
        """Initialize a LockingAPI instance for given PR."""
        self._api = api
        self._was_locked = is_locked
        self._locking_extra_query_args = {} if not lock_reason else {
            'data': {'lock_reason': lock_reason},
        }
        self._lock_uri = f'/repos/{repo_slug}/issues/{pr_number}/lock'

    async def lock_pr(self):
        """Lock the PR."""
        if not self._was_locked:
            return

        await self._api.put(
            self._lock_uri,
            **self._locking_extra_query_args,
        )

    async def unlock_pr(self):
        """Unlock the PR."""
        if not self._was_locked:
            return

        await self._api.delete(self._lock_uri)
