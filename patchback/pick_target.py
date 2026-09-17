"""Deciding which commits of a merged pull request to cherry-pick."""

from __future__ import annotations


class AmbiguousMergeShapeError(Exception):
    """Raised when the commits a pull request contributed are unclear."""


def count_upstreamed_commits(git_cherry_output: str) -> tuple[int, int]:
    """Return how many of the PR commits landed, and how many there are.

    ``git cherry <upstream> <pr-head>`` prints one line per commit of the
    pull request, prefixed with ``-`` when an equivalent patch is already
    present in ``<upstream>`` and with ``+`` when it is not.
    """
    upstreamed = total = 0
    for line in git_cherry_output.splitlines():
        mark = line.split(' ', 1)[0]
        if mark not in {'+', '-'}:
            continue
        total += 1
        upstreamed += mark == '-'
    return upstreamed, total


def resolve_pick_target(
        merge_commit_sha: str, upstreamed: int, total: int,
) -> str:
    """Return the committish holding this pull request's changes.

    GitHub reports a single ``merge_commit_sha`` whatever the merge
    strategy was, but that commit means different things:

    * squash-“merge” — one new commit carrying the whole pull request, so
      none of the original commits are upstream patch-wise;
    * rebase-“merge” and fast-forward pushes — the pull request's commits
      are replayed onto the base branch, so ``merge_commit_sha`` is merely
      the *last* of them and picking it alone drops all the others.

    Hence the answer is driven by how many of the pull request's commits
    are already upstream rather than by guessing the strategy: all of them
    means a replayed series, none of them means a single squashed commit.
    Anything in between is a shape this cannot name — refuse instead of
    backporting a slice of the pull request and calling it a success.
    """
    if total and upstreamed == total:
        return f'{merge_commit_sha}~{total:d}..{merge_commit_sha}'
    if not upstreamed:
        return merge_commit_sha
    raise AmbiguousMergeShapeError(
        f'Only {upstreamed:d} of the {total:d} commits of this pull request '
        f'are present in `{merge_commit_sha}`, so it is impossible to tell '
        'which commits it contributed to the base branch. Backporting the '
        'merge commit alone would silently drop the rest of the pull '
        'request, so no backport was attempted — please cherry-pick the '
        'commits manually.',
    )
