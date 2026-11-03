"""Naming rules for the labels driving the backport workflow."""

from __future__ import annotations


def is_backport_label(
        label: str, *, backport_prefix: str, backported_prefix: str,
) -> bool:
    """Tell whether ``label`` requests a backport.

    ``backported_prefix`` marks backports that already happened. Both
    prefixes are configurable, so the completion prefix may extend the
    trigger one -- ``backport``/``backported`` does, the default
    ``backport-``/``backported-`` pair does not. Where it does, a plain
    prefix check would read the completion label as a request to backport
    into a branch named after the leftover suffix, and labeling a landed
    backport would make the App trigger itself.
    """
    if not label.startswith(backport_prefix):
        return False

    return not (backported_prefix and label.startswith(backported_prefix))


def to_backported_label(
        label: str, *, backport_prefix: str, backported_prefix: str,
) -> str:
    """Return the label marking ``label``'s backport as done."""
    return f'{backported_prefix}{label[len(backport_prefix):]}'
