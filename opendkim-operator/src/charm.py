#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""OpenDKIM charm."""

import logging
import subprocess  # nosec B404
import time
import typing
from pathlib import Path

import ops
from charmlibs import snap
from charms.grafana_agent.v0.cos_agent import COSAgentProvider
from jinja2 import Environment, FileSystemLoader, select_autoescape

import utils
from state import OPENDKIM_MILTER_PORT, InvalidCharmConfigError, OpenDKIMConfig

logger = logging.getLogger(__name__)

OPENDKIM_SNAP_NAME = "opendkim"
OPENDKIM_CONFIG_TEMPLATE = Path("opendkim.conf.j2")
OPENDKIM_CONFIG_PATH = Path("/var/snap/opendkim/current/etc/opendkim.conf")
OPENDKIM_KEYS_PATH = Path("/var/snap/opendkim/current/etc/dkimkeys")
OPENDKIM_USER = "opendkim"

LOG_ROTATE_SYSLOG = Path("/etc/logrotate.d/rsyslog")
LOG_RETENTION_DAYS = 120


MILTER_RELATION_NAME = "milter"

COS_DIRPATH = Path("cos")

TELEGRAF_CONF_SRC = COS_DIRPATH / "telegraf/telegraf.conf"
TELEGRAF_CONF_DST = Path("/var/snap/telegraf/current/telegraf.conf")


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

        self._grafana_agent = COSAgentProvider(
            self,
            metrics_endpoints=[
                {"path": "/metrics", "port": 9103},
            ],
            dashboard_dirs=[COS_DIRPATH / "grafana_dashboards"],
            metrics_rules_dir=COS_DIRPATH / "prometheus_alert_rules",
            logs_rules_dir=COS_DIRPATH / "loki_alert_rules",
        )

    def _install(self, _: ops.EventBase) -> None:
        """Install opendkim snap and telegraf snap."""
        self.unit.status = ops.MaintenanceStatus("installing opendkim")
        opendkim_installed = self._install_opendkim()

        self._install_telegraf()

        rotate_content = utils.update_logrotate_conf(
            str(LOG_ROTATE_SYSLOG), frequency="daily", retention=LOG_RETENTION_DAYS
        )
        utils.write_file(LOG_ROTATE_SYSLOG, rotate_content, 0o644, user="root")

        if not opendkim_installed:
            return
        self.unit.status = ops.WaitingStatus()

    def _install_opendkim(self) -> bool:
        """Install opendkim from the snap store.

        Returns:
            True if the snap was installed successfully, False otherwise.
        """
        try:
            snap_installed = (
                subprocess.run(  # nosec
                    ["snap", "list", OPENDKIM_SNAP_NAME],
                    timeout=100,
                    check=False,
                ).returncode
                == 0
            )

            if not snap_installed:
                subprocess.run(  # nosec
                    ["snap", "install", OPENDKIM_SNAP_NAME, "--devmode"],
                    timeout=300,
                    check=True,
                )
        except subprocess.CalledProcessError:
            logger.exception("An exception occurred when installing OpenDKIM snap")
            self.unit.status = ops.BlockedStatus("Unable to install OpenDKIM snap")
            return False
        return True

    def _install_telegraf(self) -> None:
        """Install telegraf."""
        try:
            telegraf_snap = typing.cast(snap.Snap, snap.add(["telegraf"]))
            TELEGRAF_CONF_DST.touch()
            utils.write_file(TELEGRAF_CONF_DST, TELEGRAF_CONF_SRC.read_text(), 0o644, user="root")
            telegraf_snap.restart()
        except snap.SnapError:
            logger.exception("An exception occurred when installing Telegraf snap")

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

        should_restart = self._write_config_files(config)

        if not self._validate_keytable_keys(config):
            return

        if not self._restart_if_needed(should_restart):
            return

        try:
            validate_opendkim()
        except InvalidCharmConfigError as exc:
            logger.exception("Invalid opendkim configuration")
            self.unit.status = ops.BlockedStatus(str(exc))
            return
        self.unit.status = ops.ActiveStatus()

    def _write_config_files(self, config: OpenDKIMConfig) -> bool:
        """Write all configuration files, comparing content to avoid unnecessary writes.

        Args:
            config: The validated OpenDKIM configuration.

        Returns:
            True if any file was changed and a restart is needed.
        """
        should_restart = False

        for keyname, keyvalue in config.private_keys.items():
            keyfile = OPENDKIM_KEYS_PATH / f"{keyname}.private"
            if keyvalue != utils.read_text(keyfile):
                utils.write_file(keyfile, keyvalue, 0o600, user=OPENDKIM_USER)
                should_restart = True

        signingtable_path = OPENDKIM_KEYS_PATH / config.signingtable_path.name
        signingtable = "\n".join(" ".join(row) for row in config.signingtable)
        if signingtable != utils.read_text(signingtable_path):
            utils.write_file(signingtable_path, signingtable, 0o644, user=OPENDKIM_USER)
            should_restart = True

        keytable_path = OPENDKIM_KEYS_PATH / config.keytable_path.name
        keytable = "\n".join(" ".join(row) for row in config.keytable)
        if keytable != utils.read_text(keytable_path):
            utils.write_file(keytable_path, keytable, 0o644, user=OPENDKIM_USER)
            should_restart = True

        rendered = self._render_opendkim_conf(config)
        if rendered != utils.read_text(OPENDKIM_CONFIG_PATH):
            utils.write_file(OPENDKIM_CONFIG_PATH, rendered, 0o644, user=OPENDKIM_USER)
            should_restart = True

        return should_restart

    @staticmethod
    def _render_opendkim_conf(config: OpenDKIMConfig) -> str:
        """Render the opendkim.conf template.

        Args:
            config: The validated OpenDKIM configuration.

        Returns:
            The rendered configuration string.
        """
        context = config.model_dump()
        env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=select_autoescape(),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        template = env.get_template(str(OPENDKIM_CONFIG_TEMPLATE))
        return template.render(context)

    def _validate_keytable_keys(self, config: OpenDKIMConfig) -> bool:
        """Validate that all key files referenced in the keytable exist.

        Args:
            config: The validated OpenDKIM configuration.

        Returns:
            True if all referenced key files exist.
        """
        for row in config.keytable:
            try:
                key_path = Path(row[1].split(":", maxsplit=2)[2])
                if key_path.is_absolute() and key_path.parts[:3] == ("/", "etc", "dkimkeys"):
                    key_path = OPENDKIM_KEYS_PATH / key_path.name
            except IndexError:
                logger.exception("Invalid keytable row value: %s", row[1])
                self.unit.status = ops.BlockedStatus("Wrong opendkim configuration. See logs")
                return False

            if not key_path.exists():
                logger.error("Referenced key file does not exist: %s", key_path)
                self.unit.status = ops.BlockedStatus("Wrong opendkim configuration. See logs")
                return False
        return True

    def _restart_if_needed(self, should_restart: bool) -> bool:
        """Restart the opendkim snap daemon if needed and wait for readiness.

        Args:
            should_restart: Whether a restart is needed.

        Returns:
            True if no restart was needed or restart succeeded.
        """
        if not should_restart:
            return True
        try:
            logger.info("Restart opendkim snap service")
            subprocess.run(  # nosec
                ["snap", "restart", "opendkim.daemon"],
                timeout=100,
                check=True,
            )
            if not self._wait_for_milter_ready():
                logger.error("OpenDKIM milter endpoint did not become ready")
                self.unit.status = ops.BlockedStatus("Unable to restart OpenDKIM service")
                return False
        except (subprocess.CalledProcessError, TimeoutError):
            logger.exception("Error restarting opendkim daemon")
            self.unit.status = ops.BlockedStatus("Unable to restart OpenDKIM service")
            return False
        return True

    def _wait_for_milter_ready(self, timeout: int = 30) -> bool:
        """Wait until the OpenDKIM milter endpoint is listening on its TCP port.

        Args:
            timeout: Maximum number of seconds to wait.

        Returns:
            True if the milter endpoint became ready within the timeout.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = subprocess.run(  # nosec
                ["ss", "-ltn", f"sport = :{OPENDKIM_MILTER_PORT}"],
                timeout=10,
                check=False,
                capture_output=True,
                text=True,
            )
            if "LISTEN" in result.stdout:
                return True
            time.sleep(1)
        return False


def validate_opendkim() -> None:
    """Validate the opendkim configuration using opendkim check mode.

    Raises:
       InvalidCharmConfigError: Raised if the check failed.
    """
    try:
        subprocess.run(  # nosec
            ["opendkim", "-n", "-x", str(OPENDKIM_CONFIG_PATH)],
            timeout=100,
            check=True,
        )
    except (subprocess.CalledProcessError, TimeoutError) as exc:
        logger.exception("Error validating with opendkim -n")
        raise InvalidCharmConfigError("Wrong opendkim configuration. See logs") from exc


if __name__ == "__main__":  # pragma: nocover
    ops.main(OpenDKIMCharm)
