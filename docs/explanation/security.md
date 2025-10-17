# Security overview

The OpenDKIM charm provides signing and validation of email messages.

For the signing of messages, private keys are used. The private keys are
passed to the charm as secrets. These private keys must be kept secret and
never exposed to unauthorized users.

The functionality for signing and verifying messages should only be exposed
to trusted applications.

## Risks

- Disclosure of private keys.
- Signing of messages for untrusted parties.
- Incorrect validation of messages.
