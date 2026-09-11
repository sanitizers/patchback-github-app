"""
Misc. utility functions
"""

from __future__ import annotations

from typing import TypeVar

_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")


def strip_nones(mapping: dict[_T1, _T2 | None]) -> dict[_T1, _T2]:
    """
    Remove keys set to None from a dictionary

    Returns:
        A new dictionary instance
    """
    return {key: value for key, value in mapping.items() if value is not None}
