"""Repo configuration support for GitHub App installations."""

from __future__ import annotations

import logging

import attr
from octomachinery.app.runtime.installation_utils import (
    get_installation_config,
)

from .config_schema import coerce_config_mapping


logger = logging.getLogger(__name__)


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


def _field_types() -> dict:
    """Map every supported config option to its expected value type."""
    attr.resolve_types(PatchbackConfig)
    return {field.name: field.type for field in attr.fields(PatchbackConfig)}


async def get_patchback_config(
        *,
        ref: str = None,
) -> tuple[PatchbackConfig, tuple[str, ...]]:
    """Return patchback config from ``.github/patchback.yml`` file.

    Unknown and ill-typed options fall back to their defaults rather than
    raising: this runs before any check run exists, so a single bad line
    would otherwise disable backporting for the repo with no trace the
    maintainers could see. They come back as warnings for the caller to
    surface instead.
    """
    raw_config = await get_installation_config(
        config_name='patchback.yml', ref=ref,
    )
    config_kwargs, warnings = coerce_config_mapping(raw_config, _field_types())
    for warning in warnings:
        logger.warning('%s', warning)
    return PatchbackConfig(**config_kwargs), warnings
