"""Tests for the restricted backport PR title templating."""

import pytest

from patchback.pr_title import (
    DEFAULT_BACKPORT_PR_TITLE_TEMPLATE,
    KNOWN_PLACEHOLDERS,
    render_backport_pr_title,
)


SUBSTITUTIONS = {
    'pr_number': 3230,
    'pr_title': 'Ensure SystemExit is captured on driver initialization',
    'target_branch': 'stable/3.4',
    'base_branch': 'devel',
    'merge_commit_sha': '5e717ce9c0ffeeba0ddba11c0ffee1234567890a',
}


def render(template, **overrides):
    """Render ``template`` against the sample substitutions."""
    return render_backport_pr_title(template, **{**SUBSTITUTIONS, **overrides})


def test_default_template_matches_the_historical_title():
    """The shipped default reproduces the pre-templating title verbatim."""
    assert render(DEFAULT_BACKPORT_PR_TITLE_TEMPLATE) == (
        '[PR #3230/5e717ce9 backport][stable/3.4] '
        'Ensure SystemExit is captured on driver initialization'
    )


@pytest.mark.parametrize(
    ('template', 'expected'),
    (
        pytest.param(
            'backport: {pr_title}',
            'backport: Ensure SystemExit is captured on driver initialization',
            id='issue-25-short-form',
        ),
        pytest.param(
            '{pr_title} backport #{pr_number}',
            'Ensure SystemExit is captured on driver initialization '
            'backport #3230',
            id='issue-25-suffix-form',
        ),
        pytest.param(
            '[{base_branch} -> {target_branch}] {merge_commit_sha}',
            '[devel -> stable/3.4] 5e717ce9c0ffeeba0ddba11c0ffee1234567890a',
            id='branch-and-full-sha',
        ),
        pytest.param('no placeholders', 'no placeholders', id='literal'),
    ),
)
def test_supported_placeholders_are_interpolated(template, expected):
    """Every allowed placeholder renders its value."""
    assert render(template) == expected


def test_every_known_placeholder_is_renderable():
    """The allowlist does not advertise names the renderer cannot fill."""
    rendered = render(' '.join(f'{{{name}}}' for name in KNOWN_PLACEHOLDERS))
    assert '{' not in rendered


def test_short_sha_is_derived_from_the_full_one():
    """The short SHA is the first 8 characters, not a separate input."""
    assert render(
        '{merge_commit_sha_short}', merge_commit_sha='0123456789abcdef',
    ) == '01234567'


@pytest.mark.parametrize(
    'template',
    (
        pytest.param('{pr_title.__class__}', id='attribute-access'),
        pytest.param(
            '{pr_title.__class__.__init__.__globals__}', id='globals-walk',
        ),
        pytest.param('{pr_title[0]}', id='subscript'),
        pytest.param('{pr_title!r}', id='conversion'),
        pytest.param('{pr_number:100000000}', id='width-blowup'),
    ),
)
def test_format_string_injection_is_inert(template):
    """`str.format` escapes are left verbatim instead of being evaluated."""
    assert render(template) == template


def test_unknown_placeholder_is_rejected_by_name():
    """A typo names itself, and the supported spellings, in the error."""
    with pytest.raises(ValueError) as exc_info:
        render('{src_title} ({pr_number})')

    error = str(exc_info.value)
    assert '{src_title}' in error
    assert '{pr_title}' in error


def test_unknown_placeholders_are_all_reported_at_once():
    """Fixing one typo does not hide the next one."""
    with pytest.raises(ValueError) as exc_info:
        render('{alpha} {omega}')

    assert '{alpha}, {omega}' in str(exc_info.value)


@pytest.mark.parametrize(
    'template',
    (
        pytest.param('', id='empty'),
        pytest.param('   \n  ', id='whitespace-only'),
        pytest.param('{pr_title}', id='empty-after-substitution'),
    ),
)
def test_empty_titles_are_rejected(template):
    """GitHub refuses empty titles, so they surface as a config error."""
    with pytest.raises(ValueError, match='empty title'):
        render(template, pr_title='')


def test_multiline_templates_are_collapsed_to_one_line():
    """A YAML block template cannot smuggle newlines into the title."""
    assert render('{pr_number}\n\n  backport') == '3230 backport'


def test_unmatched_braces_pass_through():
    """Text that is not a placeholder spelling is left alone."""
    assert render('}{ {} {{pr_number}}') == '}{ {} {3230}'
