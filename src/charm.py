#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/#build-a-charm

"""OpenDKIM charm."""

import logging
import typing

import ops
from charms.operator_libs_linux.v0 import apt

logger = logging.getLogger(__name__)

OPENDKIM_PACKAGE_NAME = "opendkim"
OPENDKIM_MILTER_PORT = 8892


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
        self.unit.open_port("tcp", OPENDKIM_MILTER_PORT)

    def _install(self, _: ops.EventBase) -> None:
        """Install opendkim package."""
        self.unit.status = ops.MaintenanceStatus("installing opendkim")
        apt.add_package(package_names=OPENDKIM_PACKAGE_NAME, update_cache=True)
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    ops.main(OpenDKIMCharm)
