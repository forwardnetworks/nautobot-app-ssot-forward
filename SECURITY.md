# Security Policy

## Reporting a vulnerability

Report security issues privately. Do not open a public issue, pull request, or
discussion for a suspected vulnerability.

Preferred channel:

- GitHub Private Vulnerability Reporting from this repository's Security tab.

Alternative channel:

- Email security@forwardnetworks.com with subject `forward-nautobot security report`.

Include the plugin version, Nautobot version, reproduction steps, affected code
paths, and impact. We aim to acknowledge reports within 3 business days and
provide an assessment or remediation plan within 10 business days.

## Supported versions

Security fixes target the latest released minor version and the Nautobot baseline
listed in the README compatibility matrix.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Older releases | Upgrade to the latest release |

## Scope and handling notes

- Forward credentials are stored in the Nautobot database. The profile password
  field is encrypted at rest with Fernet using a key derived from Django
  `SECRET_KEY`, masked in UI output, and redacted from support bundles. Protect
  `SECRET_KEY` like a credential; rotating it makes existing encrypted Forward
  passwords undecryptable until operators re-enter them.
- Forward API traffic uses `httpx` with `trust_env=True`, so Nautobot process
  proxy variables such as `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY` are honored.
- SaaS profiles should use `https://fwd.app` with TLS verification enabled.
  On-prem profiles may use a custom URL and may disable TLS verification only
  when local certificate policy requires it.
- Sync is an inventory-wide write trust boundary. Restrict profile management
  and SSoT job execution to trusted Nautobot operators.
- Keep customer names, network IDs, snapshot IDs, screenshots, and credentials
  out of source, docs, fixtures, and release artifacts. The sensitive-content
  gate blocks common Forward identifiers and supports a local pattern file for
  customer-specific terms.
