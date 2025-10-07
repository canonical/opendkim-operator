# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests."""

import getpass
import json
import os
import tempfile
import typing
from pathlib import Path
from secrets import token_hex
from unittest.mock import ANY, MagicMock

import ops
import ops.testing
import pytest

import utils
from charm import OpenDKIMCharm


def test_install(monkeypatch):
    """
    arrange: Mock apt.add_package and prepare a trivial context and state.
    act: Run install hook.
    assert: Add package was called and the unit is active.
    """
    add_package_mock = MagicMock()
    monkeypatch.setattr("charm.apt.add_package", add_package_mock)

    write_file_mock = MagicMock()
    monkeypatch.setattr("utils.write_file", write_file_mock)
    update_logrotate_conf_mock = MagicMock()
    monkeypatch.setattr("utils.update_logrotate_conf", update_logrotate_conf_mock)

    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )
    base_state: dict[str, str] = {}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.install(), state)
    write_file_mock.assert_called_with(Path("/etc/logrotate.d/rsyslog"), ANY, 0o644, user="root")
    assert len(out.opened_ports) == 1
    assert list(out.opened_ports)[0].port == 8892
    assert out.unit_status.name == ops.testing.WaitingStatus.name


@pytest.mark.parametrize(
    "signingtable,keytable,private_keys,error_messages",
    [
        pytest.param(
            None,
            None,
            None,
            ["empty signingtable", "empty keytable", "empty private-keys"],
            id="No config options",
        ),
        pytest.param(
            "",
            "",
            None,
            ["empty signingtable", "empty keytable", "empty private-keys"],
            id="Empty config options",
        ),
        pytest.param(
            "*wrongyaml",
            "*wrongyaml",
            {},
            ["wrong signingtable", "wrong keytable"],
            id="Wrong YAML formats",
        ),
        pytest.param(
            "signingtable",
            "keytable",
            {},
            ["wrong", " signingtable,keytable."],
            id="Wrong YAML config options",
        ),
        pytest.param(
            json.dumps([["valid", "valid"]]),
            "keytable",
            {},
            ["wrong", " keytable."],
            id="Wrong YAML config options",
        ),
        pytest.param(
            "signingtable",
            json.dumps([["*@example.com", "selector._domainkey.example.com"]]),
            {},
            ["wrong", " signingtable."],
            id="Wrong YAML config options",
        ),
    ],
)
def test_invalid_config(signingtable, keytable, private_keys, error_messages):
    """
    arrange: Prepare a configuration options and key secrets that is invalid.
    act: Send hook on config_changed.
    assert: Test that the charm is blocked and the correct message is shown..
    """
    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )

    config: dict[str, str] = {}
    secrets: ops.testing.Secret = {}
    if signingtable is not None:
        config["signingtable"] = signingtable
    if keytable is not None:
        config["keytable"] = keytable
    if private_keys is not None:
        secret_id = token_hex(20)[:20]
        config["private-keys"] = f"secret:{secret_id}"
        secrets = {ops.testing.Secret(id=f"secret:{secret_id}", tracked_content=private_keys)}
    base_state: dict[str, typing.Any] = {"config": config, "secrets": secrets}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)
    assert out.unit_status.name == ops.testing.BlockedStatus.name
    for error_message in error_messages:
        assert error_message in out.unit_status.message


def test_missing_milter_relation():
    """
    arrange: Prepare a valid configuration and apply it.
    act: Send hook on config_changed.
    assert: The charmed is blocked because there is no valid milter relation.
    """
    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )

    secret_id = token_hex(20)[:20]
    secrets = {
        ops.testing.Secret(id=f"secret:{secret_id}", tracked_content={"thekey": "PRIVATEKEY"})
    }
    config = {
        "signingtable": json.dumps([["*@example.com", "selector._domainkey.example.com"]]),
        "keytable": json.dumps(
            [
                [
                    "selector._domainkey.example.com",
                    "example.com:selector:/etc/dkimkeys/thekey.private",
                ]
            ]
        ),
        "private-keys": f"secret:{secret_id}",
    }
    base_state: dict[str, typing.Any] = {"config": config, "secrets": secrets}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)
    assert out.unit_status.name == ops.testing.BlockedStatus.name
    assert "milter" in out.unit_status.message


@pytest.mark.parametrize(
    "initial_opendkin_conf,restart_expected",
    [
        pytest.param("", True, id="Initial opendkim.conf empty, restart service"),
        pytest.param(
            (Path(__file__).parent / "files/base_opendkim.conf").read_text(),
            False,
            id="opendkim.conf not changed, do not restart service",
        ),
    ],
)
def test_correct_config(initial_opendkin_conf, restart_expected, base_state, monkeypatch):
    """
    arrange: Mock all external accesses and prepare a valid configuration with a milter relation.
    act: Run hook config_changed.
    assert: The charm is active. All the files were written and the service is restarted/reloaded.
    """
    monkeypatch.setattr("utils.read_text", MagicMock(return_value=initial_opendkin_conf))
    monkeypatch.setattr("charm.validate_opendkim", MagicMock(return_value=None))
    systemd_reload_mock = MagicMock()
    monkeypatch.setattr("charm.systemd.service_reload", systemd_reload_mock)
    systemd_restart_mock = MagicMock()
    monkeypatch.setattr("charm.systemd.service_restart", systemd_restart_mock)
    write_file_mock = MagicMock()
    monkeypatch.setattr("utils.write_file", write_file_mock)

    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )

    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)

    assert out.unit_status.name == ops.testing.ActiveStatus.name
    assert list(out.relations)[0].local_unit_data["port"] == "8892"

    systemd_reload_mock.assert_called_with("opendkim")
    if restart_expected:
        assert write_file_mock.call_count == 5
        systemd_restart_mock.assert_called_with("opendkim")
        write_file_mock.assert_any_call(
            Path("/etc/opendkim.conf"),
            (Path(__file__).parent / "files/base_opendkim.conf").read_text(),
            0o644,
            user="opendkim",
        )
    else:
        assert write_file_mock.call_count == 4
        systemd_restart_mock.assert_not_called()
    write_file_mock.assert_any_call(
        Path("/etc/dkimkeys/key1.private"), "PRIVATEKEY1", 0o600, user="opendkim"
    )
    write_file_mock.assert_any_call(
        Path("/etc/dkimkeys/key2.private"), "PRIVATEKEY2", 0o600, user="opendkim"
    )
    write_file_mock.assert_any_call(
        Path("/etc/dkimkeys/signingtable"),
        (Path(__file__).parent / "files/base_signingtable").read_text(),
        0o644,
        user="opendkim",
    )
    write_file_mock.assert_any_call(
        Path("/etc/dkimkeys/keytable"),
        (Path(__file__).parent / "files/base_keytable").read_text(),
        0o644,
        user="opendkim",
    )


def test_write_file():
    """
    arrange: Prepare some text and a directory.
    act: Call write_file.
    assert: The file is rendered with the correct content.
    """
    user = getpass.getuser()
    with tempfile.TemporaryDirectory() as tmpdir:
        content = "any text"
        path = Path(tmpdir) / "onefile.txt"
        utils.write_file(path, content, 0o666, user=user)
        st = os.stat(str(path))
        assert oct(st.st_mode) == "0o100666"
        assert path.read_text() == content
