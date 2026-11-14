# Naming the Ducks

Canonical names for this project, and how to refer to it in
prose. Other files in `.agents-ctx/` (and any generated content)
should say "the project" rather than hardcoding one of these --
reach for a specific name only when the distinction actually
matters (e.g. citing a package, an import, or a repository URL).

## App name: Patchback

This is a GitHub App, deployed as a service -- nothing is
published to PyPI. In prose, it's "Patchback", the public App at
<https://github.com/apps/patchback>.

## Python import name: `patchback`

The package the service runs, as `python -m patchback`.

## GitHub repository slug: `sanitizers/patchback-github-app`

Use it verbatim when it's actually the repository being
referenced (URLs, `gh` invocations, PR/issue citations) -- not as
a stand-in for the app's name in prose.

## Don't confuse it with octomachinery

The app is built on `sanitizers/octomachinery`, a separate
framework project in its own repository. Say which one is meant.
