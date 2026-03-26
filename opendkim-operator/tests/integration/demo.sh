#!/bin/bash
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Demo script: deploys opendkim + smtp-relay + mailcatcher on LXD,
# generates DKIM keys, configures signing, sends a test email,
# and verifies the DKIM-Signature header.
#
# Usage: ./demo.sh [--keep]
#   --keep              Do not destroy the Juju model on exit

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"
OPENDKIM_CHARM_DIR="${REPO_ROOT}/opendkim-operator"
OPENDKIM_SNAP_DIR="${REPO_ROOT}/opendkim-snap"
MODEL="${MODEL:-demo-opendkim}"
TEST_DOMAIN="${TEST_DOMAIN:-testrelay.internal}"
SELECTOR="${SELECTOR:-default}"
KEYNAME="${TEST_DOMAIN}-${SELECTOR}"
KEYNAME="${KEYNAME//./-}"
MAILCATCHER_CONTAINER="${MAILCATCHER_CONTAINER:-mailcatcher-lxd}"
MAILCATCHER_SMTP_PORT="${MAILCATCHER_SMTP_PORT:-1025}"
MAILCATCHER_WEB_PORT="${MAILCATCHER_WEB_PORT:-1080}"
KEEP="${KEEP:-0}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
warn() { echo "[$(date '+%H:%M:%S')] WARNING: $*" >&2; }
die() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; exit 1; }

cleanup() {
    local exit_code=$?
    if [[ "${KEEP}" == "1" || "${exit_code}" == "0" ]]; then
        log "Keeping model '${MODEL}' (KEEP=${KEEP}). Use 'juju destroy-model ${MODEL}' to clean up."
        return
    fi
    log "Destroying model '${MODEL}'..."
    juju destroy-model "${MODEL}" --yes 2>/dev/null || true
}
trap cleanup EXIT

need_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

need_cmd juju
need_cmd lxc
need_cmd curl

# ---------------------------------------------------------------------------
# 1. Determine paths
# ---------------------------------------------------------------------------
log "Checking for locally-built snap..."
SNAP_FILE="$(ls -t "${OPENDKIM_SNAP_DIR}"/opendkim_*.snap 2>/dev/null | head -1)"
if [[ -z "${SNAP_FILE}" ]]; then
    log "No local snap found. Building from source..."
    (cd "${OPENDKIM_SNAP_DIR}" && sudo snapcraft pack) || die "snapcraft build failed"
    SNAP_FILE="$(ls -t "${OPENDKIM_SNAP_DIR}"/opendkim_*.snap | head -1)"
fi
log "Using snap: ${SNAP_FILE}"

SNAP_VERSION="$(basename "${SNAP_FILE}" .snap | sed 's/opendkim_//')"
log "Snap version: ${SNAP_VERSION}"

log "Checking for locally-built charm..."
CHARM_FILE="$(ls -t "${OPENDKIM_CHARM_DIR}"/*.charm 2>/dev/null | head -1)"
if [[ -z "${CHARM_FILE}" ]]; then
    log "No local charm found. Building from source..."
    (cd "${OPENDKIM_CHARM_DIR}" && charmcraft pack) || die "charmcraft build failed"
    CHARM_FILE="$(ls -t "${OPENDKIM_CHARM_DIR}"/*.charm | head -1)"
fi
log "Using charm: ${CHARM_FILE}"

# ---------------------------------------------------------------------------
# 2. Set up Juju model
# ---------------------------------------------------------------------------
log "Setting up Juju model '${MODEL}'..."
EXISTING_MODEL=$(juju models --format json 2>/dev/null | jq -r ".models[] | select(.name == \"${MODEL}\") | .name" 2>/dev/null || true)
if [[ -n "${EXISTING_MODEL}" ]]; then
    log "Model '${MODEL}' already exists. Destroying..."
    juju destroy-model "${MODEL}" --yes 2>/dev/null || true
    sleep 2
fi

juju add-model "${MODEL}" localhost/localhost || die "Failed to create model"
juju model-config --model "${MODEL}" automatically-retry-hooks=true

# ---------------------------------------------------------------------------
# 3. Deploy charms
# ---------------------------------------------------------------------------
log "Deploying opendkim charm..."
juju deploy "${CHARM_FILE}" opendkim --model "${MODEL}"
juju wait --model "${MODEL}" -t 600 "opendkim" 2>/dev/null || \
    juju status --model "${MODEL}"

