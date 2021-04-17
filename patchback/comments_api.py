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
        await self._api.patch(self._comment_uri, data={'body': comment_text})
