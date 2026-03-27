# OpenDKIM operator

A [Juju](https://juju.is/) [charm](https://documentation.ubuntu.com/juju/3.6/reference/charm/) deploying and
managing [OpenDKIM](http://www.opendkim.org/) on machines.

The OpenDKIM charm installs and configures the [OpenDKIM](http://www.opendkim.org/) application and offers
other charms the ability to sign and validate email messages using the `milter` relation.

Like any Juju charm, this charm supports one-line deployment, configuration, integration, scaling, and more.
For opendkim.

This charm will make operating OpenDKIM simple and straightforward for email administration teams through Juju's clean interface.

## In this documentation

| | |
|--|--|
|  [Tutorials](link to tutorial)</br>  Get started - a hands-on introduction to using the charm for new users </br> |  [How-to guides](link to how-to guide) </br> Step-by-step guides covering key operations and common tasks |
| [Reference](link to reference) </br> Technical information - specifications, APIs, architecture | [Explanation](link to explanation) </br> Concepts - discussion and clarification of key topics  |

## Contributing to this documentation

Documentation is an important part of this project, and we take the same open-source approach
to the documentation as the code. As such, we welcome community contributions, suggestions, and
constructive feedback on our documentation.
See [How to contribute](how-to/contribute.md) for more information.

If there's a particular area of documentation that you'd like to see that's missing, please
[file a bug](https://github.com/canonical/opendkim-operator/issues).

## Project and community

The OpenDKIM operator is a member of the Ubuntu family. It's an open-source project that warmly welcomes community
projects, contributions, suggestions, fixes, and constructive feedback.

- [Code of conduct](https://ubuntu.com/community/code-of-conduct)
- [Get support](https://discourse.charmhub.io/)
- [Join our online chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
- [Contribute](how-to/contribute.md)

Thinking about using the OpenDKIM Operator for your next project?
[Get in touch](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)!

# Contents

1. [How-to]()
  1. [Integrate with COS](how-to/integrate-with-cos.md)
  1. [Contribute](how-to/contribute.md)
  1. [Upgrade](how-to/upgrade.md)
1. [Reference]()
  1. [Actions](reference/actions.md)
  1. [Charm architecture](reference/charm-architecture.md)
  1. [Configurations](reference/configurations.md)
  1. [Integrations](reference/integrations.md)
  1. [Metrics](reference/metrics.md)
1. [Explanation]()
  1. [Security](explanation/security.md)
1. [Release notes]()
  1. [Overview](release-notes/landing-page.md)