log "Deploying smtp-relay charm..."
juju deploy smtp-relay --model "${MODEL}"
juju wait --model "${MODEL}" -t 600 "smtp-relay" 2>/dev/null || \
    juju status --model "${MODEL}"

log "Integrating smtp-relay with opendkim..."
juju integrate smtp-relay opendkim --model "${MODEL}"

log "Waiting for opendkim to be blocked (no config yet)..."
juju wait --model "${MODEL}" -t 300 "opendkim" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 4. Set up mailcatcher on LXD
# ---------------------------------------------------------------------------
log "Setting up mailcatcher on LXD container '${MAILCATCHER_CONTAINER}'..."

if ! lxc info "${MAILCATCHER_CONTAINER}" >/dev/null 2>&1; then
    log "Creating mailcatcher container..."
    lxc launch ubuntu:24.04 "${MAILCATCHER_CONTAINER}" || die "Failed to create container"
    sleep 5
    lxc exec "${MAILCATCHER_CONTAINER}" -- bash -c \
        'while ! command -v ruby >/dev/null 2>&1; do
            apt-get update -qq && apt-get install -y -qq ruby ruby-dev build-essential >/dev/null 2>&1
            sleep 5
         done'
fi

MAILCATCHER_IP="$(lxc list "${MAILCATCHER_CONTAINER}" --format csv --columns 4 | head -1)"
log "Mailcatcher container IP: ${MAILCATCHER_IP}"

lxc exec "${MAILCATCHER_CONTAINER}" -- pkill -f mailcatcher 2>/dev/null || true
lxc exec "${MAILCATCHER_CONTAINER}" -- bash -c \
    "cd /tmp && nohup mailcatcher --ip=0.0.0.0 --smtp-port=${MAILCATCHER_SMTP_PORT} --http-port=${MAILCATCHER_WEB_PORT} > /tmp/mailcatcher.log 2>&1 &"
sleep 2

if lxc exec "${MAILCATCHER_CONTAINER}" -- bash -c \
    "curl -sf http://localhost:${MAILCATCHER_WEB_PORT}/messages 2>/dev/null" >/dev/null; then
    log "Mailcatcher running at http://${MAILCATCHER_IP}:${MAILCATCHER_WEB_PORT}"
else
    warn "Mailcatcher may not be running. Check: lxc exec ${MAILCATCHER_CONTAINER} -- cat /tmp/mailcatcher.log"
fi

# ---------------------------------------------------------------------------
# 5. Configure DNS on opendkim unit
# ---------------------------------------------------------------------------
log "Configuring DNS on opendkim unit..."
OPENDKIM_UNIT=$(juju status --model "${MODEL}" --format json \
    | jq -r '.applications.opendkim.units | to_entries[0].value.name')
juju exec --model "${MODEL}" --unit "${OPENDKIM_UNIT}" -- bash -c \
    'echo "nameserver 8.8.8.8" | sudo tee /etc/resolv.conf.tail > /dev/null && \
     sudo chattr -i /etc/resolv.conf 2>/dev/null || true'

# ---------------------------------------------------------------------------
# 6. Replace store opendkim snap with locally-built one
# ---------------------------------------------------------------------------
log "Replacing opendkim snap with locally-built ${SNAP_VERSION}..."
STORE_REV=$(juju ssh --model "${MODEL}" "${OPENDKIM_UNIT}" -- \
    snap list opendkim 2>/dev/null | awk 'NR==3{print $3}')
log "Current store revision: ${STORE_REV}"

if [[ "${STORE_REV}" == "${SNAP_VERSION}" ]]; then
    log "Store snap already at ${SNAP_VERSION}. Skipping replace."
else
    juju scp --model "${MODEL}" "${SNAP_FILE}" "${OPENDKIM_UNIT}":/tmp/opendkim.snap
    juju exec --model "${MODEL}" --unit "${OPENDKIM_UNIT}" -- \
        sudo snap install --dangerous /tmp/opendkim.snap
    NEW_REV=$(juju ssh --model "${MODEL}" "${OPENDKIM_UNIT}" -- \
        snap list opendkim 2>/dev/null | awk 'NR==3{print $3}')
    log "Installed local snap revision: ${NEW_REV}"
fi

# ---------------------------------------------------------------------------
# 7. Generate DKIM keypair
# ---------------------------------------------------------------------------
log "Generating DKIM keypair for domain '${TEST_DOMAIN}' selector '${SELECTOR}'..."
if ! command -v opendkim-genkey >/dev/null 2>&1; then
    log "Installing opendkim-tools..."
    sudo apt-get install -y -qq opendkim-tools
