#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""OpenDKIM charm."""

import logging
import os
import pwd
import subprocess  # nosec B404
import typing
from pathlib import Path

import ops
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from jinja2 import Environment, FileSystemLoader, select_autoescape

import utils
from state import OPENDKIM_MILTER_PORT, InvalidCharmConfigError, OpenDKIMConfig

logger = logging.getLogger(__name__)

OPENDKIM_PACKAGE_NAME = "opendkim"
OPENDKIM_CONFIG_TEMPLATE = Path("opendkim.conf.j2")
OPENDKIM_CONFIG_PATH = Path("/etc/opendkim.conf")
OPENDKIM_KEYS_PATH = Path("/etc/dkimkeys")
OPENDKIM_USER = "opendkim"

LOG_ROTATE_SYSLOG = Path("/etc/logrotate.d/rsyslog")
LOG_RETENTION_DAYS = 120


MILTER_RELATION_NAME = "milter"


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
        self.framework.observe(self.on.secret_changed, self._reconcile)
        self.framework.observe(self.on[MILTER_RELATION_NAME].relation_changed, self._reconcile)
        self.framework.observe(self.on[MILTER_RELATION_NAME].relation_departed, self._reconcile)
        self.unit.open_port("tcp", OPENDKIM_MILTER_PORT)

    def _install(self, _: ops.EventBase) -> None:
        """Install opendkim package."""
        self.unit.status = ops.MaintenanceStatus("installing opendkim")
        apt.add_package(package_names=OPENDKIM_PACKAGE_NAME, update_cache=True)
        rotate_content = utils.update_logrotate_conf(
            str(LOG_ROTATE_SYSLOG), frequency="daily", retention=LOG_RETENTION_DAYS
        )
        render_file(LOG_ROTATE_SYSLOG, rotate_content, 0o644, user="root")
        self.unit.status = ops.WaitingStatus()

    def _reconcile(self, _: ops.EventBase) -> None:
        """Configure the workload with the provided configuration for the charm."""
        try:
            config = OpenDKIMConfig.from_charm(self.config, self.model)
        except InvalidCharmConfigError as exc:
            logger.exception("Error validating the charm configuration.")
            self.unit.status = ops.BlockedStatus(str(exc))
            return

        milter_relations = self.model.relations.get(MILTER_RELATION_NAME)
        if not milter_relations:
            self.unit.status = ops.BlockedStatus("Missing milter relations")
            return
        for milter_relation in milter_relations:
            milter_relation.data[self.model.unit]["port"] = str(OPENDKIM_MILTER_PORT)

        for keyname, keyvalue in config.private_keys.items():
            keyfile = OPENDKIM_KEYS_PATH / f"{keyname}.private"
            render_file(keyfile, keyvalue, 0o600)

        signingtable = "\n".join(" ".join(row) for row in config.signingtable)
        render_file(config.signingtable_path, signingtable, 0o644)

        keytable = "\n".join(" ".join(row) for row in config.keytable)
        render_file(config.keytable_path, keytable, 0o644)

        context = config.model_dump()
        env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=select_autoescape(),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(str(OPENDKIM_CONFIG_TEMPLATE))
        rendered = template.render(context)

        previous_rendered = read_text(OPENDKIM_CONFIG_PATH)
        if rendered != previous_rendered:
            render_file(OPENDKIM_CONFIG_PATH, rendered, 0o644)
            logger.info("Restart opendkim")
            systemd.service_restart("opendkim")

        logger.info("Reload opendkim")
        systemd.service_reload("opendkim")

        try:
            validate_opendkim()
        except InvalidCharmConfigError as exc:
            logger.exception("Invalid opendkim configuration")
            self.unit.status = ops.BlockedStatus(str(exc))
            return
        self.unit.status = ops.ActiveStatus()


def validate_opendkim() -> None:
    """Validate the opendkim configuration using the binary opendkim-testkey.

    Raises:
       InvalidCharmConfigError: Raised if the check failed.
    """
    try:
        subprocess.run(  # nosec
            ["opendkim-testkey", "-x", OPENDKIM_CONFIG_PATH, "-vv"], timeout=100, check=True
        )
    except (subprocess.CalledProcessError, TimeoutError) as exc:
        logger.exception("Error validating with opendkim-testkey")
        raise InvalidCharmConfigError("Wrong opendkim configuration. See logs") from exc


def read_text(path: Path) -> str:
    """Return text from a file.

    Args:
        path: Path of the file ro read.

    Returns: String content of the file.
    """
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def render_file(path: Path, content: str, mode: int, user: str = OPENDKIM_USER) -> None:
    """Write a content rendered from a template to a file.

    Args:
        path: Path object to the file.
        content: the data to be written to the file.
        mode: access permission mask applied to the
            file using chmod (e.g. 0o640).
        user: The user that will own the file.
    """
    path.write_text(content, encoding="utf-8")
    os.chmod(path, mode)
    u = pwd.getpwnam(user)
    os.chown(path, uid=u.pw_uid, gid=u.pw_gid)


if __name__ == "__main__":  # pragma: nocover
    ops.main(OpenDKIMCharm)
