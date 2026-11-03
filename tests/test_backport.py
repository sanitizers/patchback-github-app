"""Tests for the git plumbing behind the backport branches."""

import os
import pathlib
import subprocess

import pytest

from patchback.backport import (
    backport_pr_sync,
    clip_output,
    explain_push_rejection,
    run_proc,
    sanitize_secret,
)


TOKEN = 'v1.s3cr3t-inst4ll4t10n-t0k3n'


@pytest.fixture
def git_env(tmp_path):
    """Return an environment that ignores the ambient git configuration."""
    return {
        'HOME': str(tmp_path),
        'PATH': os.environ['PATH'],
        'GIT_CONFIG_NOSYSTEM': '1',
        'GIT_CONFIG_GLOBAL': os.devnull,
    }


@pytest.fixture
def git(git_env):
    """Return a callable running git in ``cwd`` with a fixed identity."""
    def run_git(*args, cwd):
        return subprocess.run(
            (
                'git',
                '-c', 'user.name=Test',
                '-c', 'user.email=test@example.com',
                '-c', 'init.defaultBranch=main',
                *args,
            ),
            cwd=str(cwd), env=git_env, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
    return run_git


@pytest.fixture
def upstream_repo(tmp_path, git):
    """Return a bare repo with branches set up for backporting.

    ``main`` carries a change on top of ``base``. ``stable-clean`` sits at
    ``base`` so the change applies, while ``stable-conflict`` touches the
    same line and makes it collide.
    """
    work_dir = tmp_path / 'work'
    work_dir.mkdir()
    tracked_file = work_dir / 'file.txt'

    git('init', str(work_dir), cwd=tmp_path)
    tracked_file.write_text('base\n')
    git('add', 'file.txt', cwd=work_dir)
    git('commit', '-m', 'Base commit', cwd=work_dir)

    git('branch', 'stable-clean', cwd=work_dir)
    git('checkout', '-b', 'stable-conflict', cwd=work_dir)
    tracked_file.write_text('stable divergence\n')
    git('commit', '-am', 'Diverge the stable branch', cwd=work_dir)

    git('checkout', 'main', cwd=work_dir)
    tracked_file.write_text('patched\n')
    git('commit', '-am', 'Patch the file', cwd=work_dir)
    plain_sha = git('rev-parse', 'HEAD', cwd=work_dir)

    # A squash-free merge, mirroring how GitHub records a merged PR:
    git('checkout', '-b', 'feature', 'main', cwd=work_dir)
    (work_dir / 'extra.txt').write_text('from the feature branch\n')
    git('add', 'extra.txt', cwd=work_dir)
    git('commit', '-m', 'Add an extra file', cwd=work_dir)
    git('checkout', 'main', cwd=work_dir)
    git('merge', '--no-ff', '-m', 'Merge the feature branch', 'feature',
        cwd=work_dir)
    merge_sha = git('rev-parse', 'HEAD', cwd=work_dir)

    bare_dir = tmp_path / 'origin.git'
    git('init', '--bare', str(bare_dir), cwd=tmp_path)
    git('push', str(bare_dir), '--all', cwd=work_dir)

    return {
        'remote': str(bare_dir),
        'plain_sha': plain_sha,
        'merge_sha': merge_sha,
    }


def backport(upstream_repo, sha_key, target_branch, branch='backport'):
    """Drive :func:`backport_pr_sync` against the fixture repo."""
    backport_pr_sync(
        1, upstream_repo[sha_key], target_branch, branch,
        'test-org/test-repo', upstream_repo['remote'], TOKEN,
    )


def remote_branches(remote, git):
    return git('branch', '--format=%(refname:short)', cwd=remote).split()


@pytest.mark.parametrize('sha_key', ('plain_sha', 'merge_sha'))
def test_backport_pushes_the_branch(upstream_repo, git, sha_key):
    """Check that a clean cherry-pick lands on the remote."""
    backport(upstream_repo, sha_key, 'stable-clean')

    assert 'backport' in remote_branches(upstream_repo['remote'], git)


def test_backport_of_a_merge_commit_takes_the_whole_pr(upstream_repo, git):
    """Check that mainline 1 brings in every commit of the merged PR."""
    backport(upstream_repo, 'merge_sha', 'stable-clean')

    tree = git(
        'ls-tree', '--name-only', 'backport',
        cwd=upstream_repo['remote'],
    )

    assert 'extra.txt' in tree.split()


def test_conflict_is_reported_with_the_hunks(upstream_repo):
    """Check that a conflict surfaces git's output and the diff."""
    with pytest.raises(ValueError) as exc_info:
        backport(upstream_repo, 'plain_sha', 'stable-conflict')

    report = str(exc_info.value)

    assert 'Failed to cleanly apply' in report
    assert 'CONFLICT' in report
    assert '<summary>Conflicting hunks</summary>' in report
    assert 'stable divergence' in report


def test_missing_target_branch_is_reported(upstream_repo):
    """Check that an absent target branch explains the git failure."""
    with pytest.raises(LookupError) as exc_info:
        backport(upstream_repo, 'plain_sha', 'nonexistent')

    report = str(exc_info.value)

    assert 'Failed to find branch nonexistent' in report
    assert '[RETURN CODE]:' in report


def test_unfetchable_remote_is_reported(tmp_path):
    """Check that a broken remote explains the git failure."""
    with pytest.raises(LookupError) as exc_info:
        backport_pr_sync(
            1, 'deadbeef', 'stable', 'backport',
            'test-org/test-repo', str(tmp_path / 'missing.git'), TOKEN,
        )

    assert '[RETURN CODE]:' in str(exc_info.value)


def test_run_proc_merges_stderr_into_the_output():
    """Check that both streams come back from a successful command."""
    assert run_proc('sh', '-c', 'echo out; echo err >&2') == 'out\nerr\n'


def test_run_proc_exposes_the_output_of_a_failure():
    """Check that a non-zero exit carries the output along."""
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        run_proc('sh', '-c', 'echo boom >&2; exit 3')

    assert exc_info.value.returncode == 3
    assert exc_info.value.output == 'boom\n'


def test_run_proc_survives_undecodable_output():
    """Check that non-UTF-8 bytes do not blow up the capture."""
    assert run_proc('sh', '-c', r'printf "\377"') == (
        '\N{REPLACEMENT CHARACTER}'
    )


@pytest.mark.parametrize(
    ('text', 'expected'),
    (
        pytest.param('nothing to hide', 'nothing to hide', id='no-secret'),
        pytest.param(f'push to {TOKEN}@github.com', None, id='masked'),
    ),
)
def test_sanitize_secret(text, expected):
    """Check that the token never survives sanitization."""
    sanitized = sanitize_secret(text, TOKEN)

    assert TOKEN not in sanitized
    if expected is not None:
        assert sanitized == expected


def test_sanitize_secret_tolerates_an_empty_secret():
    """Check that an empty secret is not expanded into a mask."""
    assert sanitize_secret('unchanged', '') == 'unchanged'


def test_clip_output_keeps_short_text_intact():
    """Check that text within the limit is returned verbatim."""
    assert clip_output('short', limit=10) == 'short'


def test_clip_output_marks_the_truncation():
    """Check that overlong text is cut and flagged."""
    clipped = clip_output('x' * 20, limit=5)

    assert clipped == 'xxxxx\n[... truncated ...]'


@pytest.mark.parametrize(
    ('output', 'expected'),
    (
        pytest.param(
            'remote: error: GH013: Repository rule violations found for '
            'refs/heads/patchback/backport-main-deadbeef-pr-42.\n'
            'remote: - Cannot create ref due to creations being restricted.',
            'ruleset',
            id='ruleset',
        ),
        pytest.param(
            'remote: error: GH006: Protected branch update failed for '
            'refs/heads/stable.\n'
            'remote: error: Changes must be made through a pull request.',
            'branch protection rule',
            id='branch-protection',
        ),
        pytest.param(
            'remote: error: refusing to allow a GitHub App to create or '
            "update workflow '.github/workflows/ci.yml' without "
            '`workflows` permission',
            '`Workflows: write` permission',
            id='workflows',
        ),
        pytest.param(
            'remote: Write access to repository not granted.\n'
            'fatal: unable to access ...: The requested URL returned '
            'error: 403',
            'does not grant sufficient privileges',
            id='fallback',
        ),
    ),
)
def test_push_rejection_is_diagnosed(output, expected):
    """A rejected push is explained by its actual cause."""
    assert expected in explain_push_rejection(
        output, branch='patchback/backport-x', repo_remote='https://e/o/r',
    )


def test_push_rejection_hint_names_the_branch():
    """The ruleset advice points at the branch that got turned down."""
    assert 'patchback/backport-x' in explain_push_rejection(
        'remote: error: GH013: Repository rule violations found',
        branch='patchback/backport-x', repo_remote='https://e/o/r',
    )


def test_ruleset_violation_is_not_reported_as_a_missing_permission():
    """A ruleset rejection must not send maintainers to the app settings."""
    hint = explain_push_rejection(
        'remote: error: GH013: Repository rule violations found',
        branch='patchback/backport-x', repo_remote='https://e/o/r',
    )

    assert 'Contents: write' not in hint


def test_rejected_push_surfaces_the_remote_explanation(upstream_repo):
    """Check that a server-side rejection reaches the maintainers."""
    hook = pathlib.Path(upstream_repo['remote'], 'hooks', 'pre-receive')
    hook.write_text(
        '#!/bin/sh\n'
        'echo "GH013: Repository rule violations found" >&2\n'
        'exit 1\n',
    )
    hook.chmod(0o755)

    with pytest.raises(PermissionError) as exc_info:
        backport(upstream_repo, 'plain_sha', 'stable-clean')

    report = str(exc_info.value)

    assert 'ruleset' in report
    assert 'Bypass list' in report
    assert 'GH013' in report