fi

DKIM_TMP=$(mktemp -d)
opendkim-genkey -s "${SELECTOR}" -d "${TEST_DOMAIN}" -D "${DKIM_TMP}"
DKIM_TXT="$(cat "${DKIM_TMP}/${SELECTOR}.txt")"
DKIM_PRIVATE="$(cat "${DKIM_TMP}/${SELECTOR}.private")"
rm -rf "${DKIM_TMP}"

log "DKIM TXT record:"
echo "${DKIM_TXT}"
log "Add the above TXT record to DNS before testing DKIM verification."
log "(The signing test works without DNS; opendkim-testkey may report 'query failed')"

# ---------------------------------------------------------------------------
# 8. Create Juju secret and configure opendkim
# ---------------------------------------------------------------------------
log "Creating Juju secret..."
SECRET_NAME="demo-dkim-${KEYNAME}"
SECRET_EXISTS=$(juju secrets --model "${MODEL}" --format json 2>/dev/null \
    | jq -r ".secrets[] | select(.name == \"${SECRET_NAME}\") | .uri" 2>/dev/null || true)
if [[ -n "${SECRET_EXISTS}" && "${SECRET_EXISTS}" != "null" ]]; then
    log "Secret '${SECRET_NAME}' already exists. Updating..."
    SECRET_ID=$(juju secrets --model "${MODEL}" --format json \
        | jq -r ".secrets[] | select(.name == \"${SECRET_NAME}\") | .uri")
    juju update-secret "${SECRET_ID}" --file=- <<< "${KEYNAME}:${DKIM_PRIVATE}"
else
    SECRET_ID=$(juju add-secret --model "${MODEL}" "${SECRET_NAME}" "${KEYNAME}:${DKIM_PRIVATE}")
fi
log "Secret ID: ${SECRET_ID}"

log "Granting secret to opendkim..."
juju grant-secret "${SECRET_ID}" opendkim --model "${MODEL}"

KEYTABLE="[[\"${SELECTOR}._domainkey.${TEST_DOMAIN}\", \"${TEST_DOMAIN}:${SELECTOR}:/etc/dkimkeys/${KEYNAME}.private\"]]"
SIGNINGTABLE="[[\"*@${TEST_DOMAIN}\", \"${SELECTOR}._domainkey.${TEST_DOMAIN}\"]]"

log "Configuring opendkim..."
juju config --model "${MODEL}" opendkim \
    keytable="${KEYTABLE}" \
    signingtable="${SIGNINGTABLE}" \
    "private-keys=secret:${SECRET_ID##*:}"

# ---------------------------------------------------------------------------
# 9. Configure smtp-relay
# ---------------------------------------------------------------------------
log "Configuring smtp-relay with relay domain '${TEST_DOMAIN}'..."
juju config --model "${MODEL}" smtp-relay "relay_domains=- ${TEST_DOMAIN}"

SMTP_UNIT=$(juju status --model "${MODEL}" --format json \
    | jq -r '.applications["smtp-relay"].units | to_entries[0].value.name')
SMTP_IP=$(juju status --model "${MODEL}" --format json \
    | jq -r '.applications["smtp-relay"].units[0] | .["public-address"]')
log "Adding ${TEST_DOMAIN} -> ${SMTP_IP} to /etc/hosts on smtp-relay..."
juju exec --model "${MODEL}" --unit "${SMTP_UNIT}" -- \
    bash -c "echo '${SMTP_IP} ${TEST_DOMAIN}' | sudo tee -a /etc/hosts > /dev/null"
juju exec --model "${MODEL}" --unit "${SMTP_UNIT}" -- \
    bash -c "echo '${MAILCATCHER_IP} mailcatcher' | sudo tee -a /etc/hosts > /dev/null"

# ---------------------------------------------------------------------------
# 10. Wait for both apps to be active
# ---------------------------------------------------------------------------
log "Waiting for opendkim and smtp-relay to become active..."
juju wait --model "${MODEL}" -t 300 \
    "(opendkim | status=active) & (smtp-relay | status=active)" 2>/dev/null || {
    log "Status after wait:"
    juju status --model "${MODEL}"
}

OPENDKIM_STATUS=$(juju status --model "${MODEL}" --format json \
    | jq -r '.applications.opendkim."application-status".current')
