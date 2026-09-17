"""Patchback robot runner."""

import asyncio

from octomachinery.app.server.runner import run as run_app
from octomachinery.utils.versiontools import get_version_from_scm_tag

from . import event_handlers  # noqa: F401; pylint: disable=unused-import


# NOTE: `octomachinery` caps `anyio` below v2, and `anyio` v1 boots the app
# NOTE: via `asyncio.get_event_loop()`, relying on it to implicitly create a
# NOTE: loop when the main thread has none. Python 3.14 removed that fallback
# NOTE: and raises `RuntimeError` instead, so the app never starts there.
# NOTE: Making the loop up front is what the interpreter used to do for us. It
# NOTE: is harmless on older Pythons and stops being necessary once
# NOTE: `octomachinery` supports `anyio` v2+.
# pylint: disable-next=expression-not-assigned
__name__ == '__main__' and asyncio.set_event_loop(asyncio.new_event_loop())

__name__ == '__main__' and run_app(  # pylint: disable=expression-not-assigned
    name='Patchback-Bot',
    version=get_version_from_scm_tag(root='..', relative_to=__file__),
    url='https://github.com/apps/patchback',
)
