"""Repo configuration support for GitHub App installations."""

from __future__ import annotations

import attr
from octomachinery.app.runtime.installation_utils import (
    get_installation_config,
)


DEFAULT_BACKPORT_BRANCH_PREFIX = 'patchback/backports/'
DEFAULT_BACKPORT_LABEL_PREFIX = 'backport-'
DEFAULT_TARGET_BRANCH_PREFIX = ''
DEFAULT_FAILED_BACKPORT_LABEL_PREFIX = 'failed-backport-'


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

    failed_label_prefix: str | None = attr.ib(default=DEFAULT_FAILED_BACKPORT_LABEL_PREFIX)
    """
    Add {failed_label_prefix}-{target_branch} label when backport fails.
    {target_branch_prefix} is stripped from {target_branch}.
    Set to None to disable adding a label on failure.
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
