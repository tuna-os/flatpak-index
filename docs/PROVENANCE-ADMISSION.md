# Evaluating provenance admission

This is a proposal, **not an enforced publication policy**. The production
catalog is currently served from `tuna-os/docs`; application workflows can write
it directly. The owner and publication entry point remain open decisions in
[#171](https://github.com/tuna-os/flatpak-index/issues/171) and
[#168](https://github.com/tuna-os/flatpak-index/issues/168). The shared
`publish-flatpak-index` action, the `update-flatpak-index` action, and vendored
`update-index.py` copies are distinct paths. An admission check in only this
repository would not stop the other writers or protect deployment.

## Candidate contract

- The eventual reviewed publisher accepts only entries from an explicit,
  review-controlled mapping of app/ref and registry repository to producer
  repository, release workflow, permitted source refs, architectures, and
  self-hosted runner policy. Each project's maintainers must decide whether
  its release runner is trusted; do not assume all self-hosted runners are
  acceptable or categorically reject them without that decision. Policy changes
  need independent review and must not be supplied by the publishing app.
- Resolve any tag once to exact raw manifest bytes and their sha256 digest;
  verify a cryptographically valid producer attestation for that *same digest*,
  expected producer repository and workflow, and an allowed source ref. Missing,
  malformed, unverifiable, wrong-repository, wrong-workflow or wrong-ref
  attestations fail closed. Never verify a tag and later re-resolve it for
  publication. Confirm the verifier actually binds subject, signer and ref;
  test it against real producer attestations before enabling enforcement.
- If the attested root is an OCI index, verify every selected child manifest
  against its descriptor digest; verify each config blob against its descriptor
  digest before reading labels. For a single manifest, verify its config in the
  same way. Reject malformed or unsupported digests, fetch failures and byte
  mismatches rather than skipping a private or missing image. Preserve each
  distinct Flatpak ref, branch and architecture, including installer frontends,
  and both Flatpak and AppStream labels. Scope replacement to the allowed app
  and ref so one producer cannot replace another producer's entries.
- Build and validate the entire candidate without changing the live catalog.
  On any failure, keep the previous production artifact available; deploy only
  the complete validated candidate using the selected publication mechanism.
  Audit the served artifact and retain an operator rollback path. Restrict all
  alternate write paths, or they bypass admission entirely.

The [Frostyard implementation](https://github.com/frostyard/flatpak-index/blob/ff27263767e7d95fc777a24592c1d5ff85931b82/scripts/build-index.py)
illustrates verifying a root attestation and hashing child/config bytes. Its
missing/private-image skip and blanket self-hosted-runner denial are not adopted
here. Producer provenance is not a Flatpak client signature: it does not
authenticate the catalog to clients, and no cosign signature of the current
index is asserted. Reproducible rebuilds can provide additional evidence but
are not a substitute for client trust or provenance verification.

## Current partial protection and verification needed

The `oci.py` registry helper used by the metadata auditor checks raw sha256
bytes for digest-addressed manifests and configs before parsing. A tag passed
as a manifest reference remains mutable and is not authenticated by this
check. This is integrity checking against the caller's digest, **not** an
attestation, an admission gate, or a check on the local OCI layout read by
`update-index.py`. The repair command also must not be treated as an atomic
production publisher.

Before rolling out the proposed gate, inventory and migrate all production
writers, select and protect the publisher, and agree the per-project policy.
Exercise missing/wrong attestations and tampered bytes, valid releases with
multiple refs/branches/architectures, and failed updates leaving the prior
catalog untouched. Run the complete affected publisher and registry test modules,
then use a disposable user-scope Flatpak remote to run `remote-ls` and a
no-deploy installation against the candidate without publishing it. Finally
verify the served endpoint after a separately authorized deployment. The local
registry tests alone do not establish this end-to-end behavior.
