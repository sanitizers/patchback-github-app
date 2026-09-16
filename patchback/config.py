"""Repo configuration support for GitHub App installations."""

from __future__ import annotations

import attr
from octomachinery.app.runtime.installation_utils import (
    get_installation_config,
)


DEFAULT_BACKPORT_BRANCH_PREFIX = 'patchback/backports/'
DEFAULT_BACKPORT_LABEL_PREFIX = 'backport-'
DEFAULT_TARGET_BRANCH_PREFIX = ''
DEFAULT_BACKPORTED_LABEL_PREFIX = ''


@attr.dataclass
class PatchbackConfig:
    """Per GitHub repo App configuration."""

    backport_branch_prefix: str = attr.ib(
        default=DEFAULT_BACKPORT_BRANCH_PREFIX,
    )
    """Backport PR branch prefix."""

    backport_label_prefix: str = attr.ib(default=DEFAULT_BACKPORT_LABEL_PREFIX)
    """Prefix for labels triggering the backport workflow."""

    target_branch_prefix: str = attr.ib(  # e.g 'stable-'
        default=DEFAULT_TARGET_BRANCH_PREFIX,
    )
    """Prefix that the older/stable version branch has."""

    backported_label_prefix: str = attr.ib(  # e.g 'backported-'
        default=DEFAULT_BACKPORTED_LABEL_PREFIX,
    )
    """Prefix of the label marking a backport that landed.

    Empty -- the default -- leaves the original pull request unlabeled on
    success. Set it to label the pull request with
    ``{backported_label_prefix}{branch_id}`` once the backport PR exists,
    which makes the backports that still need a human easy to filter out.
    """

    delete_backport_label_on_success: bool = attr.ib(default=False)
    """Whether to drop the triggering label once the backport PR exists.

    Off by default: dropping the label loses the record of what was asked
    for unless :attr:`backported_label_prefix` is set to keep it.
    """


async def get_patchback_config(
        *,
        ref: str = None,
) -> PatchbackConfig:
    """Return patchback config from ``.github/patchback.yml`` file."""
    return PatchbackConfig(
        **(
            await get_installation_config(config_name='patchback.yml', ref=ref)
        ),
    )
