# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for opendkim unit tests."""

import json
import typing
from secrets import token_hex

import ops
import pytest


@pytest.fixture(scope="function", name="base_state")
def base_state_fixture() -> dict[str, typing.Any]:
    """Fixture for the base state for opendkim."""
    secret_id = token_hex(20)[:20]
    private_keys = {"key1": "PRIVATEKEY1", "key2": "PRIVATEKEY2"}
    secrets = {ops.testing.Secret(id=secret_id, tracked_content=private_keys)}

    keytable = json.dumps(
        [
            ["selector._domainkey.example.com", "example.com:selector:/etc/dkimkeys/key1.private"],
            [
                "selector._domainkey.other.example.com",
                "other.example.com:selector:/etc/dkimkeys/key2.private",
            ],
        ]
    )
    signingtable = json.dumps(
        [
            ["*@example.com", "selector._domainkey.example.com"],
            ["*@other.example.com", "selector._domainkey.other.example.com"],
        ]
    )

    milter_relation = ops.testing.Relation(
        id=1,
        endpoint="milter",
        interface="milter",
        remote_app_data={},
        remote_app_name="smtp-relay",
    )
    return {
        "config": {
            "keytable": keytable,
            "signingtable": signingtable,
            "private-keys": f"secret:{secret_id}",
        },
        "secrets": secrets,
        "relations": [milter_relation],
    }
