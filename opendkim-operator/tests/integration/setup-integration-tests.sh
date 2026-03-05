#!/bin/bash
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

set -euxo pipefail

sudo DEBIAN_FRONTEND=noninteractive apt-get -qq update
sudo DEBIAN_FRONTEND=noninteractive apt-get -qq -y install opendkim-tools

# Build the opendkim snap from source for integration testing
# dirname $0 is opendkim-operator/tests/integration; go up 3 levels to the repo root
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
sudo snap install snapcraft --classic
(cd "${REPO_ROOT}/opendkim-snap" && snapcraft pack)

sudo docker run --rm -d -p 1080:1080 -p 25:1025 sj26/mailcatcher
