"""Webhook event handlers."""

import http
import logging

from anyio import run_in_thread
from gidgethub import BadRequest, ValidationError

from octomachinery.app.routing import process_event_actions
from octomachinery.app.routing.decorators import process_webhook_payload
from octomachinery.app.runtime.context import RUNTIME_CONTEXT

from .checks_api import ChecksAPI
from .comments_api import CommentsAPI
from .config import get_patchback_config
from .git_api import GitAPI
from .git_cli import cherry_pick_to_backport_branch
from .github_reporter import PullRequestReporter
from .locking_api import LockingAPI


logger = logging.getLogger(__name__)


MANUAL_BACKPORT_GUIDE_MD_TMPL = """

### Backporting merged PR #{pr_number} into {pr_base_ref}

1. Ensure you have a local repo clone of your fork. Unless you cloned it
   from the upstream, this would be your `origin` remote.
2. Make sure you have an upstream repo added as a remote too. In these
   instructions you'll refer to it by the name `upstream`. If you don't
   have it, here's how you can add it:
   ```console
   $ git remote add upstream {git_url}
   ```
3. Ensure you have the latest copy of upstream and prepare a branch
   that will hold the backported code:
   ```console
   $ git fetch upstream
   $ git checkout -b {backport_pr_branch} upstream/{target_branch}
   ```
4. Now, cherry-pick PR #{pr_number} contents into that branch:
   ```console
   $ git cherry-pick -x {pr_merge_commit}
   ```
   If it'll yell at you with something like `fatal: Commit {pr_merge_commit} is
   a merge but no -m option was given.`, add `-m 1` as follows instead:
   ```console
   $ git cherry-pick -m1 -x {pr_merge_commit}
   ```
5. At this point, you'll probably encounter some merge conflicts. You must
   resolve them in to preserve the patch from PR #{pr_number} as close to the
   original as possible.
6. Push this branch to your fork on GitHub:
   ```console
   $ git push origin {backport_pr_branch}
   ```
7. Create a PR, ensure that the CI is green. If it's not — update it so that
   the tests and any other checks pass. This is it!
   Now relax and wait for the maintainers to process your pull request
   when they have some cycles to do reviews. Don't worry — they'll tell you if
   any improvements are necessary when the time comes!
"""


def ensure_pr_merged(event_handler):
    async def event_handler_wrapper(*, number, pull_request, **kwargs):
        if not pull_request['merged']:
            logger.info('PR#%s is not merged, ignoring...', number)
            return

        return await event_handler(
            number=number,
            pull_request=pull_request,
            **kwargs,
        )
    return event_handler_wrapper


@process_event_actions('pull_request', {'closed'})
@process_webhook_payload
@ensure_pr_merged
async def on_merge_of_labeled_pr(
        *,
        number,  # PR number
        pull_request,  # PR details subobject
        repository,  # repo details subobject
        **_kwargs,  # unimportant event details
) -> None:
    """React to labeled pull request merge."""
    repo_config = await get_patchback_config()
    backport_label_len = len(repo_config.backport_label_prefix)
    labels = [label['name'] for label in pull_request['labels']]
    target_branches = [
        f'{repo_config.target_branch_prefix}{label[backport_label_len:]}'
        for label in labels
        if label.startswith(repo_config.backport_label_prefix)
    ]

    if not target_branches:
        logger.info(
            'PR#%s does not have backport labels '
            'starting with "%s", ignoring...',
            number,
            repo_config.backport_label_prefix,
        )
        return

    merge_commit_sha = pull_request['merge_commit_sha']

    logger.info(
        'PR#%s is labeled with "%s". It needs to be backported to %s',
        number, labels, ', '.join(target_branches),
    )
    logger.info('PR#%s merge commit: %s', number, merge_commit_sha)

    for target_branch in target_branches:
        await process_pr_backport_labels(
            number,
            pull_request['title'],
            pull_request['body'],
            pull_request['locked'],
            pull_request['active_lock_reason'],
            pull_request['base']['ref'],
            pull_request['head']['sha'],
            merge_commit_sha,
            target_branch,
            repo_config.backport_branch_prefix,
            repository['pulls_url'],
            repository['full_name'],
            repository['clone_url'],
        )


