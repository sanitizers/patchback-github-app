"""Tests for picking the commits a merged pull request contributed."""

import subprocess

import pytest

from patchback.pick_target import (
    AmbiguousMergeShapeError,
    count_upstreamed_commits,
    resolve_pick_target,
)


@pytest.mark.parametrize(
    ('git_cherry_output', 'expected'),
    (
        pytest.param('', (0, 0), id='no-commits'),
        pytest.param('+ c0ffee\n', (0, 1), id='one-missing'),
        pytest.param('- c0ffee\n', (1, 1), id='one-upstreamed'),
        pytest.param(
            '- c0ffee\n- deadbe\n- f00dfe\n', (3, 3), id='series-upstreamed',
        ),
        pytest.param(
            '+ c0ffee\n+ deadbe\n+ f00dfe\n', (0, 3), id='series-missing',
        ),
        pytest.param(
            '- c0ffee\n+ deadbe\n', (1, 2), id='partially-upstreamed',
        ),
        pytest.param(
            'warning: whatever\n- c0ffee\n', (1, 1), id='ignores-noise',
        ),
    ),
)
def test_count_upstreamed_commits(git_cherry_output, expected):
    assert count_upstreamed_commits(git_cherry_output) == expected


@pytest.mark.parametrize(
    ('upstreamed', 'total', 'expected'),
    (
        pytest.param(0, 0, 'c0ffee', id='no-pr-commits'),
        pytest.param(0, 1, 'c0ffee', id='squashed-single'),
        pytest.param(0, 5, 'c0ffee', id='squashed-series'),
        pytest.param(1, 1, 'c0ffee~1..c0ffee', id='replayed-single'),
        pytest.param(4, 4, 'c0ffee~4..c0ffee', id='replayed-series'),
    ),
)
def test_resolve_pick_target(upstreamed, total, expected):
    assert resolve_pick_target('c0ffee', upstreamed, total) == expected


def test_resolve_pick_target_refuses_partial_match():
    """A pull request only half-present upstream must not be guessed at."""
    with pytest.raises(AmbiguousMergeShapeError, match='2 of the 5 commits'):
        resolve_pick_target('c0ffee', 2, 5)


def _git(repo, *args, check=True):
    return subprocess.run(
        ('git', '-C', str(repo), *args),
        check=check, text=True, capture_output=True,
    ).stdout.strip()


def _commit(repo, name):
    (repo / name).write_text(f'{name}\n')
    _git(repo, 'add', name)
    _git(repo, 'commit', '-m', f'Add {name}')
    return _git(repo, 'rev-parse', 'HEAD')


@pytest.fixture
def repo(tmp_path):
    """A repo with ``main``, a stable branch and a 3-commit PR branch."""
    repo = tmp_path / 'repo'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    _git(repo, 'config', 'user.email', 'patchback@example.com')
    _git(repo, 'config', 'user.name', 'patchback')
    _commit(repo, 'base')
    _git(repo, 'branch', 'stable')
    _git(repo, 'checkout', '-q', '-b', 'pr')
    for name in ('first', 'second', 'third'):
        _commit(repo, name)
    _git(repo, 'checkout', '-q', 'main')
    return repo


def _pick_target(repo, merge_commit_sha, pr_commits_count):
    """Replay the decision ``backport_pr_sync`` makes, against real Git."""
    pr_head_sha = _git(repo, 'rev-parse', '--verify', 'pr^{commit}')
    if pr_head_sha == merge_commit_sha:
        upstreamed = total = pr_commits_count
    else:
        upstreamed, total = count_upstreamed_commits(
            _git(repo, 'cherry', merge_commit_sha, 'pr'),
        )
    return resolve_pick_target(merge_commit_sha, upstreamed, total)


def _backport(repo, pick_target):
    """Cherry-pick onto the stable branch and return the resulting files."""
    _git(repo, 'checkout', '-q', '-b', 'backport', 'stable')
    _git(repo, 'cherry-pick', '-x', pick_target)
    return sorted(_git(repo, 'ls-tree', '--name-only', 'HEAD').split())


