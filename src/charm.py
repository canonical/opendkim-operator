#!/usr/bin/env python3

# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

# Learn more at: https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/#build-a-charm

"""OpenDKIM charm."""

import logging
import os
import typing
from pathlib import Path
from typing import Optional, cast

import ops
import yaml
from charms.operator_libs_linux.v0 import apt
from charms.operator_libs_linux.v1 import systemd
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, ValidationError, computed_field

logger = logging.getLogger(__name__)

OPENDKIM_PACKAGE_NAME = "opendkim"
OPENDKIM_MILTER_PORT = 8892
OPENDKIM_CONFIG_TEMPLATE = Path("opendkim.conf.j2")
OPENDKIM_CONFIG_PATH = Path("/etc/opendkim.conf")
OPENDKIM_CONFIG_PATH = Path("/etc/opendkim.conf")
OPENDKIM_KEYS_PATH = Path("/etc/dkimkeys")
OPENDKIM_SIGNINGTABLE_PATH = OPENDKIM_KEYS_PATH / "signingtable"
OPENDKIM_KEYTABLE_PATH = OPENDKIM_KEYS_PATH / "keytable"

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
        # JAVI log rotation?
        self.unit.status = ops.ActiveStatus()

    def _reconcile(self, _: ops.EventBase) -> None:
        """TODO."""
        try:
            config = OpenDKIMConfig.from_charm(self)
        except InvalidCharmConfigError as exc:
            logger.exception("Error validating the charm configuration.")
            self.unit.status = ops.BlockedStatus(str(exc))
            return

        # Jinja2 context
        context = config.model_dump()
        logger.info("Javi context %s", context)
        env = Environment(
            loader=FileSystemLoader("templates"),
            autoescape=select_autoescape(),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # JAVI validate here anything else?
        milter_relations = self.model.relations.get(MILTER_RELATION_NAME)
        if not milter_relations:
            self.unit.status = ops.WaitingStatus("waiting for milter relations")
            return
        for milter_relation in milter_relations:
            milter_relation.data[self.model.unit]["port"] = str(OPENDKIM_MILTER_PORT)

        # At this point, render all required files.
        for keyname, keyvalue in config.private_keys.items():
            keyfile = OPENDKIM_KEYS_PATH / f"{keyname}.private"
            render_file(keyfile, keyvalue, 0o600)

        signingtable = "\n".join(" ".join(row) for row in config.signingtable)
        render_file(OPENDKIM_SIGNINGTABLE_PATH, signingtable, 0o644)

        keytable = "\n".join(" ".join(row) for row in config.keytable)
        render_file(OPENDKIM_KEYTABLE_PATH, keytable, 0o644)

        template = env.get_template(str(OPENDKIM_CONFIG_TEMPLATE))
        rendered = template.render(context)
        render_file(OPENDKIM_CONFIG_PATH, rendered, 0o644)
        systemd.service_reload("opendkim")

        self.unit.status = ops.ActiveStatus()


# pylint: disable=too-few-public-methods,unused-argument
class OpenDKIMConfig(BaseModel):
    """TODO.

    Attrs:
        canonicalization: TODO
        socket: TODO
        signheaders: TODO
        mode: TODO
        internalhosts: TODO
        signingtable: TODO
        keytable: TODO
        private_keys: TODO
        signing_mode: TODO
        signingtable_path: TODO
        keytable_path: TODO
    """

    canonicalization: str = "relaxed/relaxed"
    socket: str = f"inet:{OPENDKIM_MILTER_PORT}"
    signheaders: str = DEFAULT_SIGN_HEADERS
    mode: str = "sv"
    internalhosts: str = "0.0.0.0/0"
    signingtable: list[typing.Tuple[str, str]]
    keytable: list[list[str]]
    private_keys: dict[str, str]
    signingtable_path: Path = OPENDKIM_SIGNINGTABLE_PATH
    keytable_path: Path = OPENDKIM_KEYTABLE_PATH

    @computed_field  # type: ignore[misc]
    @property
    def signing_mode(self) -> bool:
        """TODO."""
        return "s" in self.mode

    @classmethod
    def from_charm(cls, charm: OpenDKIMCharm) -> "OpenDKIMConfig":
        """TODO.

        Args:
          charm: TODO

        Raises:
          InvalidCharmConfigError: TODO

        Return:
          TODO.
        """
        signingtable_option = cast(Optional[str], charm.config.get("signingtable"))
        if not signingtable_option:
            raise InvalidCharmConfigError("empty signingtable configuration option")
        try:
            signingtable = yaml.safe_load(signingtable_option)
        except yaml.YAMLError as exc:
            raise InvalidCharmConfigError("Wrong signingtable format") from exc

        keytable_option = cast(Optional[str], charm.config.get("keytable"))
        if not keytable_option:
            raise InvalidCharmConfigError("empty keytable configuration option")
        try:
            keytable = yaml.safe_load(keytable_option)
        except yaml.YAMLError as exc:
            raise InvalidCharmConfigError("Wrong keytable format") from exc

        private_keys_secret_id = cast(Optional[str], charm.config.get("private-keys"))
        if private_keys_secret_id is None:
            raise InvalidCharmConfigError("empty private_keys configuration option")
        private_keys_secret_id = private_keys_secret_id.replace("secret:", "")
        secret = charm.model.get_secret(id=private_keys_secret_id)

        # JAVI. Does this refresh has any implication in secret updating/rotation?
        private_keys = typing.cast(dict[str, str], secret.get_content(refresh=True))
        try:
            return cls(signingtable=signingtable, keytable=keytable, private_keys=private_keys)
        except ValidationError as exc:
            logger.error(str(exc))
            error_field_str = ",".join(f"{field}" for field in get_invalid_config_fields(exc))
            raise InvalidCharmConfigError(f"Wrong config options: {error_field_str}") from exc


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
