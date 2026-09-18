# Runbook: Flatpak Index Catalog Build & Validation Failures

## Operational Overview

This runbook covers diagnostic and remediation steps when catalog generation or validation fails in `flatpak-index`.

---

## Escalation Trigger

- GitHub Actions workflow `tests.yml` fails on `main`.
- `scripts/enrich-index.py` reports unparseable AppStream metadata or broken catalog entries.
- Alert/Notification: Catalog integrity drift detected between `index/static` OCI labels and expected Flatpak metadata.

---

## Diagnostic Steps

1. **Inspect CI Run Logs**:
   - Locate the failed workflow run in GitHub Actions for `tuna-os/flatpak-index`.
   - Inspect output step `pytest` or `enrich-index.py`.

2. **Run Local Validation**:
   - Clone the repo and set up Python test environment:
     ```bash
     python3 -m unittest discover tests/
     ```
   - Execute `enrich-index.py` against `index/static`:
     ```bash
     python3 scripts/enrich-index.py index/static
     ```

3. **Verify AppStream Metadata Syntax**:
   - Check if any app metadata in `index/static` contains invalid XML or missing required OCI labels (`org.flatpak.metadata`, `org.freedesktop.appstream.appdata`).

---

## Remediation Steps

1. **Fix Broken App Stream Labels**:
   - If an entry in `index/static` has broken XML, edit the target JSON file under `index/static`.
   - Ensure `org.freedesktop.appstream.appdata` label values are properly escaped XML strings.

2. **Re-run Test Suite**:
   ```bash
   python3 -m unittest discover tests/
   ```

3. **Validate Catalog Output**:
   - Confirm all tests pass locally before opening a pull request.
