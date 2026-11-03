class CommentsAPI:
    def __init__(self, *, api, repo_slug, pr_number):
        self._api = api
        self._comments_uri = (
            f'/repos/{repo_slug}/issues/{pr_number}/comments'
        )
        self._comment_uri = None

    async def create_comment(self, comment_text):
        comment_resp = await self._api.post(
            self._comments_uri,
            data={'body': comment_text},
        )
        self._comment_uri = comment_resp['url']

    async def update_comment(self, comment_text):
        # NOTE: The tracking comment may be missing when `create_comment()`
        # NOTE: never ran or failed. Reporting a terminal failure must not
        # NOTE: itself explode in that case, so this is a no-op.
        if self._comment_uri is None:
            return

        await self._api.patch(self._comment_uri, data={'body': comment_text})
