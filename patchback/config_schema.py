"""Tolerant interpretation of the user-supplied repo config mapping.

The App reads ``.github/patchback.yml`` out of repos it has no control
over. Feeding that mapping straight into a constructor makes every
unknown key and every mistyped value fatal, and it fails *before* any
check run or comment exists — so the repo just silently stops getting
backports. Everything here degrades to the built-in default and reports
what it dropped instead of raising.

This module is deliberately dependency-free so that it stays testable
without the GitHub App runtime.
"""

from __future__ import annotations

import difflib
from typing import Any, Mapping


CONFIG_FILE_NAME = '.github/patchback.yml'


def _type_name(type_: Any) -> str:
    return getattr(type_, '__name__', None) or str(type_)


def _is_acceptable(value: Any, expected: Any) -> bool:
    if expected is None:  # Un-annotated field — nothing to check against.
        return True
    if isinstance(value, bool) is not (expected is bool):
        # ``bool`` is a subclass of ``int``, and YAML turns ``on``/``yes``
        # into booleans, so the two directions must not be conflated.
        return False
    return isinstance(value, expected)


def coerce_config_mapping(
        raw_config: Any,
        field_types: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Return usable config kwargs plus warnings about what was dropped.

    ``field_types`` maps each supported option to the type its value must
    have. Options that are unknown or ill-typed are left out of the
    returned kwargs so that the caller's own defaults apply.
    """
    if raw_config is None:
        return {}, ()

    if not isinstance(raw_config, Mapping):
        return {}, (
            f'Ignoring `{CONFIG_FILE_NAME}` entirely: expected a mapping of '
            f'options, got {_type_name(type(raw_config))}. '
            'Using the defaults instead.',
        )

    kwargs: dict[str, Any] = {}
    warnings: list[str] = []

    for key, value in raw_config.items():
        if key not in field_types:
            suggestions = difflib.get_close_matches(str(key), field_types, n=1)
            hint = f' Did you mean `{suggestions[0]}`?' if suggestions else ''
            warnings.append(
                f'Ignoring unknown option `{key}` '
                f'in `{CONFIG_FILE_NAME}`.{hint}',
            )
            continue

        expected = field_types[key]
        if not _is_acceptable(value, expected):
            warnings.append(
                f'Ignoring option `{key}` in `{CONFIG_FILE_NAME}`: expected '
                f'{_type_name(expected)}, got {_type_name(type(value))} '
                f'({value!r}). Using the default instead.',
            )
            continue

        kwargs[key] = value

    return kwargs, tuple(warnings)