def test_squash_merge_backports_the_whole_pull_request(repo):
    _git(repo, 'merge', '--squash', 'pr')
    _git(repo, 'commit', '-m', 'Squashed PR')
    merge_commit_sha = _git(repo, 'rev-parse', 'HEAD')

    pick_target = _pick_target(repo, merge_commit_sha, 3)

    assert pick_target == merge_commit_sha
    assert _backport(repo, pick_target) == [
        'base', 'first', 'second', 'third',
    ]


def test_rebase_merge_backports_every_commit(repo):
    """A rebase-“merge” replays the series — picking its tip loses the rest."""
    _commit(repo, 'unrelated')  # make the rebase actually rewrite the commits
    _git(repo, 'checkout', '-q', '-b', 'rebased', 'pr')
    _git(repo, 'rebase', 'main')
    _git(repo, 'checkout', '-q', 'main')
    _git(repo, 'merge', '--ff-only', 'rebased')
    merge_commit_sha = _git(repo, 'rev-parse', 'HEAD')

    pick_target = _pick_target(repo, merge_commit_sha, 3)

    assert pick_target == f'{merge_commit_sha}~3..{merge_commit_sha}'
    assert _backport(repo, pick_target) == [
        'base', 'first', 'second', 'third',
    ]


def test_rebase_merge_tip_alone_would_lose_commits(repo):
    """Guard the premise: the old single-commit pick really was lossy."""
    _commit(repo, 'unrelated')
    _git(repo, 'checkout', '-q', '-b', 'rebased', 'pr')
    _git(repo, 'rebase', 'main')
    _git(repo, 'checkout', '-q', 'main')
    _git(repo, 'merge', '--ff-only', 'rebased')
    merge_commit_sha = _git(repo, 'rev-parse', 'HEAD')

    assert _backport(repo, merge_commit_sha) == ['base', 'third']


def test_fast_forward_merge_backports_every_commit(repo):
    """A fast-forward leaves no rewritten copies for `git cherry`."""
    _git(repo, 'merge', '--ff-only', 'pr')
    merge_commit_sha = _git(repo, 'rev-parse', 'HEAD')
    assert merge_commit_sha == _git(repo, 'rev-parse', 'pr')

    pick_target = _pick_target(repo, merge_commit_sha, 3)

    assert pick_target == f'{merge_commit_sha}~3..{merge_commit_sha}'
    assert _backport(repo, pick_target) == [
        'base', 'first', 'second', 'third',
    ]


def test_single_commit_squash_merge_is_unchanged(repo):
    """The common case must keep picking exactly the reported merge commit."""
    _git(repo, 'checkout', '-q', '-B', 'pr', 'main')
    _commit(repo, 'only')
    _git(repo, 'checkout', '-q', 'main')
    _git(repo, 'merge', '--squash', 'pr')
    _git(repo, 'commit', '-m', 'Squashed PR')
    merge_commit_sha = _git(repo, 'rev-parse', 'HEAD')

    # The squash of a lone commit is patch-identical to it, so Git reports
    # it as upstreamed and the equivalent one-commit range is picked.
    assert _pick_target(repo, merge_commit_sha, 1) == (
        f'{merge_commit_sha}~1..{merge_commit_sha}'
    )
    assert _backport(
        repo, f'{merge_commit_sha}~1..{merge_commit_sha}',
    ) == ['base', 'only']


def test_merge_commits_in_the_series_are_refused(repo):
    """``~N`` does not describe a branchy history, so refuse to guess."""
    _git(repo, 'checkout', '-q', 'main')
    _commit(repo, 'unrelated')
    _git(repo, 'checkout', '-q', 'pr')
    _git(repo, 'merge', '--no-ff', '-m', 'Merge main into pr', 'main')
    _git(repo, 'checkout', '-q', 'main')
    _git(repo, 'merge', '--ff-only', 'pr')
    merge_commit_sha = _git(repo, 'rev-parse', 'HEAD')

    # 4 commits per GitHub's count (3 + the merge), but ``~4`` walks first
    # parents only and therefore spans a different number of commits.
    pick_target = resolve_pick_target(merge_commit_sha, 4, 4)
    picked_count = int(_git(repo, 'rev-list', '--count', pick_target, '--'))

    assert picked_count != 4
