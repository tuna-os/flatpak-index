# Check-metadata failures

`check-metadata.yml` is the only production health check that this repository
owns. The workflow runs every day at 06:17 UTC and by manual request. It
compares the served Flatpak remote against the registry. It reports metadata
that software centres need.

This runbook explains what the check validates, how to read a red run, and who
fixes each failure.

## What the check validates

The workflow fetches the served index and audits it:

```sh
curl -sSfL -o served-index.json https://tunaos.org/flatpak/index/static
./scripts/enrich-index.py served-index.json --check
```

`enrich-index.py --check` reads the AppStream labels that the registry publishes
for each digest in the served index. It reports a failure when an entry lacks
metadata that software centres need. It prints warnings for entries that install
correctly but show an empty frame in a software centre. A red run means at least
one failure. A green run means the served index matches the registry.

The check reads the served index from `tuna-os/docs`, not this repository's
`index/static` snapshot. A failure may mean the production index is stale. It may
not mean a fault in this repository.

## What the check does not validate

The check audits only the applications that `tuna-os/docs` lists in
`expected-apps.json`. The check does not audit a served application that
`expected-apps.json` omits. See issue #98 for this gap.

The check also gives no alert. A red run is a failed Actions job. No page,
message, or email follows it. A person must notice the red run and open a task.
Issue #138 tracks the plan to add alerting.

## Read a red run

A red run prints lines that start with `!` for failures and `~` for warnings.
Read the `!` lines first. Each names an application and an architecture. Match
each failure to one root cause below. The fix lives in a different repository
for each cause.

### Stale served index

Symptom: the run reports that the served index misses labels. The registry has
these labels. The production index in `tuna-os/docs` has no new publish yet, or
the Cloudflare Pages deploy has not finished.

This is a deployment lag. It is not a metadata fault. Wait for the next publish
of `tuna-os/docs`. Wait for the Pages deploy to propagate. Re-run the check after
the deploy. If the run stays red, read the other root causes.

### Missing metadata

Symptom: the run prints `image has no AppStream metadata (...); it needs a
metainfo file`. The application image lacks the labels that build the remote's
AppStream catalogue.

Fix the metainfo and icon of the application in its own repository. Publish a
new OCI image. The updater replaces the entry for the same architecture. Re-run
the served-index audit.

### Registry read error

Symptom: the run prints `could not read labels -- <error>`. The check could not
read the labels for a digest.

Check the `REGISTRY_TOKEN` secret. Confirm the digest still exists in the
registry, and a new publish replaces it. If the error repeats, the registry may
be unavailable. Wait, and re-run.

### Malformed catalogue

Symptom: the run prints `AppStream catalogue does not parse`. The metainfo XML
of the application is malformed.

Fix the metainfo XML in the application repository. Publish a new image, and
re-run the served-index audit.

## Escalation

1. Re-run the check to prove the failure is real. A propagation delay clears on
   the next run.
2. Read the `!` lines. Match each failure to a root cause.
3. Route the fix:
   - Stale served index: redeploy `tuna-os/docs`. Owner: the deployer.
   - Missing metadata or malformed catalogue: fix the application repository.
     Owner: the application maintainer.
   - Registry read error: check the token, or wait for the registry. Owner: the
     index operator.
4. Re-run the served-index audit after the fix. A green run proves the fix.

This repository does not own the production index or the deploy. Do not edit
`tuna-os/docs/static/flatpak/index/static` directly. Make the change through the
normal review path in the application repository or `tuna-os/docs`.
