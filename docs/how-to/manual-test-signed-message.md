# Manually test DKIM signing in the charm container

This guide reproduces the behavior of `test_opendkim_signed_message` manually, including checks inside the OpenDKIM charm unit.

## Prerequisites

- A machine model with `opendkim` and `smtp-relay` applications deployed and integrated.
- LXD-based MailCatcher setup script available at `opendkim-operator/tests/integration/setup-integration-tests.sh`.
- `opendkim.genkey` available on the machine running these commands.

If your model is not deployed yet:

```bash
juju deploy ./opendkim-operator/opendkim_amd64.charm opendkim
juju deploy smtp-relay smtp-relay
juju integrate smtp-relay opendkim
juju wait -w
```

## 1) Start MailCatcher

From the repository root:

```bash
./opendkim-operator/tests/integration/setup-integration-tests.sh
curl -sS http://127.0.0.1:1080/messages
```

The second command should return `[]` (or a JSON array).

## 2) Generate a DKIM key and create/update Juju secret

```bash
DOMAIN=testrelay.internal
SELECTOR=default
KEYNAME=testrelay-internal-default
WORKDIR=/tmp/opendkim-manual

mkdir -p "$WORKDIR"
opendkim.genkey -s "$SELECTOR" -d "$DOMAIN" -D "$WORKDIR"

juju add-secret opendkimsecret "${KEYNAME}#file=${WORKDIR}/${SELECTOR}.private" \
  || juju update-secret opendkimsecret "${KEYNAME}#file=${WORKDIR}/${SELECTOR}.private"

SECRET_ID=$(juju show-secret opendkimsecret --format yaml | awk '/^uri:/{print $2; exit}')
juju grant-secret "$SECRET_ID" opendkim
```

## 3) Configure OpenDKIM and smtp-relay

```bash
juju config opendkim \
  private-keys="$SECRET_ID" \
  keytable="[[\"${SELECTOR}._domainkey.${DOMAIN}\", \"${DOMAIN}:${SELECTOR}:/etc/dkimkeys/${KEYNAME}.private\"]]" \
  signingtable="[[\"*@${DOMAIN}\", \"${SELECTOR}._domainkey.${DOMAIN}\"]]"

juju config smtp-relay relay_domains="- ${DOMAIN}"
juju wait -w
```

## 4) Point smtp-relay unit to the local MailCatcher host

This matches what the integration test does by updating `/etc/hosts` on the `smtp-relay` machine.

```bash
RUNNER_IP=$(ip route get 8.8.8.8 | awk '{print $7; exit}')
SMTP_RELAY_MACHINE=$(juju show-unit smtp-relay/0 --format yaml | awk '/machine:/{print $2; exit}')

juju exec --machine "$SMTP_RELAY_MACHINE" \
  "echo ${RUNNER_IP} ${DOMAIN} | sudo tee -a /etc/hosts"
```

## 5) Send a test email through smtp-relay

```bash
SMTP_RELAY_IP=$(juju show-unit smtp-relay/0 --format yaml | awk '/public-address:/{print $2; exit}')

SMTP_RELAY_IP="$SMTP_RELAY_IP" python3 - <<'PY'
import smtplib
import os

domain = "testrelay.internal"
smtp_relay_ip = os.environ["SMTP_RELAY_IP"]
from_addr = f"Some One <someone@{domain}>"
to_addrs = [f"otherone@{domain}"]
msg = f"""Subject: Hi Mailtrap
To: {from_addr}
From: {to_addrs[0]}

This is my first message with Python."""

with smtplib.SMTP(smtp_relay_ip) as server:
    server.sendmail(from_addr=from_addr, to_addrs=to_addrs, msg=msg)
PY
```

## 6) Verify message and DKIM signature

```bash
MSG_ID=$(curl -sS http://127.0.0.1:1080/messages \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d[0]["id"] if d else "")')

test -n "$MSG_ID"
curl -sS "http://127.0.0.1:1080/messages/${MSG_ID}.source" | grep "DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed; d=${DOMAIN}"
```

If `grep` returns a matching line, DKIM signing worked.

## 7) Validate inside the OpenDKIM charm unit container

```bash
juju ssh opendkim/0 "sudo ls -l /var/snap/opendkim/current/etc/dkimkeys"
juju ssh opendkim/0 "sudo sed -n '1,120p' /var/snap/opendkim/current/etc/dkimkeys/keytable"
juju ssh opendkim/0 "sudo sed -n '1,120p' /var/snap/opendkim/current/etc/dkimkeys/signingtable"
juju ssh opendkim/0 "sudo snap services opendkim"
juju ssh opendkim/0 "sudo opendkim -n -x /var/snap/opendkim/current/etc/opendkim.conf"
```

Expected:

- Key files exist in `/var/snap/opendkim/current/etc/dkimkeys/`.
- `opendkim.daemon` is active.
- `opendkim -n` exits successfully.

## Optional cleanup

```bash
curl -sS -X DELETE "http://127.0.0.1:1080/messages/${MSG_ID}"
```