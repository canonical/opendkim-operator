# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Fixtures for charm integration tests."""

import typing
from collections.abc import Generator

import jubilant
import pytest


@pytest.fixture(scope="module", name="smtp_dkim_signing_charm")
def smtp_dkim_signing_charm_fixture(pytestconfig: pytest.Config):
    """Get value from parameter charm-file."""
    charm = pytestconfig.getoption("--charm-file")
    use_existing = pytestconfig.getoption("--use-existing", default=False)
    if not use_existing:
        assert charm, "--charm-file must be set"
    return charm


@pytest.fixture(scope="module", name="smtp_dkim_signing_app")
def deploy_smtp_dkim_signing_fixture(
    smtp_dkim_signing_charm: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy smtp-dkim-signing."""
    deploy_smtp_dkim_signing_name = "smtp-dkim-signing"

    if not juju.status().apps.get(deploy_smtp_dkim_signing_name):
        juju.deploy(
            f"./{smtp_dkim_signing_charm}",
            deploy_smtp_dkim_signing_name,
        )
    juju.wait(
        lambda status: status.apps[deploy_smtp_dkim_signing_name].is_active,
        error=jubilant.any_blocked,
        timeout=10 * 60,
    )
    return deploy_smtp_dkim_signing_name


@pytest.fixture(scope="module", name="smtp_relay_app")
def deploy_smtp_relay_fixture(
    smtp_dkim_signing_app: str,
    juju: jubilant.Juju,
) -> str:
    """Deploy smtp-relay and integrate with dkim."""
    smtp_relay_app_name = "smtp-relay"

    if not juju.status().apps.get(smtp_relay_app_name):
        juju.deploy(smtp_relay_app_name, smtp_relay_app_name)
        juju.integrate(smtp_relay_app_name, smtp_dkim_signing_app)
    juju.wait(
        lambda status: jubilant.all_active(status, smtp_relay_app_name, smtp_dkim_signing_app),
        error=jubilant.any_blocked,
        timeout=10 * 60,
    )
    return smtp_relay_app_name


@pytest.fixture(scope="session", name="juju")
def juju_fixture(request: pytest.FixtureRequest) -> Generator[jubilant.Juju, None, None]:
    """Pytest fixture that wraps :meth:`jubilant.with_model`."""

    def _show_debug_log(juju: jubilant.Juju):
        """Print debug logs."""
        if request.session.testsfailed:
            log = juju.debug_log(limit=1000)
            print(log, end="")

    use_existing = request.config.getoption("--use-existing", default=False)
    if use_existing:
        juju = jubilant.Juju()
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)
        return

    model = request.config.getoption("--model")
    if model:
        juju = jubilant.Juju(model=model)
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)
        return

    keep_models = typing.cast(bool, request.config.getoption("--keep-models"))
    with jubilant.temp_model(keep=keep_models) as juju:
        juju.wait_timeout = 10 * 60
        juju.model_config({"automatically-retry-hooks": True})
        yield juju
        _show_debug_log(juju)
        return
