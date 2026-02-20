# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }
}

run "basic_deploy" {
  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "2/edge"
    # renovate: depName="opendkim"
    revision = 1
  }

  assert {
    condition     = output.app_name == "opendkim"
    error_message = "opendkim app_name did not match expected"
  }
}
