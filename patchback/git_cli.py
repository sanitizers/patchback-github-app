"""Git CLI subprocess wrapper for backport operations."""

import logging
import pathlib
import secrets
import tempfile
from subprocess import CalledProcessError, check_call, check_output

import attr


logger = logging.getLogger(__name__)

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


@attr.dataclass
class BackportResult:
    """Result of a successful cherry-pick with objects uploaded to GitHub."""

    tree_sha: str = attr.ib()
    """Tree SHA from the local cherry-pick."""

    commit_message: str = attr.ib()
    """Commit message including the cherry-pick trailer."""


def _run(*cmd: str) -> None:
    """Run a git command with an empty environment for isolation."""
    check_call(cmd, env={})


def _run_output(*cmd: str) -> str:
    """Run a git command and return its stripped decoded output."""
    return check_output(cmd, env={}).decode().strip()



def cherry_pick_to_backport_branch(
        pr_number: int,
        merge_commit_sha: str,
        target_branch: str,
        backport_pr_branch: str,
        repo_slug: str,
        repo_remote: str,
        installation_access_token: str,
) -> BackportResult:
    """Clone a repo, cherry-pick a commit, and upload objects to GitHub.

    Returns a :class:`BackportResult` containing the tree SHA, commit
    message, and temporary ref name for signed commit creation via
    the Git Data API. The caller is responsible for deleting the
    temporary ref after the signed commit is created.

    :raises LookupError: if the repo or target branch cannot be found
    :raises ValueError: if the cherry-pick has conflicts
    :raises PermissionError: if the push to the temporary ref fails
    """
    token_mask = '*' * len(installation_access_token)
    sanitize_token = lambda text: text.replace(
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
        _run('git', 'init', tmp_dir)
        git_cmd = (
            'git',
            '--git-dir', str(pathlib.Path(tmp_dir) / '.git'),
            '--work-tree', tmp_dir,
            '-c', f'user.email={GIT_EMAIL}',
            '-c', f'user.name={GIT_USERNAME}',
            '-c', 'diff.algorithm=histogram',
        )
        _run(*git_cmd, 'remote', 'add', 'origin', repo_remote_w_creds)

        try:
            _run(*git_cmd, 'fetch', '--prune', 'origin')
        except CalledProcessError as proc_err:
            raise LookupError(
                f'Failed to fetch {repo_remote}',
            ) from proc_err
        logger.info('Fetched `%s`', repo_remote)

        try:
            _run(
                *git_cmd, 'checkout',
                '-b', backport_pr_branch, f'origin/{target_branch}',
            )
        except CalledProcessError as proc_err:
            raise LookupError(
                f'Failed to find branch {target_branch}',
            ) from proc_err
        logger.info('Checked out `%s`', backport_pr_branch)

        logger.info(
            'Cherry-picking `%s` into `%s`...',
            merge_commit_sha, backport_pr_branch,
        )
        is_merge_commit = int(_run_output(
            *git_cmd, 'rev-list',
            '--no-walk', '--count', '--merges',
            merge_commit_sha, '--',
        )) > 0
        logger.info(
            '`%s` is%s a merge commit',
            merge_commit_sha, ('' if is_merge_commit else ' not'),
        )

        try:
            _run(
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
        logger.info('Backported the commit into `%s`', backport_pr_branch)

        tree_sha = _run_output(*git_cmd, 'log', '--format=%T', '-1')
        commit_message = _run_output(*git_cmd, 'log', '--format=%B', '-1')

        temp_ref = f'{backport_pr_branch}/{secrets.token_hex(16)}'
        logger.info('Uploading git objects via temp ref `%s`...', temp_ref)
        try:
            _run(*git_cmd, 'push', 'origin', f'HEAD:{temp_ref}')
        except CalledProcessError as proc_err:
            logger.error(sanitize_token(str(proc_err)))
            cmd_log = CMD_RUN_OUT_TMPL.format(
                cmd=sanitize_token(' '.join(proc_err.cmd)),
                cmd_out=sanitize_token(proc_err.stdout or ''),
                cmd_err=sanitize_token(proc_err.stderr or ''),
                cmd_rc=proc_err.returncode,
            )
            raise PermissionError(
                f'Could not push temporary ref `{temp_ref}`. '
                'This may be caused by branch protection rulesets '
                'blocking pushes to this ref pattern, or by lacking '
                '`Contents: write` or `Workflows: write` permissions.'
                '\n\nthe underlying command output was:\n\n'
                f'```console\n{cmd_log}\n```',
            ) from proc_err

        try:
            _run(*git_cmd, 'push', '-d', 'origin', temp_ref)
        except CalledProcessError:
            logger.warning('Failed to delete temp ref `%s`', temp_ref)
        else:
            logger.info('Deleted temp ref `%s`', temp_ref)

        return BackportResult(
            tree_sha=tree_sha,
            commit_message=commit_message,
        )
