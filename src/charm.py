#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/#build-a-charm

"""OpenDKIM charm."""

import logging
import os
import typing
from pathlib import Path

import ops
from charms.operator_libs_linux.v0 import apt
from jinja2 import Environment, FileSystemLoader, select_autoescape

logger = logging.getLogger(__name__)

OPENDKIM_PACKAGE_NAME = "opendkim"
OPENDKIM_MILTER_PORT = 8892
OPENDKIM_CONFIG_TEMPLATE = Path("opendkim.conf.j2")
OPENDKIM_CONFIG_PATH = Path("/etc/opendkim.conf")


class OpenDKIMCharm(ops.CharmBase):
    """Charm the service."""

    def __init__(self, *args: typing.Any):
        """Construct.

        Args:
            args: Arguments passed to the CharmBase parent constructor.
        """
        super().__init__(*args)
        self.framework.observe(self.on.install, self._install)
        self.framework.observe(self.on.upgrade_charm, self._install)
        self.framework.observe(self.on.config_changed, self._reconcile)
        self.unit.open_port("tcp", OPENDKIM_MILTER_PORT)

    def _install(self, _: ops.EventBase) -> None:
        """Install opendkim package."""
        self.unit.status = ops.MaintenanceStatus("installing opendkim")
        apt.add_package(package_names=OPENDKIM_PACKAGE_NAME, update_cache=True)
        self.unit.status = ops.ActiveStatus()

    def _reconcile(self, _: ops.EventBase) -> None:
        """TODO."""
        config = OpenDKIMConfig.from_charm(self)
        # Jinja2 context
        context = {str(config): str(config)}
        env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=select_autoescape(),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(str(OPENDKIM_CONFIG_TEMPLATE))
        rendered = template.render(context)
        render_file(OPENDKIM_CONFIG_PATH, rendered, 0o644)
        # WHEN TO ?
        # host.service_reload('opendkim')
        # # Ensure service is running.
        # host.service_start('opendkim')
        self.unit.status = ops.ActiveStatus()


# pylint: disable=too-few-public-methods,unused-argument
class OpenDKIMConfig:
    """TODO."""

    @classmethod
    def from_charm(cls, charm: OpenDKIMCharm) -> "OpenDKIMConfig":
        """TODO.

        Args:
          charm: TODO

        Return:
          TODO.
        """
        return cls()


def render_file(path: Path, content: str, mode: int) -> None:
    """Write a content rendered from a template to a file.

    Args:
        path: Path object to the file.
        content: the data to be written to the file.
        mode: access permission mask applied to the
            file using chmod (e.g. 0o640).
    """
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)


if __name__ == "__main__":  # pragma: nocover
    ops.main(OpenDKIMCharm)
