# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests."""

from unittest.mock import MagicMock

import ops
import ops.testing

from charm import OpenDKIMCharm


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
