"""Tests for the backport label naming rules."""

import pytest

from patchback.labels import is_backport_label, to_backported_label


DEFAULTS = {
    'backport_prefix': 'backport-',
    'backported_prefix': 'backported-',
}


@pytest.mark.parametrize(
    ('label', 'expected'),
    (
        ('backport-3.8', True),
        ('backport-stable/2.0', True),
        ('backport-', True),
        ('bug', False),
        ('needs-backport-3.8', False),
        ('Backport-3.8', False),
    ),
)
def test_backport_label_recognition(label, expected):
    assert is_backport_label(label, **DEFAULTS) is expected


def test_completion_label_does_not_request_a_backport():
    """A completion label must never re-trigger the workflow.

    The prefixes are configurable and the completion one may extend the
    trigger one. Here ``backported-3.8`` starts with ``backport``, so a
    plain prefix check reads it as a request to backport into a branch
    named ``ed-3.8`` -- and labeling on success makes the App trigger
    itself, over and over.
    """
    assert is_backport_label(
        'backported-3.8',
        backport_prefix='backport', backported_prefix='backported',
    ) is False


def test_completion_labels_are_requests_when_the_feature_is_off():
    """An empty completion prefix must not swallow every label."""
    assert is_backport_label(
        'backport-3.8', backport_prefix='backport-', backported_prefix='',
    ) is True


def test_unrelated_completion_prefix_keeps_requests_intact():
    assert is_backport_label(
        'backport-3.8', backport_prefix='backport-', backported_prefix='done-',
    ) is True


def test_default_prefixes_do_not_collide():
    """The default completion label is not a trigger label to begin with."""
    assert is_backport_label('backported-3.8', **DEFAULTS) is False


@pytest.mark.parametrize(
    ('label', 'expected'),
    (
        ('backport-3.8', 'backported-3.8'),
        ('backport-stable/2.0', 'backported-stable/2.0'),
    ),
)
def test_completion_label_derivation(label, expected):
    assert to_backported_label(label, **DEFAULTS) == expected


def test_completion_label_derivation_respects_custom_prefixes():
    assert to_backported_label(
        'bp/3.8', backport_prefix='bp/', backported_prefix='done/',
    ) == 'done/3.8'
