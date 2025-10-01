# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests."""

import os
import tempfile
import typing
from pathlib import Path
from secrets import token_hex
from unittest.mock import MagicMock

import ops
import ops.testing
import pytest

from charm import OpenDKIMCharm, render_file


def test_install(monkeypatch):
    """
    arrange: Mock apt.add_package and prepare a trivial context and state.
    act: Run install hook.
    assert: Add package was called and the unit is active.
    """
    add_package_mock = MagicMock()
    monkeypatch.setattr("charm.apt.add_package", add_package_mock)

    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )
    base_state: dict[str, str] = {}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.install(), state)
    add_package_mock.assert_called()
    assert len(out.opened_ports) == 1
    assert list(out.opened_ports)[0].port == 8892
    assert out.unit_status.name == ops.testing.ActiveStatus.name


@pytest.mark.parametrize(
    "signingtable,keytable,private_keys,error_messages",
    [
        pytest.param(None, None, None, ["empty signingtable"], id="No config options"),
        pytest.param("", "", {}, ["empty signingtable"], id="Empty config options"),
        pytest.param(
            "XX",
            "XX",
            {},
            ["signingtable", "keytable"],
            id="test3",
        ),
        pytest.param("*@", "", {}, ["format"], id="Wrong YAML"),
    ],
)
def test_blocked_charm(signingtable, keytable, private_keys, error_messages):
    """
    arrange: TODO.
    act: TODO.
    assert: TODO.
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
        secrets = {ops.testing.Secret(id=secret_id, tracked_content=private_keys)}
    base_state: dict[str, typing.Any] = {"config": config, "secrets": secrets}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)
    assert out.unit_status.name == ops.testing.BlockedStatus.name
    for error_message in error_messages:
        assert error_message in out.unit_status.message


# JAVI
# def test_relation_changed(monkeypatch): ??


def test_basic_config(monkeypatch):
    """
    arrange: TODO.
    act: TODO.
    assert: TODO.
    """
    systemd_reload_mock = MagicMock()
    monkeypatch.setattr("charm.systemd.service_reload", systemd_reload_mock)

    render_file_mock = MagicMock()
    monkeypatch.setattr("charm.render_file", render_file_mock)

    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )

    keyname = "example.com-selector"
    keytable = f"""
[[selector._domainkey.example.com, example.com:selector:/etc/dkimkeys/{keyname}.private]]
    """
    signingtable = '[["*@example.com", "selector._domainkey.example.com"]]'
    private_keys = {keyname: "PRIVATEKEY"}
    secret_id = token_hex(20)[:20]

    milter_relation = ops.testing.Relation(
        id=1,
        endpoint="milter",
        interface="milter",
        remote_app_data={},
        remote_app_name="smtp-relay",
    )
    base_state: dict[str, typing.Any] = {
        "config": {
            "keytable": keytable,
            "signingtable": signingtable,
            "private-keys": f"secret:{secret_id}",
        },
        "secrets": {ops.testing.Secret(id=secret_id, tracked_content=private_keys)},
        "relations": [milter_relation],
    }
    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)

    assert out.unit_status.name == ops.testing.ActiveStatus.name

    # JAVI maybe test with two relations? is this what we want?
    assert list(out.relations)[0].local_unit_data["port"] == "8892"
    systemd_reload_mock.assert_called_with("opendkim")
    # There must be 4 calls to render_file.
    assert render_file_mock.call_count == 4
    expected_opendkim_conf = (Path(__file__).parent / "files/opendkim.conf").read_text()
    render_file_mock.assert_any_call(Path(f"/etc/dkimkeys/{keyname}.private"), "PRIVATEKEY", 0o600)
    render_file_mock.assert_any_call(
        Path("/etc/dkimkeys/signingtable"), "*@example.com selector._domainkey.example.com", 0o644
    )
    render_file_mock.assert_any_call(
        Path("/etc/dkimkeys/keytable"),
        "selector._domainkey.example.com"
        " example.com:selector:/etc/dkimkeys/example.com-selector.private",
        0o644,
    )
    render_file_mock.assert_any_call(Path("/etc/opendkim.conf"), expected_opendkim_conf, 0o644)


def test_render_file():
    """
    arrange: TODO.
    act: TODO.
    assert: TODO.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        content = "any text"
        path = Path(tmpdir) / "onefile.txt"
        render_file(path, content, 0o666)
        st = os.stat(str(path))
        assert oct(st.st_mode) == "0o100666"
        assert path.read_text() == content
