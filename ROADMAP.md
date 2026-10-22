# Flatpak Index Roadmap

This roadmap turns the TunaOS Flatpak remote into a single, reviewable
distribution service. It covers index ownership and publication; application
features and packaging roadmaps remain in their respective repositories.

## Current state

The production remote at `https://tunaos.org/flatpak/` is served from
`tuna-os/docs` by the `tunaos-org` Cloudflare Worker, while this repository
contains a historical index snapshot and a separate GitHub Pages deployment.
Application repositories publish OCI images and are currently documented to
push index updates directly to `docs` with a `FLATPAK_INDEX_TOKEN`.

Until the consolidation decision below is complete, treat the index under
`tuna-os/docs/static/flatpak/` as production and this repository as a reference
snapshot. Do not infer production state from this repository's Pages site.

## Q4 2026

_Currency: current as of 2026-09, strategist review._

Q4 is the quarter in which the ownership decision from the near term is
executed and the publication model is consolidated. The two outcome sets below
are the exit criteria for the quarter; both must be met for the roadmap to
close Q4. Items owned outside this repository are marked, because this repo
builds the index but does not serve it or control application-repo workflows.

### Ownership consolidation

| Item | Q4 exit criterion | Owned by |
| --- | --- | --- |
| Production source named | `tuna-os/docs` and `tuna-os/flatpak-index` both name the same production source repository, with a dated migration or retirement plan recorded in the Decision record below. | both repos |
| Consolidation executed | Production ownership has moved to one repository, or this repository is formally retired as an index host with a redirect published. | decision owner |
| Non-authoritative snapshot | The GitHub Pages snapshot is removed, or a redirect makes clear it is not production. | tuna-os/flatpak-index |

### Publisher contract migration

| Item | Q4 exit criterion | Owned by |
| --- | --- | --- |
| Single publisher contract | One reviewed publisher contract is documented: the fields every publish must supply (app ID, immutable OCI digest, architecture set, source revision, channel) and the validation it runs before publication. | tuna-os/flatpak-index |
| Centralized publish path | One automation path validates and publishes the index, replacing per-app `FLATPAK_INDEX_TOKEN` cross-repository write credentials. | tuna-os/.github + application repos |
| Credential reduction | A documented plan to remove long-lived per-app tokens, with the first application repositories migrated to the centralized path. | application repos |

### Freshness SLO

- **Definition.** Publish-to-availability SLO: 95% of application publishes are
  available at `https://tunaos.org/flatpak/` within 24 hours of the source
  repository's publish. This is the Q4 target; the exact figure is the first
  thing the ownership decision records once the publish path is consolidated.
- **Measurement.** The production freshness check (`scripts/check-freshness.py`,
  run on a schedule by `.github/workflows/check-metadata.yml`) reports whether
  the served index carries the latest published digest for every entry and
  whether every served entry is installable from the served URL.
- **Gap.** A precise publish-to-availability latency needs the source publish
  timestamp, which lives in the application repositories. Capturing it is part
  of the publisher contract migration: once publishes flow through the
  centralized path the timestamp is available and the SLO becomes a measured
  number rather than a target.

### How this maps to the roadmap

- Ownership consolidation closes the **Near term** (ownership decision recorded)
  and **Mid term** (non-authoritative copies removed) exit gates.
- Publisher contract migration closes the **Mid term** (one reviewed publisher
  contract, one automation path) exit gate.
- The freshness SLO feeds the **Long term** availability/freshness history measure.

## Near term: decide and make drift visible

Target: one planning cycle.

- Name an accountable owner for the remote and choose its long-term source
  repository: move production ownership here, or formally retire this
  repository as an index host.
- Inventory every documented app ID, OCI reference, supported architecture,
  and publisher workflow against the served production index.
- Define a freshness SLO from a successful app publish to remote availability.
- Add a production check that installs or inspects every catalog entry from the
  served URL and reports catalog, digest, architecture, and metadata drift.
- Document an incident owner and a tested rollback procedure for a bad index
  publication.

Exit gate: the ownership decision is recorded, the production source is named
in both repositories, and drift is measured from the user-facing endpoint.

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

Record the ownership decision and dates here when approved. Until then, this
roadmap describes direction rather than a commitment to move production out of
`tuna-os/docs`.
