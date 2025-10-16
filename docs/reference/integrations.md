# Integrations

<!-- Use the template below to add information about integrations supported by this charm. -->

### Milter integration

_Interface_:   milter
_Supported charms_: postfix-relay

The milter integration offers the signing and verification of emails to other charms.

For example, to integrate with the `postfix-relay` charm:

```
juju integrate opendkim postfix-relay:milter
```
