# Flatpak Index Observability Assessment & Stack Guidelines

## Executive Summary

`flatpak-index` provides static index definitions, OCI index generation scripts (`scripts/update-index.py`, `scripts/enrich-index.py`, `scripts/oci.py`), and Flatpak repository metadata for `tuna-os`. Because it runs primarily as static assets served over HTTPS or built via GitHub Actions CI/CD pipelines, no backend exporter (Prometheus, OpenTelemetry Collector) is currently deployed.

This document outlines the current observability assessment, telemetry capabilities, service level objectives (SLOs), and recommended stack guidelines without introducing unconfirmed backend exporters or external data flows.

---

## 1. Observability Assessment

| Dimension | Current State | Target State | Gap / Action Items |
| :--- | :--- | :--- | :--- |
| **Metrics** | Local script validation output and GitHub Actions step timings | Prometheus/OpenTelemetry metrics for index sync & OCI manifest publishing | Implement pipeline metric emission upon backend infrastructure confirmation |
| **Logging** | Standard output/error logs from python scripts (`scripts/*.py`) and CI step logs | Structured JSON logging with severity levels for index parsing errors | Standardize script logging output for catalog drift detection |
| **Tracing** | N/A (Static repository and CI jobs) | Distributed tracing for catalog generation pipelines | Not applicable for current batch CLI index scripts |
| **Alerting** | GitHub Actions Workflow Failure Notifications | Automated alerts on catalog digest drift and unparseable AppStream metadata | Configure alerting rules for catalog build pipeline failures |

---

## 2. Service Level Objectives (SLOs) & SLIs

### SLO 1: AppStream Metadata Validity Rate
- **Definition**: The percentage of catalog entries in `index/static` and generated OCI labels that parse into valid AppStream XML components.
- **SLI**: `(valid_appstream_catalogs / total_published_apps) * 100%`
- **Target**: **99.9%** valid over a 30-day rolling window.

### SLO 2: Catalog Build & Validation Pipeline Success
- **Definition**: Successful execution of `scripts/enrich-index.py` and `tests/test_index.py` during CI runs on repository main branch updates.
- **SLI**: `(successful_ci_index_builds / total_ci_index_builds) * 100%`
- **Target**: **99.5%** pipeline success rate.

---

## 3. Recommended Stack Guidelines

1. **No Unconfirmed Backend Exporters**:
   - In compliance with Operations policies, no backend metric exporter or external telemetry data flow is enabled until operator confirmation.
2. **Local & CI Diagnostic Logging**:
   - All python index tools (`enrich-index.py`, `update-index.py`) should output key metadata parsing errors to stderr using clear diagnostic formats.
3. **Future Infrastructure Integration**:
   - When a telemetry collector (e.g. OpenTelemetry or Prometheus Pushgateway) is provisioned for tuna-os infrastructure pipelines, index generation job metrics (duration, total apps, missing screenshot counts) should be exported via standard HTTP push endpoints.
