"""Webhook event handlers."""

import logging

from octomachinery.app.routing import process_event_actions
from octomachinery.app.routing.decorators import process_webhook_payload
from octomachinery.app.runtime.context import RUNTIME_CONTEXT


logger = logging.getLogger(__name__)


@process_event_actions('pull_request', {'labeled'})
@process_webhook_payload
# pylint: disable=too-many-locals
async def on_label_change(
        *,
        label,  # label added
        # https://docs.github.com/en/rest/reference/pulls#get-a-pull-request:
        # phantom merge commit sha if it's open or closed and not merged;
        # real merge commit sha, if it's merged.
        merge_commit_sha,
        merged,  # flag whether it's merged or not
        number,  # PR number
        **_kwargs,  # unimportant event details
) -> None:
    """React to GitHub App pull request / issue label webhook event."""
    if not merged:
        logger.info('PR#%s is not merged, ignoring...', number)
        return

    backport_label_prefix = 'backport-'
    backport_label_len = len(backport_label_prefix)
    # target_branches = [
    #     label[backport_label_len:] for label in labels
    #     if label.startswith(backport_label_prefix)
    # ]
    target_branches = (
        (label['name'][backport_label_len:], )
        if label['name'].startswith(backport_label_prefix)
        else ()
    )

    if not target_branches:
        logger.info('PR#%s does not have backport labels, ignoring...', number)
        return

    gh_api = RUNTIME_CONTEXT.app_installation_client

    logger.info('PR#%s got labeled with "%s"', number, label)
    logger.info('PR#%s merge commit: %s', number, merge_commit_sha)
    logger.info('gh_api=%s', gh_api)
