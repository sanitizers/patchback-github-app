"""Git plumbing that produces the backport branches.

This module deliberately imports nothing but the standard library: the
GitHub App layers live in :mod:`patchback.event_handlers`. Keeping the
separation means the cherry-picking logic stays exercisable — and
testable — without a web framework in the picture.
"""

import logging
import pathlib
import tempfile
from subprocess import STDOUT, CalledProcessError, check_output


logger = logging.getLogger(__name__)


# Refs:
# * https://github.community/t/github-actions-bot-email-address/17204/6
# * https://github.com/actions/checkout/issues/13#issuecomment-724415212
# * https://api.github.com/users/patchback%5Bbot%5D
# TODO: Figure out how to generate this automatically, on startup.
BOT_USER_GH_ID = 45432694
GIT_USERNAME = 'patchback[bot]'
GIT_EMAIL = f'{BOT_USER_GH_ID:d}+{GIT_USERNAME!s}@users.noreply.github.com'


# GitHub truncates the Checks API output fields and the issue comment
# bodies at 65535 characters. Every captured command output is reported
# alongside some prose, so budget well below that limit.
MAX_REPORTED_OUTPUT_LEN = 20_000


CMD_RUN_OUT_TMPL = """
$ {cmd!s}

[RETURN CODE]: {cmd_rc:d}

[OUTPUT]:
{cmd_out!s}
"""


def sanitize_secret(text: str, secret: str) -> str:
    """Mask every occurrence of ``secret`` in ``text``."""
    if not secret:
        return text

    return text.replace(secret, '*' * len(secret))


def clip_output(text: str, limit: int = MAX_REPORTED_OUTPUT_LEN) -> str:
    """Shorten ``text`` to ``limit`` characters, flagging the omission."""
    if len(text) <= limit:
        return text

    return f'{text[:limit]!s}\n[... truncated ...]'


def run_proc(*cmd: str) -> str:
    """Run ``cmd``, returning its stdout with stderr merged in.

    The output is captured rather than inherited so that failures can be
    reported back to the humans — it lands in
    :attr:`subprocess.CalledProcessError.output` when the command exits
    non-zero. Git happily emits non-UTF-8 bytes (author names, file
    contents in conflict hunks), hence the lenient decoding.
    """
    return check_output(
        cmd, env={}, stderr=STDOUT, text=True, errors='replace',
    )


def format_cmd_log(cmd, returncode: int, output: str) -> str:
    """Render one command invocation and its outcome for reporting."""
    return CMD_RUN_OUT_TMPL.format(
        cmd=' '.join(cmd),
        cmd_rc=returncode,
        cmd_out=clip_output(output),
    )


def format_proc_err(proc_err: CalledProcessError, sanitize) -> str:
    """Render a failed command as a fenced console block."""
    cmd_log = sanitize(
        format_cmd_log(
            proc_err.cmd, proc_err.returncode, proc_err.output or '',
        ),
    )
    return f'```console\n{cmd_log!s}\n```'


def format_conflict_report(git_cmd, proc_err, sanitize) -> str:
    """Explain a failed cherry-pick, conflicting hunks included.

    Git names every conflicting path in its own output, so that block
    doubles as the file list. The hunks go into a collapsed section
    because they can be long and the surrounding report has to stay
    readable.
    """
    report = (
        'The `git cherry-pick` invocation reported:\n\n'
        f'{format_proc_err(proc_err, sanitize)!s}\n'
    )

    try:
        conflicts = run_proc(*git_cmd, 'diff', '--diff-filter=U')
    except CalledProcessError as diff_err:
        logger.warning(
            'Failed to collect the conflicting hunks: %s',
            sanitize(str(diff_err)),
        )
        return report

    if not conflicts.strip():
        return report

    return (
        f'{report!s}\n'
        '<details>\n<summary>Conflicting hunks</summary>\n\n'
        '```diff\n'
        f'{clip_output(sanitize(conflicts))!s}\n'
        '```\n\n'
        '</details>\n'
    )


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
    def sanitize(inp):
        return sanitize_secret(inp, installation_access_token)

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
        run_proc('git', 'init', tmp_dir)
        git_cmd = (
            'git',
            '--git-dir', str(pathlib.Path(tmp_dir) / '.git'),
            '--work-tree', tmp_dir,
            '-c', f'user.email={GIT_EMAIL}',
            '-c', f'user.name={GIT_USERNAME}',
            '-c', 'diff.algorithm=histogram',
            # '-c', 'protocol.version=2',  # Needs Git 2.18+
        )
        run_proc(*git_cmd, 'remote', 'add', 'origin', repo_remote_w_creds)
        try:
            run_proc(*git_cmd, 'fetch', '--prune', 'origin')
        except CalledProcessError as proc_err:
            raise LookupError(
                f'Failed to fetch {repo_remote}\n\n'
                f'{format_proc_err(proc_err, sanitize)!s}',
            ) from proc_err
        else:
            logger.info('Fetched `%s`', repo_remote)

        try:
            run_proc(
                *git_cmd, 'checkout',
                '-b', backport_pr_branch, f'origin/{target_branch}',
            )
        except CalledProcessError as proc_err:
            raise LookupError(
                f'Failed to find branch {target_branch}\n\n'
                f'{format_proc_err(proc_err, sanitize)!s}',
            ) from proc_err
        else:
            logger.info('Checked out `%s`', backport_pr_branch)

        logger.info(
            'Cherry-picking `%s` into `%s`...',
            merge_commit_sha, backport_pr_branch,
        )
        is_merge_commit = int(
            run_proc(
                *git_cmd, 'rev-list',
                '--no-walk', '--count', '--merges',
                merge_commit_sha, '--',
            ),
        ) > 0
        logger.info(
            '`%s` is%s a merge commit',
            merge_commit_sha, ('' if is_merge_commit else ' not'),
        )

        try:
            run_proc(
                *git_cmd, 'cherry-pick', '-x',
                '--strategy-option=diff-algorithm=histogram',
                '--strategy-option=find-renames',
                *(('--mainline', '1') if is_merge_commit else ()),
                merge_commit_sha,
            )
        except CalledProcessError as proc_err:
            raise ValueError(
                f'Failed to cleanly apply {merge_commit_sha} '
                f'on top of {backport_pr_branch}\n\n'
                f'{format_conflict_report(git_cmd, proc_err, sanitize)!s}',
            ) from proc_err
        else:
            logger.info('Backported the commit into `%s`', backport_pr_branch)

        logger.info('Pushing `%s` back to GitHub...', backport_pr_branch)
        try:
            run_proc(
                *git_cmd, 'push',
                # We manage the branch and thus don't care about rewrites:
                '--force-with-lease',
                'origin', 'HEAD',
            )
        except CalledProcessError as proc_err:
            cmd_log = format_proc_err(proc_err, sanitize)
            logger.error('Failed to push the backport branch: %s', cmd_log)

            raise PermissionError(
                'Current GitHub App installation does not grant sufficient '
                f'privileges for pushing to {repo_remote}. Lacking '
                '`Contents: write` or `Workflows: write` permissions '
                'are known to cause this.\n\n'
                'the underlying command output was:\n\n'
                f'{cmd_log!s}',
            ) from proc_err
        else:
            logger.info('Push to GitHub succeeded...')
