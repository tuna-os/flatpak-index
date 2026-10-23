# Security Policy

## Supported Versions

Only the `main` branch is actively supported. This repository holds the scripts
and CI that build the TunaOS Flatpak remote; it does **not** serve the live
index. The served index lives in
[tuna-os/docs](https://github.com/tuna-os/docs) at
`static/flatpak/index/static`. Report issues against whichever of these two
holds the code you are reporting.

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub
issues.** Use private disclosure instead.

1. Go to the repository's **Security** tab:
   <https://github.com/tuna-os/flatpak-index/security>
2. Click **Report a vulnerability**.
3. Describe the issue: affected component (e.g. `scripts/enrich-index.py`,
   `scripts/oci.py`, a GitHub Action), what an attacker can do, and steps to
   reproduce. If you have a fix or a patch, include it.

You can expect an acknowledgement within 48 hours and a status update within 5
business days.

## What to Expect

- Reports are treated confidentially and used only to develop and ship a fix.
- The maintainers prepare a fix before public disclosure.
- Public disclosure happens after a fix is released, or after 90 days,
  whichever is sooner.

## Scope

Vulnerabilities in this repository include the Python scripts in `scripts/`
(the OCI index builder and the live-remote auditor), the GitHub Actions in
`.github/actions/` and `.github/workflows/`, and anything that runs in the
publish pipeline. Security issues in the published Flatpak packages themselves
belong in the application repository that publishes them, not here.
