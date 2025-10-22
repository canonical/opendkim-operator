# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variables {
  channel = "2/edge"
  # renovate: depName="opendkim"
  revision = 1
}

run "basic_deploy" {
  assert {
    condition     = module.charm_name.app_name == "opendkim"
    error_message = "charm_name app_name did not match expected"
  }
}
