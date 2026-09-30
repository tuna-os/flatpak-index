# Observability & Telemetry Assessment: flatpak-index

This document defines the observability architecture, logging conventions, and telemetry stack guidelines for `flatpak-index`.

## Executive Summary

`flatpak-index` manages the index and validates AppStream metadata for Flatpak artifacts in TunaOS (`tuna-os/*`). It provides self-contained Python utilities (`scripts/update-index.py`, `scripts/enrich-index.py`, `scripts/oci.py`) used in automated CI/CD workflows and release pipelines.

---

## Telemetry Stack Audit & Status

### Backend Configuration
- **Status**: The repository uses no external telemetry backend (Operator Targets: open-source=none, kube-native=none, commercial=none).
- **Data Flow Policy**: Strict compliance with a policy that allows no off-box data export. No telemetry exporter, OTLP endpoint, or external agent communication is active or allowed without explicit operator configuration.

### Current Logging Architecture
- **Script Output**: Scripts now send diagnostic outputs, layout warnings, and missing AppStream label notifications via `print()` statements to `stdout` and `stderr` (`sys.stderr`).
- **Data Integrity**: Image entries and manifests in `index/static` carry OCI digests, architecture mappings, and AppStream label metadata (`org.freedesktop.appstream.*`).

---

## Observability Guidelines & Standards

### Structured Logging Recommendations
1. **Standardized Log Levels**: Transition script diagnostics from raw `print` statements to Python's standard `logging` library using structured log levels:
   - `INFO`: Index updates, manifest parse progress, tag merge operations.
   - `WARNING`: Non-fatal missing AppStream metadata (`org.freedesktop.appstream.appdata`).
   - `ERROR`: Invalid OCI layouts, missing `index.json`, missing required Flatpak labels (`org.flatpak.ref`, `org.flatpak.metadata`).
2. **Contextual Metadata**: Format log entries to include repository name (`--repo-name`), OCI digest, target architecture, and operation status.

### Tracing & Metrics Readiness (Future Roadmap)
- **OpenTelemetry Wiring**: When operators provide an OpenTelemetry backend, instrument index build and enrichment pipelines with bounded spans to trace:
  - `oci.layout.read`: Steps to parse the OCI directory layout and resolve blobs.
  - `index.merge`: Index entry insertion and deduplication.
  - `appstream.validate`: Metainfo and label completeness verification.
- **Metrics**: Instrument pipeline duration and validation error counters (`flatpak_index_build_duration_seconds`, `flatpak_index_validation_errors_total`).

---

## Governance & Compliance

- **Credentials & Privacy**: Absolute prohibition against logging credentials, access tokens, API keys, or full environment dumps.
- **Label Cardinality**: Attribute values and tags must remain strictly bounded to prevent metric cardinality explosion.
- **Hold-Gated Mode**: Authors submit all observability PRs in this repository in hold-gated mode; these PRs need human review before merge.