@process_event_actions('pull_request', {'labeled'})
@process_webhook_payload
@ensure_pr_merged
async def on_label_added_to_merged_pr(
        *,
        label,  # label added
        number,  # PR number
        pull_request,  # PR details subobject
        repository,  # repo details subobject
        **_kwargs,  # unimportant event details
) -> None:
    """React to GitHub App pull request / issue label webhook event."""
    repo_config = await get_patchback_config()
    label_name = label['name']
    if not label_name.startswith(repo_config.backport_label_prefix):
        logger.info(
            'PR#%s got labeled with %s but it is not '
            'a backport label (it is not prefixed with "%s"), ignoring...',
            number, label_name, repo_config.backport_label_prefix,
        )
        return

    target_branch = (
        f'{repo_config.target_branch_prefix}'
        f'{label_name[len(repo_config.backport_label_prefix):]}'
    )
    merge_commit_sha = pull_request['merge_commit_sha']

    logger.info(
        'PR#%s got labeled with "%s". It needs to be backported to %s',
        number, label_name, target_branch,
    )
    logger.info('PR#%s merge commit: %s', number, merge_commit_sha)
    await process_pr_backport_labels(
        number,
        pull_request['title'],
        pull_request['body'],
        pull_request['locked'],
        pull_request['active_lock_reason'],
        pull_request['base']['ref'],
        pull_request['head']['sha'],
        merge_commit_sha,
        target_branch,
        repo_config.backport_branch_prefix,
        repository['pulls_url'],
        repository['full_name'],
        repository['clone_url'],
    )


