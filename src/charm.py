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
from typing import Optional, cast

import ops
import yaml
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ValidationError, computed_field

import utils

logger = logging.getLogger(__name__)

OPENDKIM_PACKAGE_NAME = "opendkim"
OPENDKIM_MILTER_PORT = 8892
OPENDKIM_CONFIG_TEMPLATE = Path("opendkim.conf.j2")
OPENDKIM_CONFIG_PATH = Path("/etc/opendkim.conf")
OPENDKIM_KEYS_PATH = Path("/etc/dkimkeys")
OPENDKIM_SIGNINGTABLE_PATH = OPENDKIM_KEYS_PATH / "signingtable"
OPENDKIM_KEYTABLE_PATH = OPENDKIM_KEYS_PATH / "keytable"
OPENDKIM_USER = "opendkim"

LOG_ROTATE_SYSLOG = Path("/etc/logrotate.d/rsyslog")
LOG_RETENTION_DAYS = 120


MILTER_RELATION_NAME = "milter"

# https://datatracker.ietf.org/doc/html/rfc6376#section-5.4
DEFAULT_SIGN_HEADERS = (
    "From,Reply-To,Subject,Date,To,Cc"
    ",Resent-From,Resent-Date,Resent-To,Resent-Cc"
    ",In-Reply-To,References"
    ",MIME-Version,Message-ID,Content-Type"
)


class InvalidCharmConfigError(Exception):
    """Exception raised when the parsed charm config is invalid."""


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
        self.framework.observe(self.on[MILTER_RELATION_NAME].relation_broken, self._reconcile)
        self.framework.observe(self.on[MILTER_RELATION_NAME].relation_joined, self._reconcile)
        self.unit.open_port("tcp", OPENDKIM_MILTER_PORT)

    def _install(self, _: ops.EventBase) -> None:
        """Install opendkim package."""
        self.unit.status = ops.MaintenanceStatus("installing opendkim")
        apt.add_package(package_names=OPENDKIM_PACKAGE_NAME, update_cache=True)
        rotate_content = utils.update_logrotate_conf(
            str(LOG_ROTATE_SYSLOG), frequency="daily", retention=LOG_RETENTION_DAYS
        )
        render_file(LOG_ROTATE_SYSLOG, rotate_content, 0o644, user="root")
        self.unit.status = ops.ActiveStatus()

    def _reconcile(self, _: ops.EventBase) -> None:
        """Configure the workload with the provided configuration for the charm."""
        try:
            config = OpenDKIMConfig.from_charm(self)
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

        context = config.model_dump()
        env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=select_autoescape(),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        for keyname, keyvalue in config.private_keys.items():
            keyfile = OPENDKIM_KEYS_PATH / f"{keyname}.private"
            render_file(keyfile, keyvalue, 0o600)

        signingtable = "\n".join(" ".join(row) for row in config.signingtable)
        render_file(OPENDKIM_SIGNINGTABLE_PATH, signingtable, 0o644)

        keytable = "\n".join(" ".join(row) for row in config.keytable)
        render_file(OPENDKIM_KEYTABLE_PATH, keytable, 0o644)

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
        except ValueError as exc:
            logger.exception("Invalid opendkim configuration")
            self.unit.status = ops.BlockedStatus(str(exc))
            return
        self.unit.status = ops.ActiveStatus()


class OpenDKIMConfig(BaseModel):
    """OpenDKIM configuration.

    Attrs:
        canonicalization: DKIM canonicalization scheme.
        socket: Socket where OpenDKIM listens.
        signheaders: Header Fields to Sign.
        internalhosts: Set internal hosts whose mail should be signed.
        mode: OpenDKIM model.
        signingtable: OpenDKIM SigningTable as a pair or values per line.
        keytable: OpenDKIM  as a pair or values per line. Uses refile.
        private_keys: Dict with the filename without extension as key and the private key as value.
        signing_mode: True if in signing model.
        signingtable_path: Path to the signingtable file.
        keytable_path:  to the keytable file.
    """

    canonicalization: str = "relaxed/relaxed"
    socket: str = f"inet:{OPENDKIM_MILTER_PORT}"
    signheaders: str = DEFAULT_SIGN_HEADERS
    internalhosts: str = "0.0.0.0/0"
    mode: str = "sv"
    signingtable: list[typing.Tuple[str, str]]
    keytable: list[list[str]]
    private_keys: dict[str, str]
    signingtable_path: Path = OPENDKIM_SIGNINGTABLE_PATH
    keytable_path: Path = OPENDKIM_KEYTABLE_PATH

    @computed_field  # type: ignore[misc]
    @property
    def signing_mode(self) -> bool:
        """Return True if the charm works in signing mode."""
        return "s" in self.mode

    @classmethod
    def from_charm(cls, charm: OpenDKIMCharm) -> typing.Self:
        """Return a new OpenDKIM configuration from the OpenDKIMCharm.

        Args:
          charm: OpenDKIMCharm.

        Raises:
          InvalidCharmConfigError: When the configuration from the charm is not valid.

        Return:
          Configuration created from the charm.
        """
        errors = []
        try:
            signingtable = _parse_yaml_config_option(charm.config, "signingtable")
        except ValueError as e:
            errors.append(str(e))

        try:
            keytable = _parse_yaml_config_option(charm.config, "keytable")
        except ValueError as e:
            errors.append(str(e))

        private_keys_secret_id = cast(Optional[str], charm.config.get("private-keys"))
        if not private_keys_secret_id:
            errors.append("empty private-keys configuration")

        if errors:
            raise InvalidCharmConfigError(" - ".join(errors))

        private_keys_secret_id = cast(str, private_keys_secret_id).replace("secret:", "")
        secret = charm.model.get_secret(id=private_keys_secret_id)

        private_keys = secret.get_content(refresh=True)
        try:
            return cls(signingtable=signingtable, keytable=keytable, private_keys=private_keys)
        except ValidationError as exc:
            logger.error(str(exc))
            error_field_str = ",".join(f"{field}" for field in get_invalid_config_fields(exc))
            raise InvalidCharmConfigError(f"wrong config options: {error_field_str}.") from exc


def _parse_yaml_config_option(config_data: ops.model.ConfigData, config_name: str) -> typing.Any:
    """Return the parsed YAML from a configuration option."""
    config_value = cast(Optional[str], config_data.get(config_name))
    if not config_value:
        raise ValueError(f"empty {config_name} configuration")
    try:
        return yaml.safe_load(config_value)
    except yaml.YAMLError as exc:
        logger.exception("Failed loading %s", config_name)
        raise ValueError(f"wrong {config_name} format") from exc


def validate_opendkim() -> None:
    """Validate the opendkim configuration using the binary opendkim-testkey.

    Raises:
       ValueError: Raised if the check failed.
    """
    try:
        subprocess.run(
            ["opendkim-testkey", "-x", OPENDKIM_CONFIG_PATH, "-vv"], timeout=100, check=True
        )
    except (subprocess.CalledProcessError, TimeoutError) as exc:
        logger.exception("Error validating with opendkim-testkey")
        raise ValueError("Wrong opendkim configuration. See logs") from exc


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


def get_invalid_config_fields(exc: ValidationError) -> list[str]:
    """Return a list on invalid config from pydantic validation error.

    Args:
        exc: The validation error exception.

    Returns:
        str: list of fields that failed validation.
    """
    logger.info(exc.errors())
    error_fields = ["-".join([str(i) for i in error["loc"]]) for error in exc.errors()]
    return error_fields


if __name__ == "__main__":  # pragma: nocover
    ops.main(OpenDKIMCharm)
