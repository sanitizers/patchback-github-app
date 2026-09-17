"""Reasoning about the shape of the commit being backported."""

from __future__ import annotations


class UnsupportedMergeCommitError(Exception):
    """Raised when a commit cannot be cherry-picked unambiguously."""


def count_commit_parents(rev_list_parents_output: str) -> int:
    """Return the number of parents listed by ``git rev-list --parents``.

    The output is a single line holding the commit SHA followed by the
    SHAs of its parents, so everything past the first token is a parent.
    """
    tokens = rev_list_parents_output.split()
    if not tokens:
        raise ValueError('`git rev-list --parents` returned no commit')
    return len(tokens) - 1


def cherry_pick_mainline_args(parent_count: int) -> tuple[str, ...]:
    """Return the ``git cherry-pick`` mainline flags for such a commit.

    A regular commit is cherry-picked as-is. A two-parent merge commit is
    picked relative to its first parent — the branch it was merged into —
    which is the diff the pull request contributed.

    An octopus commit has no such single mainline: the diff against any
    one parent also carries the changes of every other branch merged in
    the same commit. Merge queues batching several pull requests are the
    usual source of these. Picking parent 1 anyway would quietly backport
    unrelated pull requests, so refuse instead.
    """
    if parent_count > 2:
        raise UnsupportedMergeCommitError(
            f'The merge commit has {parent_count:d} parents. Such octopus '
            'commits combine several branches at once, so there is no '
            'single set of changes that belongs to this pull request '
            'alone — cherry-picking it would also backport whatever else '
            'was merged in the same commit. Backport the pull request '
            'manually, picking its own commits rather than the merge.',
        )
    return ('--mainline', '1') if parent_count == 2 else ()
