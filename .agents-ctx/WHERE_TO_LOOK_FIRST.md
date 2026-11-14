# Where to Look First

When picking up a task, get oriented before proposing anything.
Read, in this order:

1. The packaging metadata -- what the project is, what it depends
   on, what it exposes.
2. The source of the module the task is about.
3. The shared test fixtures, then the tests for that module --
   they are the behavioral contract.
4. `tox.ini` and `.pre-commit-config.yaml` -- how things get run
   locally and in CI.
5. The main CI/CD workflow.

Here:

1. `requirements.in` -- the direct dependencies, pinned into
   `requirements.txt` with pip-tools (`.pip-tools.toml`). There's
   no packaging metadata.
2. `patchback/event_handlers.py` -- the webhook handlers doing the
   backports -- and the API helpers next to it, e.g.
   `checks_api.py`, `comments_api.py`, `locking_api.py`.
3. There's no test suite yet.
4. `.pre-commit-config.yaml` -- there's no `tox.ini`.
5. `Procfile`, `runtime.txt` and `app.sh` -- how the service is
   deployed.

Other places worth knowing:

- `app.yml` -- a GitHub App manifest recording the privileges
  Patchback needs. It isn't synced with the public App's settings,
  which have to be changed on its settings page.
- `README.md` -- how repositories use the app.
