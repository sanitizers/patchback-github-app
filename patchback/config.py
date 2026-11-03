"""Repo configuration support for GitHub App installations."""

from __future__ import annotations

import attr
from octomachinery.app.runtime.installation_utils import (
    get_installation_config,
)

from .pr_title import DEFAULT_BACKPORT_PR_TITLE_TEMPLATE


DEFAULT_BACKPORT_BRANCH_PREFIX = 'patchback/backports/'
DEFAULT_BACKPORT_LABEL_PREFIX = 'backport-'
DEFAULT_TARGET_BRANCH_PREFIX = ''


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

    backport_pr_title_template: str = attr.ib(
        default=DEFAULT_BACKPORT_PR_TITLE_TEMPLATE,
    )
    """Template of the backport PR title.

    Only the placeholders listed in
    :data:`~patchback.pr_title.KNOWN_PLACEHOLDERS` are interpolated; see
    :mod:`patchback.pr_title` for why the substitution is restricted.
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
