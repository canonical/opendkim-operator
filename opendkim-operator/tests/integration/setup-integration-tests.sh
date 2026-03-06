#!/bin/bash
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

set -euxo pipefail

sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update
sudo DEBIAN_FRONTEND=noninteractive apt-get -qq -y install opendkim-tools
sudo docker run --rm -d -p 1080:1080 -p 25:1025 sj26/mailcatcher