if [[ "${OPENDKIM_STATUS}" != "active" ]]; then
    warn "opendkim status is '${OPENDKIM_STATUS}' (expected 'active')."
    warn "The email send may still succeed if the daemon is running."
fi

# ---------------------------------------------------------------------------
# 11. Send a test email
# ---------------------------------------------------------------------------
FROM="Some One <someone@${TEST_DOMAIN}>"
TO="otherone@${TEST_DOMAIN}"
SUBJECT="Test DKIM Signed Email"
BODY="This is a test message to verify DKIM signing."

log "Sending test email via SMTP to ${SMTP_IP}:25..."
log "  From: ${FROM}"
log "  To:   ${TO}"
log "  Subject: ${SUBJECT}"

EMAIL_SCRIPT=$(mktemp)
cat > "${EMAIL_SCRIPT}" <<'PYEOF'
import smtplib, sys
from_addr, to_addr, subject, body, smtp_ip = sys.argv[1:]
msg = f"From: {from_addr}\r\nTo: {to_addr}\r\nSubject: {subject}\r\n\r\n{body}\r\n"
try:
    with smtplib.SMTP(smtp_ip, 25, timeout=10) as server:
        server.set_debuglevel(1)
        server.sendmail(from_addr, [to_addr], msg)
    print("Email sent successfully!")
except smtplib.SMTPException as e:
    print(f"SMTP error: {e}", file=sys.stderr)
    sys.exit(1)
PYEOF

python3 "${EMAIL_SCRIPT}" "$FROM" "$TO" "$SUBJECT" "$BODY" "${SMTP_IP}" || {
    rm -f "${EMAIL_SCRIPT}"
    die "Failed to send email. Check SMTP connectivity."
}
rm -f "${EMAIL_SCRIPT}"

# ---------------------------------------------------------------------------
# 12. Wait for message to appear in mailcatcher
# ---------------------------------------------------------------------------
log "Fetching message from mailcatcher..."
sleep 3

MESSAGES=$(curl -sf "http://${MAILCATCHER_IP}:${MAILCATCHER_WEB_PORT}/messages" 2>/dev/null || echo "[]")
COUNT=$(echo "${MESSAGES}" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")

if [[ "${COUNT}" == "0" ]]; then
    warn "No messages in mailcatcher yet. Retrying..."
    for i in $(seq 1 10); do
        sleep 2
        MESSAGES=$(curl -sf "http://${MAILCATCHER_IP}:${MAILCATCHER_WEB_PORT}/messages" 2>/dev/null || echo "[]")
        COUNT=$(echo "${MESSAGES}" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
        [[ "${COUNT}" != "0" ]] && break
        echo "  Waiting... (${i}/10)"
    done
fi

if [[ "${COUNT}" == "0" ]]; then
    die "No messages received by mailcatcher. Check smtp-relay logs."
fi

MSG_ID=$(echo "${MESSAGES}" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
SOURCE=$(curl -sf "http://${MAILCATCHER_IP}:${MAILCATCHER_WEB_PORT}/messages/${MSG_ID}.source" 2>/dev/null)

# ---------------------------------------------------------------------------
# 13. Verify DKIM-Signature
# ---------------------------------------------------------------------------
log ""
log "========================================="
log "         VERIFICATION RESULTS           "
log "========================================="
log ""

if echo "${SOURCE}" | grep -qi "dkim-signature"; then
    DKIM_HEADER=$(echo "${SOURCE}" | grep -i "DKIM-Signature" | head -1)
    log "PASS: DKIM-Signature header found:"
    echo "${DKIM_HEADER}"
    echo ""

    if echo "${SOURCE}" | grep -qi "from:.*testrelay.internal"; then
        log "PASS: From header contains test domain."
    fi

    log ""
    log "Full headers:"
    echo "${SOURCE}" | sed 's/^/  /'
else
    echo "${SOURCE}" >&2
    die "FAIL: No DKIM-Signature header found. Check: juju debug-log --model ${MODEL} --include-unit opendkim/0"
fi

log ""
log "========================================="
log "  Email delivered and DKIM-signed        "
log "  successfully!                          "
log "========================================="
log ""
log "View in mailcatcher web UI:"
log "  http://${MAILCATCHER_IP}:${MAILCATCHER_WEB_PORT}/messages/${MSG_ID}/source"
log ""
log "Useful commands:"
log "  juju status --model ${MODEL}"
log "  juju debug-log --model ${MODEL} --include-unit opendkim/0"
log "  juju ssh --model ${MODEL} ${OPENDKIM_UNIT}"
log ""
