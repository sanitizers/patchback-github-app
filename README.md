[![SWUbanner]][SWUdocs]

[![pre-commit.ci status badge]][pre-commit.ci results page]
[![GH Sponsors badge]][GH Sponsors URL]

[SWUbanner]:
https://raw.githubusercontent.com/vshymanskyy/StandWithUkraine/main/banner-direct-single.svg
[SWUdocs]:
https://github.com/vshymanskyy/StandWithUkraine/blob/main/docs/README.md

[pre-commit.ci status badge]:
https://results.pre-commit.ci/badge/github/sanitizers/patchback-github-app/master.svg
[pre-commit.ci results page]:
https://results.pre-commit.ci/latest/github/sanitizers/patchback-github-app/master

[GH Sponsors badge]:
https://img.shields.io/badge/%40webknjaz-transparent?logo=githubsponsors&logoColor=%23EA4AAA&label=Sponsor&color=2a313c
[GH Sponsors URL]: https://github.com/sponsors/webknjaz


# patchback-github-app

This is the GitHub App that cherry-picks merged pull requests into your
maintenance branches. You label a pull request, it gets merged, and the
bot attempts the corresponding backport PR — no manual `git cherry-pick`
juggling.

The project is `patchback-github-app`; the App it registers as, hosted or
self-run, is Patchback. Below, *Patchback* means the App.

> [!NOTE]
> The attempt is best-effort. It can come up short because the patch
> conflicts with the target branch, because GitHub is having a bad day —
> nothing here is persisted, so a failed attempt is never retried, however
> many hours or days pass — or because the webhook is never delivered, in
> which case the bot never learns there was anything to do.

