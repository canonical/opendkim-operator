# Build and validate the OpenDKIM snap

This document captures the exact workflow we followed to build, patch, and validate the OpenDKIM snap in this repository.

## Goal

Produce a local OpenDKIM snap that:

- contains all runtime dependencies used by `opendkim-genkey`
- works under snap confinement for key generation
- can be consumed by the charm integration tests

## Repository layout used

- Snap source: `opendkim-snap/snap/snapcraft.yaml`
- Built snap artifact: `opendkim-snap/opendkim_2.11.0-beta2_amd64.snap`
- Charm that installs the snap from the store: `opendkim-operator/src/charm.py`
- Integration test helper invoking key generation: `opendkim-operator/tests/integration/test_charm.py`

## Reproduce the failure first

We started by reproducing the failing command from the integration tests:

```bash
tmpdir=$(mktemp -d)
cd "$tmpdir"
opendkim.genkey -s default -d testrelay.internal
```

Observed error:

```text
opendkim-genkey: openssl exited with status %d
1
```

This confirmed the issue was reproducible outside of pytest.

## Confirm root causes

### Root cause A: `openssl` not available in snap payload/runtime

`opendkim-genkey` is a Perl wrapper that shells out to `openssl`.
Without `openssl` in the snap runtime, key generation fails.

### Root cause B: strict confinement + temp path choice

Even after adding `openssl`, key generation failed when writing in paths not allowed by confinement.
Using a home-based temporary directory and granting the `home` plug for the `genkey` app resolved this.

## Patch Snapcraft configuration

We updated `opendkim-snap/snap/snapcraft.yaml`:

- Add `openssl` to `stage-packages`.
- Add `home` plug to the `genkey` app.

Relevant shape:

```yaml
apps:
  genkey:
    command: usr/sbin/opendkim-genkey
    plugs: [network, home]

parts:
  opendkim:
    stage-packages:
      - opendkim
      - opendkim-tools
      - openssl
      - perl
      - dns-root-data
```

## Build the snap

From `opendkim-snap/`:

```bash
snapcraft pack
```

This produces:

```text
opendkim_2.11.0-beta2_amd64.snap
```

## Install and validate locally

Install local artifact:

```bash
sudo snap remove opendkim || true
sudo snap install --dangerous ./opendkim_2.11.0-beta2_amd64.snap
```

Validate key generation using a home temp directory and explicit output directory:

```bash
tmpdir=$(mktemp -d "$HOME/opendkim-genkey-XXXXXX")
opendkim.genkey -s default -d testrelay.internal -D "$tmpdir"
ls -la "$tmpdir"
```

Expected output files:

- `default.private`
- `default.txt`

Run the spread tests with `snapcraft test`:

```bash
cd opendkim-snap
snapcraft test
```

This builds the snap and runs all spread tasks under `tests/spread/` (`snap-apps/`, `keygen/`, `config-validation/`) inside an LXD VM.

## Align integration test helper with confinement

In `opendkim-operator/tests/integration/test_charm.py`, generate keys in a home temp directory and pass `-D`:

- `tempfile.TemporaryDirectory(dir=pathlib.Path.home())`
- `opendkim.genkey ... -D <tmpdir>`

This makes test behavior match snap confinement constraints.

## Rebuild charm artifact cleanly before testing

When validating with the charm, use a clean build as requested:

```bash
cd opendkim-operator
charmcraft clean
charmcraft pack
```

Then run integration tests with explicit charm file:

```bash
cd opendkim-operator
tox -e integration -- --charm-file opendkim_amd64.charm
```

## Additional charm robustness fixes discovered during testing

While running integration tests, we also hit charm-side issues unrelated to `opendkim.genkey` packaging. We addressed these to keep test runs moving:

- Ensure parent directories exist before writing managed files.
- Fallback to `root` ownership if `opendkim` user is missing.
- Restart the snap daemon (`snap restart opendkim.daemon`) instead of reloading a non-existent host systemd unit (`opendkim.service`).

## Troubleshooting checklist

If key generation fails again, check the following in order:

1. Snap metadata contains `genkey` with `home` plug.
2. Snap payload contains `/usr/bin/openssl`.
3. You are generating into a writable path under `$HOME`.
4. You are passing `-D <writable-dir>` to `opendkim.genkey`.
5. You rebuilt and reinstalled the local snap artifact after changes.
6. You rebuilt the charm with `charmcraft clean && charmcraft pack` before integration testing.

## Quick command summary

```bash
# Build snap
cd opendkim-snap
snapcraft pack

# Install snap
sudo snap remove opendkim || true
sudo snap install --dangerous ./opendkim_2.11.0-beta2_amd64.snap

# Verify genkey
tmpdir=$(mktemp -d "$HOME/opendkim-genkey-XXXXXX")
opendkim.genkey -s default -d testrelay.internal -D "$tmpdir"
ls -la "$tmpdir"

# Run snap-native tests
cd opendkim-snap
snapcraft test

# Build charm cleanly and test
cd opendkim-operator
charmcraft clean
charmcraft pack
tox -e integration -- --charm-file opendkim_amd64.charm
```
