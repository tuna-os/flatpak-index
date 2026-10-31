# Flatpak Index Roadmap

This roadmap turns the TunaOS Flatpak remote into a single, reviewable
distribution service. It covers index ownership and publication; application
features and packaging roadmaps remain in their respective repositories.

## Current state

The `tunaos-org` Cloudflare Worker serves the production remote at
`https://tunaos.org/flatpak/` with static assets from `tuna-os/docs`.
The decision in issue #171 confirms `tuna-os/docs` as the canonical catalog.
Release workflows send updates directly to `tuna-os/docs` with
`FLATPAK_INDEX_TOKEN`.

This repository provides tooling, templates, and metadata audits.
It does not serve the production catalog. Do not infer production state from
this repository's Pages site.

## Near term: decide and make drift visible

Target: one planning cycle.

- Name an accountable owner for the remote and choose its long-term source
  repository: move production ownership here, or formally retire this
  repository as an index host. (Complete: see Decision record.)
- Inventory every documented app ID, OCI reference, supported architecture,
  and publisher workflow against the served production index.
- Define a freshness SLO from a successful app publish to remote availability.
- Add a production check that installs or inspects every catalog entry from the
  served URL and reports catalog, digest, architecture, and metadata drift.
- Document an incident owner and a tested rollback procedure for a bad index
  publication.

Exit gate: the Decision record names the canonical catalog, documentation
identifies `tuna-os/docs`, and CI measures drift from the served endpoint.

## Mid term: consolidate publication

Target: the cycle after the ownership decision.

- Route index changes through one reviewed publisher contract rather than
  giving every application repository a long-lived cross-repository write
  credential.
- Require publisher input to identify the app ID, immutable OCI digest,
  architecture set, source revision, and intended channel.
- Validate the candidate index before publication and the served index after
  deployment.
- Remove or redirect the non-authoritative Pages deployment and delete the
  historical snapshot once consumers and documentation no longer depend on it.
- Provide a contributor runbook for adding, updating, pausing, and retiring an
  application.

Exit gate: one repository owns production, one automation path publishes it,
and non-authoritative copies cannot be mistaken for the live remote.

## Long term: operate the remote as a product

- Publish availability and freshness history against the defined SLO.
- Review catalog health and unsupported architectures each release cycle.
- Track install success or another privacy-preserving adoption signal so the
  catalog roadmap is informed by user outcomes rather than repository activity.
- Establish lifecycle states and time-bounded removal notices for applications
  and channels.

## Success measures

| Outcome | Measure |
| --- | --- |
| Unambiguous ownership | One documented production repository and owner |
| Controlled publishing | Zero per-app long-lived cross-repository write credentials |
| Catalog integrity | Zero unexplained differences between declared and served entries |
| Freshness | Successful publications meet the agreed publish-to-availability SLO |
| Recoverability | A rollback exercise succeeds within the documented recovery target |
| Contributor clarity | One tested runbook covers add, update, pause, and retire workflows |

## Decision record

### 2026-10-30: Canonical catalog and production ownership (#171)

Maintainers recorded the catalog ownership decision in issue #171:

- **Canonical catalog repository:** `tuna-os/docs` (`static/flatpak/index/static`).
- **Production remote URL:** `https://tunaos.org/flatpak/tuna-os.flatpakrepo`.
- **Production served index:** `https://tunaos.org/flatpak/index/static`.
- **Server infrastructure:** The Worker for `tunaos.org` deploys assets from `tuna-os/docs`.
- **Production catalog owner:** `tuna-os/docs` maintainers.
- **Tooling and audit owner:** `tuna-os/flatpak-index` maintainers.
- **Publisher target:** Workflows send updates only to `tuna-os/docs` with `FLATPAK_INDEX_TOKEN`. Publishers do not write to `flatpak-index`.
- **Snapshot retirement:** Issue #173 removes the local `index/static` snapshot and Pages deployment.
- **Rollback responsibility:** `tuna-os/docs` maintainers roll back bad catalog entries through a git revert of `static/flatpak/index/static` in `tuna-os/docs`.
