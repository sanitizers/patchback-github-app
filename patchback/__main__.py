"""Patchback robot runner."""

from octomachinery.app.server.runner import run as run_app
from octomachinery.utils.versiontools import get_version_from_scm_tag

from . import event_handlers  # noqa: F401; pylint: disable=unused-import


__name__ == '__main__' and run_app(  # pylint: disable=expression-not-assigned
    name='Patchback-Bot',
    version=get_version_from_scm_tag(root='..', relative_to=__file__),
    url='https://github.com/apps/patchback',
)
