"""Tests for deciding how a commit can be cherry-picked."""

import subprocess

import pytest

from patchback.merge_commit import (
    UnsupportedMergeCommitError,
    cherry_pick_mainline_args,
    count_commit_parents,
)


@pytest.mark.parametrize(
    ('rev_list_output', 'expected_parents'),
    (
        pytest.param('c0ffee\n', 0, id='root-commit'),
        pytest.param('c0ffee deadbe\n', 1, id='regular-commit'),
        pytest.param('c0ffee deadbe f00d\n', 2, id='merge-commit'),
        pytest.param('c0ffee deadbe f00d babe\n', 3, id='octopus-commit'),
    ),
)
def test_count_commit_parents(rev_list_output, expected_parents):
    assert count_commit_parents(rev_list_output) == expected_parents


def test_count_commit_parents_rejects_empty_output():
    with pytest.raises(ValueError, match='no commit'):
        count_commit_parents('\n')


def test_regular_commit_is_picked_without_a_mainline():
    assert cherry_pick_mainline_args(1) == ()


def test_merge_commit_is_picked_against_its_first_parent():
    assert cherry_pick_mainline_args(2) == ('--mainline', '1')


@pytest.mark.parametrize('parent_count', (3, 4, 17))
def test_octopus_commit_is_refused(parent_count):
    with pytest.raises(UnsupportedMergeCommitError) as exc_info:
        cherry_pick_mainline_args(parent_count)

    error_message = str(exc_info.value)
    assert f'{parent_count:d} parents' in error_message
    assert 'manually' in error_message


def _git(repo, *args):
    return subprocess.check_output(
        ('git', '-C', str(repo), *args),
        text=True,
        env={'GIT_AUTHOR_NAME': 'T', 'GIT_AUTHOR_EMAIL': 't@e',
             'GIT_COMMITTER_NAME': 'T', 'GIT_COMMITTER_EMAIL': 't@e',
             'PATH': '/usr/bin:/bin'},
    )


@pytest.fixture
def octopus_repo(tmp_path):
    """Make a repo whose tip merges three side branches at once.

    The resulting commit has four parents: the branch it was made on plus
    the three that were merged into it.
    """
    _git(tmp_path, 'init', '--initial-branch', 'main', '.')
    (tmp_path / 'base').write_text('base\n')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, 'commit', '-m', 'base')

    for branch in ('one', 'two', 'three'):
        _git(tmp_path, 'checkout', '-b', branch, 'main')
        (tmp_path / branch).write_text(f'{branch}\n')
        _git(tmp_path, 'add', '.')
        _git(tmp_path, 'commit', '-m', branch)

    _git(tmp_path, 'checkout', 'main')
    _git(tmp_path, 'merge', '--no-ff', '-m', 'octopus', 'one', 'two', 'three')
    return tmp_path


def _parents_of(repo, revision):
    return count_commit_parents(
        _git(
            repo, 'rev-list',
            '--no-walk', '--parents', '-n', '1', revision, '--',
        ),
    )


def test_real_git_output_parses_into_parent_counts(octopus_repo):
    """The parser agrees with what `git rev-list --parents` really emits."""
    assert _parents_of(octopus_repo, 'HEAD') == 4
    assert _parents_of(octopus_repo, 'one') == 1
    assert _parents_of(octopus_repo, 'main~1') == 0


def test_a_real_octopus_commit_is_refused(octopus_repo):
    with pytest.raises(UnsupportedMergeCommitError):
        cherry_pick_mainline_args(_parents_of(octopus_repo, 'HEAD'))


def test_a_real_two_parent_merge_keeps_the_first_parent(tmp_path):
    _git(tmp_path, 'init', '--initial-branch', 'main', '.')
    (tmp_path / 'base').write_text('base\n')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, 'commit', '-m', 'base')
    _git(tmp_path, 'checkout', '-b', 'side')
    (tmp_path / 'side').write_text('side\n')
    _git(tmp_path, 'add', '.')
    _git(tmp_path, 'commit', '-m', 'side')
    _git(tmp_path, 'checkout', 'main')
    _git(tmp_path, 'merge', '--no-ff', '-m', 'merge', 'side')

    assert cherry_pick_mainline_args(
        _parents_of(tmp_path, 'HEAD'),
    ) == ('--mainline', '1')