async def process_pr_backport_labels(
        pr_number,
        pr_title,
        pr_body,
        pr_is_locked,
        pr_lock_reason,
        pr_base_ref,
        pr_head_sha,
        pr_merge_commit,
        target_branch,
        backport_branch_prefix,
        pr_api_url, repo_slug,
        git_url,
) -> None:
    gh_api = RUNTIME_CONTEXT.app_installation_client
    checks_api = ChecksAPI(
        api=gh_api, repo_slug=repo_slug, branch_name=target_branch,
    )
    comments_api = CommentsAPI(
        api=gh_api, repo_slug=repo_slug, pr_number=pr_number,
    )
    locking_api = LockingAPI(
        api=gh_api, repo_slug=repo_slug, pr_number=pr_number,
        is_locked=pr_is_locked, lock_reason=pr_lock_reason,
    )
    git_data_api = GitAPI(api=gh_api, repo_slug=repo_slug)
    pr_reporter = PullRequestReporter(
        checks_api=checks_api,
        comments_api=comments_api,
        locking_api=locking_api,
        branch_name=target_branch,
    )

    await pr_reporter.start_reporting(pr_head_sha, pr_number, pr_merge_commit)

    backport_pr_branch = (
        f'{backport_branch_prefix}{target_branch}/'
        f'{pr_merge_commit}/pr-{pr_number}'
    )
    manual_backport_guide = MANUAL_BACKPORT_GUIDE_MD_TMPL.format_map(locals())
    try:
        backport = await run_in_thread(
            cherry_pick_to_backport_branch,
            pr_number,
            pr_merge_commit,
            target_branch,
            backport_pr_branch,
            repo_slug,
            git_url,
            (await RUNTIME_CONTEXT.app_installation.get_token()).token,
        )
    except LookupError as lu_err:
        logger.info(
            'Failed to backport PR #%d (commit `%s`) to `%s` '
            'because the target branch does not exist',
            pr_number, pr_merge_commit, target_branch,
        )

        await pr_reporter.finish_reporting(
            subtitle='💔 cherry-picking failed — target branch does not exist',
            summary=f'❌ {lu_err!s}',
        )
        return
    except ValueError as val_err:
        logger.info(
            'Failed to backport PR #%d (commit `%s`) to `%s` because '
            'it conflicts with the target backport branch contents',
            pr_number, pr_merge_commit, target_branch,
        )

        await pr_reporter.finish_reporting(
            subtitle='💔 cherry-picking failed — conflicts found',
            text=manual_backport_guide,
            summary=f'❌ {val_err!s}',
        )
        return
    except PermissionError as perm_err:
        logger.info(
            'Failed to backport PR #%d (commit `%s`) to `%s` because '
            'of insufficient GitHub App Installation privileges to '
            'modify the repo contents',
            pr_number, pr_merge_commit, target_branch,
        )

        await pr_reporter.finish_reporting(
            subtitle='💔 cherry-picking failed — could not push',
            text=manual_backport_guide,
            summary=f'❌ {perm_err!s}',
        )
        return
    else:
        logger.info('Backport PR branch: `%s`', backport_pr_branch)

    try:
        parent_sha = await git_data_api.get_branch_head_sha(target_branch)
    except PermissionError as perm_err:
        logger.info(
            'Failed to read target branch `%s` for PR #%d backport',
            target_branch, pr_number,
        )
        await pr_reporter.finish_reporting(
            subtitle=(
                '💔 signed commit failed — could not read target branch'
            ),
            text=manual_backport_guide,
            summary=f'❌ {perm_err!s}',
        )
        return

    try:
        commit_sha = await git_data_api.create_commit(
            tree_sha=backport.tree_sha,
            message=backport.commit_message,
            parent_sha=parent_sha,
        )
    except PermissionError as perm_err:
        logger.info(
            'Failed to create signed commit for PR #%d backport to `%s`',
            pr_number, target_branch,
        )
        await pr_reporter.finish_reporting(
            subtitle='💔 signed commit failed — could not create commit',
            text=manual_backport_guide,
            summary=f'❌ {perm_err!s}',
        )
        return
    logger.info('Created signed commit `%s`', commit_sha)

    try:
        await git_data_api.create_branch(
            branch_name=backport_pr_branch, sha=commit_sha,
        )
    except PermissionError as perm_err:
        logger.info(
            'Failed to create branch `%s` for PR #%d backport',
            backport_pr_branch, pr_number,
        )
        await pr_reporter.finish_reporting(
            subtitle='💔 signed commit failed — could not create branch',
            text=manual_backport_guide,
            summary=f'❌ {perm_err!s}',
        )
        return
    logger.info('Created branch `%s`', backport_pr_branch)

    backport_pr_branch_msg = f'Backport PR branch: `{backport_pr_branch}`'
    await pr_reporter.update_progress(
        subtitle='cherry-pick succeeded',
        text='PR branch created, proceeding with making a PR.',
        summary=backport_pr_branch_msg,
    )

    logger.info('Creating a backport PR...')
    try:
        pr_resp = await gh_api.post(
            pr_api_url,
            data={
                'title': f'[PR #{pr_number}/{pr_merge_commit[:8]} backport]'
                f'[{target_branch}] {pr_title}',
                'head': backport_pr_branch,
                'base': target_branch,
                'body': f'**This is a backport of PR #{pr_number} as '
                f'merged into {pr_base_ref} '
                f'({pr_merge_commit}).**\n\n{pr_body}',
                'maintainer_can_modify': True,
                'draft': False,
            },
        )
    except ValidationError as val_err:
        logger.info(
            'Failed to backport PR #%d (commit `%s`) to `%s`: %s',
            pr_number, pr_merge_commit, target_branch, val_err,
        )

        await pr_reporter.finish_reporting(
            subtitle='💔 creation of the backport PR failed',
            text=manual_backport_guide,
            summary=f'❌ {backport_pr_branch_msg}\n\n{val_err!s}',
        )
        return
    except BadRequest as bad_req_err:
        if (
                bad_req_err.status_code != http.client.FORBIDDEN or
                str(bad_req_err) != 'Resource not accessible by integration'
        ):
            raise
        logger.info(
            'Failed to backport PR #%d (commit `%s`) to `%s` because '
            'of insufficient GitHub App Installation privileges to '
            'create pull requests',
            pr_number, pr_merge_commit, target_branch,
        )

        await pr_reporter.finish_reporting(
            subtitle='💔 creation of the backport PR failed',
            text=manual_backport_guide,
            summary=f'❌ {backport_pr_branch_msg}\n\n{bad_req_err!s}',
        )
        return
    else:
        logger.info('Created a PR @ %s', pr_resp['html_url'])

    await pr_reporter.finish_reporting(
        conclusion='success',
        subtitle='💚 backport PR created',
        text=f'Backported as {pr_resp["html_url"]}',
        summary=f'✅ {backport_pr_branch_msg!s}',
    )
