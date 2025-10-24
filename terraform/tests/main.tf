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
      version = "~> 0.23.0"
      source  = "juju/juju"
    }
  }
}

provider "juju" {}

module "opendkim" {
  source   = "./.."
  app_name = "opendkim"
  channel  = var.channel
  model    = "prod-opendkim-example"
  revision = var.revision
}
