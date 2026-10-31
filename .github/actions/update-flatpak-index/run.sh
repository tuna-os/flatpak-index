#!/usr/bin/env bash
set -euo pipefail

# Resolve the publisher from this action's release, never from the app checkout.
action_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
args=(--oci-dir "$OCI_DIR" --index-file "$INDEX_FILE"
      --repo-name "$REPO_NAME" --registry "$REGISTRY")
case "$REQUIRE_APPSTREAM" in
  true) args+=(--require-appstream) ;;
  false) ;;
  *) echo '::error::require-appstream must be true or false' >&2; exit 1 ;;
esac
read -r -a tags <<< "$TAGS"
if [ "${#tags[@]}" -eq 0 ]; then
  echo '::error::tags must contain at least one tag' >&2
  exit 1
fi
python3 "$action_dir/../../../scripts/update-index.py" "${args[@]}" --tags "${tags[@]}"
