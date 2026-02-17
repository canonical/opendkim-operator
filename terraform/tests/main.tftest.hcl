# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variables {
  channel = "2/edge"
  # renovate: depName="opendkim"
  revision = 1
}

run "basic_deploy" {
  module {
    source = "./tests"
  }

  assert {
    condition     = module.opendkim.app_name == "opendkim"
    error_message = "opendkim app_name did not match expected"
  }
}
