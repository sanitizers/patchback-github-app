"""Webhook event handlers."""

import logging
import pathlib
import tempfile

from anyio import run_in_thread
from pygit2 import clone_repository, RemoteCallbacks, Signature, UserPass

from octomachinery.app.routing import process_event_actions
from octomachinery.app.routing.decorators import process_webhook_payload
from octomachinery.app.runtime.context import RUNTIME_CONTEXT


logger = logging.getLogger(__name__)

BACKPORT_LABEL_PREFIX = 'backport-'
BACKPORT_LABEL_LEN = len(BACKPORT_LABEL_PREFIX)


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
        repo_slug: str, repo_remote: str, installation_access_token: str,
) -> None:
    """Returns a branch with backported PR pushed to GitHub.

    It clones the ``repo_remote`` using a GitHub App Installation token
    ``installation_access_token`` to authenticate. Then, it cherry-picks
    ``merge_commit_sha`` onto a new branch based on the
    ``target_branch`` and pushes it back to ``repo_remote``.
    """
    backport_pr_branch = (
        f'patchback/backports/{target_branch}/'
        f'{merge_commit_sha}/pr{pr_number}'
    )
    token_auth_callbacks = RemoteCallbacks(
        credentials=UserPass(
            'x-access-token', installation_access_token,
        ),
    )
    with tempfile.TemporaryDirectory(
            prefix=f'{repo_slug.replace("/", "--")}---{target_branch}---',
            suffix=f'---PR-{pr_number}.git',
    ) as tmp_dir:
        repo = clone_repository(
            url=repo_remote,
            path=pathlib.Path(tmp_dir),
            bare=True,
            checkout_branch=target_branch,
# TODO: figure out if using "remote" would be cleaner:
#            remote=,  # callable (Repository, name, url) -> Remote
            callbacks=token_auth_callbacks,
        )
        repo.remotes.add_fetch(  # phantom merge heads
            'origin',
            # '+refs/pull/*/merge:refs/merge/origin/*',
            f'+refs/pull/{pr_number}/merge:refs/merge/origin/{pr_number}',
        )
        repo.remotes.add_fetch(  # read-only PR branch heads
            'origin',
            # '+refs/pull/*/head:refs/pull/origin/*',
            f'+refs/pull/{pr_number}/head:refs/pull/origin/{pr_number}',
        )
        github_upstream_remote = repo.remotes['origin']
        github_upstream_remote.fetch(callbacks=token_auth_callbacks)

        repo.remotes.add_push(  # PR backport branch
            'origin',
            ':'.join((target_branch, backport_pr_branch))
        )

        # Ref: https://www.pygit2.org/recipes/git-cherry-pick.html
        cherry = repo.revparse_single(merge_commit_sha)
        backport_branch = repo.create_branch(
            backport_pr_branch, repo.branches[target_branch].peel(),
        )

        base = repo.merge_base(cherry.oid, backport_branch.target)
        base_tree = cherry.parents[0].tree

        index = repo.merge_trees(base_tree, backport_branch, cherry)
        tree_id = index.write_tree(repo)

        author = cherry.author
        committer = Signature('Patchback', 'patchback@sanitizers.bot')

        repo.create_commit(
            backport_branch.name,
            author, committer,
            cherry.message,
            tree_id,
            [backport_branch.target],
        )
        github_upstream_remote.push(
            [f'HEAD:refs/heads/{backport_pr_branch}'],
            callbacks=token_auth_callbacks,  # clone callbacks aren't preserved
        )

    return backport_pr_branch


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
    labels = pull_request['labels']
    target_branches = [
        label[BACKPORT_LABEL_LEN:] for label in labels
        if label.startswith(BACKPORT_LABEL_PREFIX)
    ]

    if not target_branches:
        logger.info('PR#%s does not have backport labels, ignoring...', number)
        return

    merge_commit_sha = pull_request['merge_commit_sha']
    gh_api = RUNTIME_CONTEXT.app_installation_client

    logger.info('PR#%s is labeled with "%s"', number, labels)
    logger.info('PR#%s merge commit: %s', number, merge_commit_sha)
    logger.info('gh_api=%s', gh_api)
    for target_branch in target_branches:
        backport_pr_branch = await run_in_thread(
            backport_pr_sync,
            number, merge_commit_sha, target_branch,
            repository['full_name'],
            repository['clone_url'],
            (await RUNTIME_CONTEXT.app_installation.get_token()).token,
        )
        logger.info('Backport PR branch: `%s`', backport_pr_branch)


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
    label_name = label['name']
    if not label_name.startswith(BACKPORT_LABEL_PREFIX):
        logger.info(
            'PR#%s got labeled with %s but it is not '
            'a backport label, ignoring...',
            number, label_name,
        )
        return

    target_branch = label_name[BACKPORT_LABEL_LEN:]
    merge_commit_sha = pull_request['merge_commit_sha']
    gh_api = RUNTIME_CONTEXT.app_installation_client

    logger.info(
        'PR#%s got labeled with "%s". It needs to be backported to %s',
        number, label_name, target_branch,
    )
    logger.info('PR#%s merge commit: %s', number, merge_commit_sha)
    logger.info('gh_api=%s', gh_api)

    backport_pr_branch = await run_in_thread(
        backport_pr_sync,
        number, merge_commit_sha, target_branch,
        repository['full_name'],
        repository['clone_url'],
        (await RUNTIME_CONTEXT.app_installation.get_token()).token,
    )
    logger.info('Backport PR branch: `%s`', backport_pr_branch)