Patchback does not come back later to confirm that a backport exists,
whether opened by the bot or by hand. Dropping the request label once the
backport PR is there is tracked in [#12].

[#12]: https://github.com/sanitizers/patchback-github-app/issues/12

Patchback is in use by [@pytest-dev], [@theforeman], [@ogajduse],
[@fao89], [@pulp], [@ansible-community], [@cherrypy], [@ansible],
[@aio-libs], [@ansible-collections], [@webknjaz] and [@sanitizers].

[@pytest-dev]: https://github.com/sponsors/pytest-dev
[@theforeman]: https://github.com/sponsors/theforeman
[@ogajduse]: https://github.com/sponsors/ogajduse
[@fao89]: https://github.com/sponsors/fao89
[@pulp]: https://github.com/sponsors/pulp
[@ansible-community]: https://github.com/sponsors/ansible-community
[@cherrypy]: https://github.com/sponsors/cherrypy
[@ansible]: https://github.com/sponsors/ansible
[@aio-libs]: https://github.com/sponsors/aio-libs
[@ansible-collections]: https://github.com/sponsors/ansible-collections
[@webknjaz]: https://github.com/sponsors/webknjaz
[@sanitizers]: https://github.com/sponsors/sanitizers

> [!IMPORTANT]
> The hosted deployment is a small, hobby-scale service. It was always
> meant for a limited circle of projects rather than for signups at
> scale, so please talk to [@webknjaz] before pointing it at a new
> organisation. [Running your own instance](#running-your-own-instance)
> is the option that always works, and
> [App permissions](#app-permissions) covers what an installation asks
> for and why.


## Prior art

CPython's [cherry-picker] is the nearest neighbour. It is a CLI that
contributors run in their own development environments, authenticating
with whatever credentials the environment holds, and
[miss-islington] — a web service authenticating as a machine account and
configured for `python/cpython` and nothing else — imports it, so the two
are effectively one thing. A few other projects, aiohttp and Ansible
among them, configured cherry-picker for local runs of their own.

Patchback is only ever the service half: a GitHub App, with labels,
per-repository configuration and GitHub's own UI where cherry-picker has
a command line. That makes the contributor experience roughly the inverse
of CPython's, and a CLI is not ruled out later. The cherry-picking itself
happens in a throwaway worktree under a temporary directory; doing it in
memory with [pygit2] rather than through the Git CLI was the original
intent, but the library's platform support was not there at the time, and
it stays on the wish list — for cherry-picker as much as for this
project.

[History](#history) covers how it got here.

[cherry-picker]: https://github.com/python/cherry-picker
[miss-islington]: https://github.com/python/miss-islington
[pygit2]: https://github.com/libgit2/pygit2


## Usage

Add a `backport-<branch>` label to a pull request. Once that PR is
**merged**, Patchback backports it to the `<branch>` branch.

Both orderings work:

* label the PR *before* it is merged — the backport starts on merge;
* label an already merged PR — the backport starts right away.

Pull requests that are closed without being merged are ignored, so
labelling early is safe.

A single PR may carry several backport labels. Each one produces its own
backport PR.

### Example

A pull request #42 labelled `backport-3.12`, merged into `main` as
commit `1a2b3c4d…`, produces:

| | |
| --- | --- |
| Branch | `patchback/backports/3.12/1a2b3c4d…/pr-42` |
| Title | `[PR #42/1a2b3c4d backport][3.12] <original title>` |
| Base | `3.12` |

The backport PR description opens with a pointer back to the original:

> **This is a backport of PR #42 as merged into main (1a2b3c4d…).**

followed by the original PR description.

### What the bot reports

While working, Patchback posts a comment on the original pull request
and keeps editing that same comment as it makes progress. When the App
has the Checks permission, it also publishes a `Backport to <branch>`
check run carrying the same status.

If the pull request is locked, the bot unlocks it in order to comment
and locks it back afterwards, preserving the original lock reason.

### When a backport fails

Cherry-picks conflict — that is normal, and it is much of why the bot
exists. Patchback reports which stage failed:

* **target branch does not exist** — the label does not correspond to a
  branch in the repository (check your
  [`target_branch_prefix`](#configuration));
* **conflicts found** — the patch does not apply cleanly;
* **could not push** — the App installation lacks write access;
* **creation of the backport PR failed** — GitHub rejected the PR.

For every failure other than a missing target branch, the comment also
carries step-by-step instructions for finishing the backport by hand.


## Configuration

Configuration is optional. To change the defaults, commit a
`.github/patchback.yml` file to your repository. The values below are the
defaults:

```yaml
---

# Prefix of the branches the bot pushes:
backport_branch_prefix: patchback/backports/

# Labels carrying this prefix trigger a backport:
backport_label_prefix: backport-

# Prepended to the rest of the label to compute the target branch:
target_branch_prefix: ''

...
```

The target branch is derived as
`target_branch_prefix + label_name[len(backport_label_prefix):]`, which
covers maintenance branches that are not named after the version alone.
[cheroot] backports `backport-8.x` to `maint/8.x` with:

```yaml
---

backport_label_prefix: backport-
target_branch_prefix: maint/

...
```

The prefixes are matched verbatim, so they can end in something other
than a dash. [pytest] uses space-delimited labels — `backport 9.1.x` —
with:

```yaml
---

backport_label_prefix: 'backport '

...
```

[cheroot]: https://github.com/cherrypy/cheroot
[pytest]: https://github.com/pytest-dev/pytest


## App permissions

A Patchback installation needs these repository permissions:

| Permission | Access | Used for |
| --- | --- | --- |
| `Metadata` | Read-only | Mandatory for every GitHub App. |
| `Contents` | Read & write | Cloning the repo and pushing the backport branch. |
| `Pull requests` | Read & write | Creating backport PRs, commenting, locking. |
| `Checks` | Read & write | Publishing the `Backport to <branch>` check run. |
| `Single file` | Read-only | Reading `.github/patchback.yml`. |
| `Workflows` | Read & write | Only needed if backports may touch `.github/workflows/`. |

The App subscribes to the `Pull request` event.

Checks access is optional: without it the bot skips the check run and
reports through its pull request comment only. Missing `Contents` or
`Workflows` access surfaces as a *could not push* failure.


## How it works

For each backport, Patchback:

1. clones the repository into a temporary directory, authenticating with
   an installation access token;
2. branches off the target branch;
3. cherry-picks the merge commit with `-x`, the `histogram` diff
   algorithm and rename detection, adding `--mainline 1` when that
   commit is itself a merge commit;
4. force-pushes the branch with `--force-with-lease` — the bot owns
   these branches, so it is free to rewrite them;
5. opens the backport pull request with `maintainer_can_modify` set.

Access tokens are masked out of any command output the bot reports back.


## Running your own instance

Patchback is a plain web service built on [octomachinery].

```console
$ python -m venv .venv && . .venv/bin/activate
$ pip install -r requirements.txt
$ cp .env.example .env  # ... and then fill it in
$ python -m patchback
```

The settings come from the environment — see `.env.example`:

| Variable | Meaning |
| --- | --- |
| `HOST`, `PORT` | Where the web service listens. |
| `ENV`, `DEBUG` | Set to `dev` / `true` for local development. |
| `GITHUB_APP_IDENTIFIER` | Numeric App ID, from the GitHub UI. |
| `GITHUB_PRIVATE_KEY` | The App's private key. |
| `GITHUB_PRIVATE_KEY_FINGERPRINT` | Fingerprint of that key, from the GitHub UI. |
| `GITHUB_WEBHOOK_SECRET` | Only if the App declares one. |
| `SENTRY_DSN` | Optional error reporting. |

A `Procfile` and an `app.sh` entry point are included for
Heroku-style deployments.


## History

Around 2018, GitHub was pushing Apps as the way to build integrations and
had just made the Checks API available to them exclusively, while Travis
CI was trialling the platform in alpha. There was nothing for any of it in
Python — [Probot] was only starting, and the helpers that existed mostly
covered plain webhook handling — so [@webknjaz] set out to write a
microframework for GitHub Apps that felt Pythonic, which is
[octomachinery]. Reimplementing a few checks that sat at the intersection
of the tooling already in use across the ecosystem was a good way to
exercise it.

Very few projects have a standard process they call *backporting*. The
ones in view were Gerrit with a handful of Git aliases at PortaOne some
fifteen years earlier, then CPython, aiohttp and Ansible — each of them a
mixture of automatic, semi-automatic and by-hand patch backporting, and
each expecting a change log fragment to travel with the patch. A pull
request against the main branch may carry several commits and land as a
merge commit; its backports are always squashed into a single one.

Those fragments are usually [Towncrier]'s, out of the Twisted ecosystem,
and managing them is what [chronographer] does — inspired by
[browntruck] and [bedevere]. Other ecosystems manage them differently:
CPython has [blurb], [blurb_it] and bedevere; OpenStack has [reno];
Ansible has [antsibull-changelog], which is reno-based; [coveragepy] uses
[scriv]. Unreleased Towncrier fragments also get a Sphinx integration for
previewing them, [sphinxcontrib-towncrier].

Cherry-picking and release notes are two halves of one release strategy,
so Patchback and Chronographer were started within a day of each other,
the change log side first — it was the more tractable of the two for a
Towncrier-shaped process, and not really doable for a reno-based one like
Ansible's. Backporting came into focus when [@felixfontein] raised it for
Ansible collections on IRC, cherry-picker being already wired up there for
manual runs. Having just worked on cherry-picker's own refactoring, and
having seen the same process in several places by then, [@webknjaz] shaped
Patchback along broadly the same lines as Chronographer.

[Probot]: https://probot.github.io
[octomachinery]: https://octomachinery.dev
[Towncrier]: https://github.com/twisted/towncrier
[chronographer]: https://github.com/sanitizers/chronographer-github-app
[browntruck]: https://github.com/pypa/browntruck
[bedevere]: https://github.com/python/bedevere
[blurb]: https://github.com/python/blurb
[blurb_it]: https://github.com/python/blurb_it
[reno]: https://docs.openstack.org/reno/latest/
[antsibull-changelog]: https://github.com/ansible-community/antsibull-changelog
[coveragepy]: https://github.com/nedbat/coveragepy
[scriv]: https://github.com/nedbat/scriv
[sphinxcontrib-towncrier]: https://sphinxcontrib-towncrier.rtfd.io
[@felixfontein]: https://github.com/felixfontein


## Contributing

Bug reports and pull requests are welcome at
https://github.com/sanitizers/patchback-github-app.


## License

Patchback is distributed under the terms of the
[GNU General Public License v3.0](LICENSE).
