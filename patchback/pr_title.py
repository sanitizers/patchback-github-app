"""Rendering of the backport pull request title from a repo-set template.

The template comes from ``.github/patchback.yml`` in the target repo, so it
is only as trusted as that repo's default branch. Two properties follow from
that and shape this module:

* Substitution is **not** :meth:`str.format`. A format string can walk
  attributes (``{x.__class__.__init__.__globals__}``) and index containers,
  which would turn a config file into a data exfiltration primitive. Here,
  only ``{name}`` spellings matching :data:`PLACEHOLDER_RE` are replaced and
  the names are checked against :data:`KNOWN_PLACEHOLDERS` — anything else is
  left in the title verbatim, never evaluated.
* A broken template must not break backporting. Rendering raises
  :class:`ValueError` describing the problem and the caller falls back to
  :data:`DEFAULT_BACKPORT_PR_TITLE_TEMPLATE`, rather than the config being
  rejected outright (which would make one typo disable the App repo-wide).
"""

import re


DEFAULT_BACKPORT_PR_TITLE_TEMPLATE = (
    '[PR #{pr_number}/{merge_commit_sha_short} backport]'
    '[{target_branch}] {pr_title}'
)
"""Historical title format, kept as the default for backward compatibility."""

PLACEHOLDER_RE = re.compile(r'\{(\w+)\}')
"""Spelling of a substitutable placeholder. Deliberately allows no dots."""

KNOWN_PLACEHOLDERS = frozenset({
    'base_branch',
    'merge_commit_sha',
    'merge_commit_sha_short',
    'pr_number',
    'pr_title',
    'target_branch',
})
"""Names a repo is allowed to interpolate into its backport PR titles."""


def render_backport_pr_title(
        template: str, *,
        pr_number: int,
        pr_title: str,
        target_branch: str,
        base_branch: str,
        merge_commit_sha: str,
) -> str:
    """Return the backport PR title ``template`` renders into.

    :raises ValueError: If the template names unknown placeholders or
                        renders into an empty title.
    """
    unknown = sorted(
        set(PLACEHOLDER_RE.findall(template)) - KNOWN_PLACEHOLDERS,
    )
    if unknown:
        raise ValueError(
            'Unknown placeholder(s) in the backport PR title template: '
            '{bad!s}. The supported ones are: {known!s}.'.format(
                bad=', '.join('{' + name + '}' for name in unknown),
                known=', '.join(
                    '{' + name + '}' for name in sorted(KNOWN_PLACEHOLDERS)
                ),
            ),
        )

    substitutions = {
        'base_branch': base_branch,
        'merge_commit_sha': merge_commit_sha,
        'merge_commit_sha_short': merge_commit_sha[:8],
        'pr_number': pr_number,
        'pr_title': pr_title,
        'target_branch': target_branch,
    }
    rendered = PLACEHOLDER_RE.sub(
        lambda match: str(substitutions[match.group(1)]), template,
    )

    # GitHub PR titles are single-line; a template spanning lines (trivial to
    # write in YAML) would otherwise produce a mangled title.
    collapsed = ' '.join(rendered.split())
    if not collapsed:
        raise ValueError(
            'The backport PR title template rendered into an empty title.',
        )
    return collapsed
