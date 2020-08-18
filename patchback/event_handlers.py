"""Webhook event handlers."""

import logging

from octomachinery.app.routing import process_event_actions
from octomachinery.app.routing.decorators import process_webhook_payload
from octomachinery.app.runtime.context import RUNTIME_CONTEXT


logger = logging.getLogger(__name__)


@process_event_actions('pull_request', {'labeled'})
@process_webhook_payload
# pylint: disable=too-many-locals
async def on_label_change(*, labels, number, **_kwargs):
    """React to GitHub App pull request / issue label webhook event."""
    gh_api = RUNTIME_CONTEXT.app_installation_client

    logger.info('PR#%s labels got updated to: %r', number, labels)
    logger.info('gh_api=%s', gh_api)
