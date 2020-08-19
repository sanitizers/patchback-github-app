"""Webhook event handlers."""

import logging

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


@process_event_actions('pull_request', {'closed'})
@process_webhook_payload
@ensure_pr_merged
async def on_merge_of_labeled_pr(
        *,
        number,  # PR number
        pull_request,  # PR details subobject
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


@process_event_actions('pull_request', {'labeled'})
@process_webhook_payload
@ensure_pr_merged
async def on_label_added_to_merged_pr(
        *,
        label,  # label added
        number,  # PR number
        pull_request,  # PR details subobject
        **_kwargs,  # unimportant event details
) -> None:
    """React to GitHub App pull request / issue label webhook event."""
    target_branches = (
        (label['name'][BACKPORT_LABEL_LEN:], )
        if label['name'].startswith(BACKPORT_LABEL_PREFIX)
        else ()
    )

    if not target_branches:
        logger.info('PR#%s does not have backport labels, ignoring...', number)
        return

    merge_commit_sha = pull_request['merge_commit_sha']
    gh_api = RUNTIME_CONTEXT.app_installation_client

    logger.info('PR#%s got labeled with "%s"', number, label)
    logger.info('PR#%s merge commit: %s', number, merge_commit_sha)
    logger.info('gh_api=%s', gh_api)
