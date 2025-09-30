# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests."""

import os
import stat
import tempfile
from pathlib import Path
from unittest.mock import ANY, MagicMock

import ops
import ops.testing

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


def test_basic_config(monkeypatch):
    """
    arrange: TODO.
    act: TODO.
    assert: TODO.
    """
    render_file_mock = MagicMock()
    monkeypatch.setattr("charm.render_file", render_file_mock)

    context = ops.testing.Context(
        charm_type=OpenDKIMCharm,
    )
    base_state: dict[str, str] = {}
    state = ops.testing.State(**base_state)
    out = context.run(context.on.config_changed(), state)
    assert out.unit_status.name == ops.testing.ActiveStatus.name
    render_file_mock.assert_called_once_with(Path("/etc/opendkim.conf"), ANY, 0o644)
    haproxy_conf_contents = render_file_mock.call_args_list[0].args[1]
    assert haproxy_conf_contents == "sure it is not"


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
