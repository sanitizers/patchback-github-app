"""Tests that one failing target branch does not cancel the others.

``patchback.event_handlers`` imports ``anyio``, ``gidgethub`` and
``octomachinery``. The suite deliberately depends on nothing but pytest and
the stdlib, so those are replaced with inert stand-ins before the import
below. The webhook decorators become identity functions, which is exactly
what these tests want: they exercise the handler body, not the router.
"""

import asyncio
import sys
import types

import pytest


def _install_stub(name, **attrs):
    module = types.ModuleType(name)
    for attr_name, value in attrs.items():
        setattr(module, attr_name, value)
    sys.modules[name] = module


def _identity(obj):
    return obj


for _pkg in (
        'octomachinery', 'octomachinery.app', 'octomachinery.app.runtime',
):
    _install_stub(_pkg)
_install_stub('anyio', run_in_thread=None)
_install_stub(
    'gidgethub',
    BadRequest=type('BadRequest', (Exception,), {}),
    ValidationError=type('ValidationError', (Exception,), {}),
)
_install_stub(
    'octomachinery.app.routing',
    process_event_actions=lambda *args, **kwargs: _identity,
)
_install_stub(
    'octomachinery.app.routing.decorators', process_webhook_payload=_identity,
)
_install_stub('octomachinery.app.runtime.context', RUNTIME_CONTEXT=None)
_install_stub('patchback.config', get_patchback_config=None)

from patchback import event_handlers  # noqa: E402


class FakeConfig:
    backport_label_prefix = 'backport-'
    target_branch_prefix = ''
    backport_branch_prefix = 'patchback/backports/'


def make_payload(*label_names):
    return {
        'number': 7,
        'pull_request': {
            'merged': True,
            'title': 'Fix a thing',
            'body': 'Body',
            'locked': False,
            'active_lock_reason': None,
            'labels': [{'name': name} for name in label_names],
            'base': {'ref': 'main'},
            'head': {'sha': 'headsha'},
            'merge_commit_sha': 'mergesha',
        },
        'repository': {
            'pulls_url': '/repos/o/r/pulls',
            'full_name': 'o/r',
            'clone_url': 'https://github.com/o/r.git',
        },
    }


@pytest.fixture
def patched_handler(monkeypatch):
    """Stub out config fetching and record backport attempts."""
    async def fake_config(*, ref=None):
        return FakeConfig()

    monkeypatch.setattr(event_handlers, 'get_patchback_config', fake_config)

    attempts = []

    def record(failing_branches=()):
        async def fake_process(*args):
            target_branch = args[8]
            attempts.append(target_branch)
            if target_branch in failing_branches:
                raise RuntimeError(f'Server disconnected on {target_branch}')

        monkeypatch.setattr(
            event_handlers, 'process_pr_backport_labels', fake_process,
        )
        return attempts

    return record


def test_every_target_branch_is_attempted_when_one_fails(patched_handler):
    """A failure on the first branch must not skip the remaining ones."""
    attempts = patched_handler(failing_branches={'3.0'})

    with pytest.raises(RuntimeError, match='Server disconnected on 3.0'):
        asyncio.run(
            event_handlers.on_merge_of_labeled_pr(
                **make_payload('backport-3.0', 'backport-2.9'),
            ),
        )

    assert attempts == ['3.0', '2.9']


def test_the_first_failure_is_the_one_reraised(patched_handler):
    """Every branch runs, and the earliest error still surfaces."""
    attempts = patched_handler(failing_branches={'3.0', '2.9'})

    with pytest.raises(RuntimeError, match='Server disconnected on 3.0'):
        asyncio.run(
            event_handlers.on_merge_of_labeled_pr(
                **make_payload('backport-2.9', 'backport-3.0'),
            ),
        )

    assert attempts == ['3.0', '2.9']


def test_nothing_is_raised_when_every_branch_succeeds(patched_handler):
    """The happy path stays silent."""
    attempts = patched_handler()

    asyncio.run(
        event_handlers.on_merge_of_labeled_pr(
            **make_payload('backport-3.0', 'backport-2.9', 'unrelated'),
        ),
    )

    assert attempts == ['3.0', '2.9']


def test_unlabeled_prs_are_ignored(patched_handler):
    """PRs without backport labels attempt nothing."""
    attempts = patched_handler()

    asyncio.run(
        event_handlers.on_merge_of_labeled_pr(**make_payload('documentation')),
    )

    assert attempts == []
