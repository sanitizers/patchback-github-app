"""Webhook event handlers."""

import http
import logging
import pathlib
import tempfile
from subprocess import CalledProcessError, check_output, check_call

from anyio import run_in_thread
from gidgethub import BadRequest, ValidationError

from octomachinery.app.routing import process_event_actions
from octomachinery.app.routing.decorators import process_webhook_payload
from octomachinery.app.runtime.context import RUNTIME_CONTEXT

from .checks_api import ChecksAPI
from .comments_api import CommentsAPI
from .locking_api import LockingAPI
from .config import get_patchback_config
from .github_reporter import PullRequestReporter


logger = logging.getLogger(__name__)

spawn_proc = lambda *cmd: check_call(cmd, env={})


# Refs:
# * https://github.community/t/github-actions-bot-email-address/17204/6
# * https://github.com/actions/checkout/issues/13#issuecomment-724415212
# * https://api.github.com/users/patchback%5Bbot%5D
# TODO: Figure out how to generate this automatically, on startup.
BOT_USER_GH_ID = 45432694
GIT_USERNAME = 'patchback[bot]'
GIT_EMAIL = f'{BOT_USER_GH_ID:d}+{GIT_USERNAME!s}@users.noreply.github.com'


CMD_RUN_OUT_TMPL = """
$ {cmd!s}

[RETURN CODE]: {cmd_rc:d}

[OUTPUT]:
{cmd_out!s}

[STDERR]:
{cmd_err!s}
"""


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


def backport_pr_sync(
        pr_number: int, merge_commit_sha: str, target_branch: str,
        backport_pr_branch: str,
        repo_slug: str, repo_remote: str, installation_access_token: str,
) -> None:
    """Returns a branch with backported PR pushed to GitHub.

    It clones the ``repo_remote`` using a GitHub App Installation token
    ``installation_access_token`` to authenticate. Then, it cherry-picks
    ``merge_commit_sha`` onto a new branch based on the
    ``target_branch`` and pushes it back to ``repo_remote``.
    """
    def sanitize_token_in_str(inp):
        nonlocal installation_access_token
        token_mask = '*' * len(installation_access_token)
        return inp.replace(
            installation_access_token, token_mask,
        )

    repo_remote_w_creds = repo_remote.replace(
        # NOTE: this is a hack for auth to work
        'https://github.com/',
        f'https://x-access-token:{installation_access_token}@github.com/',
        1,  # count
    )
    with tempfile.TemporaryDirectory(
            prefix=f'{repo_slug.replace("/", "--")}---'
            f'{target_branch.replace("/", "--")}---',
            suffix=f'---PR-{pr_number}.git',
    ) as tmp_dir:
        logger.info('Created a temporary dir: `%s`', tmp_dir)
        check_call(('git', 'init', tmp_dir), env={})
        git_cmd = (
            'git',
            '--git-dir', str(pathlib.Path(tmp_dir) / '.git'),
            '--work-tree', tmp_dir,
            '-c', f'user.email={GIT_EMAIL}',
            '-c', f'user.name={GIT_USERNAME}',
            '-c', 'diff.algorithm=histogram',
            # '-c', 'protocol.version=2',  # Needs Git 2.18+
        )
        spawn_proc(*git_cmd, 'remote', 'add', 'origin', repo_remote_w_creds)
        try:
            spawn_proc(*git_cmd, 'fetch', '--prune', 'origin')
        except CalledProcessError as proc_err:
            raise LookupError(f'Failed to fetch {repo_remote}') from proc_err
        else:
            logger.info('Fetched `%s`', repo_remote)

        try:
            check_call(
                (
                    *git_cmd, 'checkout',
                    '-b', backport_pr_branch, f'origin/{target_branch}',
                ),
            )
        except CalledProcessError as proc_err:
            raise LookupError(
                f'Failed to find branch {target_branch}',
            ) from proc_err
        else:
            logger.info('Checked out `%s`', backport_pr_branch)

        logger.info(
            'Cherry-picking `%s` into `%s`...',
            merge_commit_sha, backport_pr_branch,
        )
        merge_check_cmd = (
            *git_cmd, 'rev-list',
            '--no-walk', '--count', '--merges',
            merge_commit_sha, '--',
        )
        is_merge_commit = int(check_output(merge_check_cmd, env={})) > 0
        logger.info(
            '`%s` is%s a merge commit',
            merge_commit_sha, ('' if is_merge_commit else ' not'),
        )

        try:
            spawn_proc(
                *git_cmd, 'cherry-pick', '-x',
                '--strategy-option=diff-algorithm=histogram',
                '--strategy-option=find-renames',
                *(('--mainline', '1') if is_merge_commit else ()),
                merge_commit_sha,
            )
        except CalledProcessError as proc_err:
            raise ValueError(
                f'Failed to cleanly apply {merge_commit_sha} '
                f'on top of {backport_pr_branch}',
            ) from proc_err
        else:
            logger.info('Backported the commit into `%s`', backport_pr_branch)

        logger.info('Pushing `%s` back to GitHub...', backport_pr_branch)
        try:
            spawn_proc(
                *git_cmd, 'push',
                # We manage the branch and thus don't care about rewrites:
                '--force-with-lease',
                'origin', 'HEAD',
            )
        except CalledProcessError as proc_err:
            logger.error(sanitize_token_in_str(str(proc_err)))

            cmd_log = CMD_RUN_OUT_TMPL.format(
                cmd=sanitize_token_in_str(' '.join(proc_err.cmd)),
                cmd_out=sanitize_token_in_str(proc_err.stdout or ''),
                cmd_err=sanitize_token_in_str(proc_err.stderr or ''),
                cmd_rc=proc_err.returncode,
            )

            raise PermissionError(
                'Current GitHub App installation does not grant sufficient '
                f'privileges for pushing to {repo_remote}. Lacking '
                '`Contents: write` or `Workflows: write` permissions '
                'are known to cause this.\n\n'
                'the underlying command output was:\n\n'
                '```console\n'
                f'{cmd_log}\n'
                '```',
            ) from proc_err
        else:
            logger.info('Push to GitHub succeeded...')


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
        await run_in_thread(
            backport_pr_sync,
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
