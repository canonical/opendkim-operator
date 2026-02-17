# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "2/edge"
}

variable "revision" {
  description = "Revision number of the charm."
  type        = number
  default     = null
}

terraform {
  required_providers {
    juju = {
      version = "> 1.1.0"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

resource "juju_model" "test_model" {
  name = "test-model"
}

module "opendkim" {
  source     = "./.."
  app_name   = "opendkim"
  channel    = var.channel
  model_uuid = juju_model.test_model.uuid
  revision   = var.revision
}
