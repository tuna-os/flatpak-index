#!/usr/bin/env python3
"""Refresh approved Flatpak entries from public GHCR images, without publisher tokens.

Run in the index owner's repository with a reviewed policy. Never accept policy
or index paths from a publisher's dispatch payload. Requires skopeo on PATH.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "update_index", Path(__file__).with_name("update-index.py")
)
updater = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(updater)

ARCHES = {"amd64": "x86_64", "arm64": "aarch64"}
DIGEST = re.compile(r"sha256:([0-9a-f]{64})")
REPOSITORY = re.compile(r"tuna-os/[a-z0-9]+(?:[._-][a-z0-9]+)*")
TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")


def read_policy(path):
    sources = json.loads(path.read_text())
    if not isinstance(sources, list) or not sources:
        raise ValueError("Policy must be a nonempty list")
    seen = set()
    for source in sources:
        required = {"repository", "tag", "architecture", "ref"}
        if (not isinstance(source, dict) or not required <= set(source)
                or set(source) - required - {"tags"}):
            raise ValueError("Each source needs repository, tag, architecture and ref")
        repo, tag, arch, ref = (source[k] for k in (
            "repository", "tag", "architecture", "ref"
        ))
        if not all(isinstance(value, str) for value in (repo, tag, arch, ref)):
            raise ValueError("Policy values must be strings")
        if not REPOSITORY.fullmatch(repo) or not TAG.fullmatch(tag) or arch not in ARCHES:
            raise ValueError(f"Invalid source: {source}")
        tags = source.get("tags", [tag])
        if (not isinstance(tags, list) or not tags
                or any(not isinstance(item, str) or not TAG.fullmatch(item) for item in tags)
                or len(tags) != len(set(tags)) or tag not in tags):
            raise ValueError("Published tags must be unique valid aliases including the source tag")
        if not re.fullmatch(r"app/[A-Za-z_][A-Za-z0-9_.-]*/" + ARCHES[arch]
                            + r"/[A-Za-z0-9_.-]+", ref):
            raise ValueError(f"Invalid Flatpak ref for {arch}: {ref}")
        # A publisher must not claim another repository's application, even if
        # the GHCR repository name differs (as with the installer frontends).
        key = (arch, ref)
        if key in seen:
            raise ValueError(f"Duplicate application in policy: {key}")
        seen.add(key)
    return sources


def verify_blob(raw, digest):
    match = DIGEST.fullmatch(digest)
    if not match:
        raise ValueError(f"Expected a sha256 digest: {digest}")
    if hashlib.sha256(raw).hexdigest() != match[1]:
        raise ValueError(f"Blob digest mismatch: {digest}")
    return json.loads(raw)


def inspect(source, reference, config=False):
    command = [
        "skopeo", "--override-os", "linux", "--override-arch", source["architecture"],
        "inspect", "--raw", "--no-creds", "--tls-verify=true", "--retry-times", "3",
    ]
    if config:
        command.append("--config")
    return subprocess.run(command + [f"docker://ghcr.io/{source['repository']}{reference}"],
                          check=True, stdout=subprocess.PIPE).stdout


def pull_entry(source):
    # Fetch metadata only: downloading every application's layers each hour
    # would waste bandwidth. Resolve a tag once, then use immutable digests.
    raw = inspect(source, ":" + source["tag"])
    digest = "sha256:" + hashlib.sha256(raw).hexdigest()
    manifest = json.loads(raw)
    if "manifests" in manifest:
        candidates = [item for item in manifest["manifests"]
                      if item.get("platform", {}).get("os") == "linux"
                      and item.get("platform", {}).get("architecture") == source["architecture"]]
        if len(candidates) != 1:
            raise ValueError("Expected one approved Linux platform in manifest list")
        digest = candidates[0]["digest"]
        if not DIGEST.fullmatch(digest):
            raise ValueError("Expected a sha256 image digest")
        manifest = verify_blob(inspect(source, "@" + digest), digest)
    if manifest.get("mediaType") != "application/vnd.oci.image.manifest.v1+json":
        raise ValueError("Expected an OCI image manifest")
    config = verify_blob(inspect(source, "@" + digest, config=True), manifest["config"]["digest"])
    if config.get("os") != "linux" or config.get("architecture") != source["architecture"]:
        raise ValueError("Image platform does not match policy")
    entry = updater.build_image_entry(digest, config, source.get("tags", [source["tag"]]), True)
    if updater.app_ref(entry) != source["ref"]:
        raise ValueError("Image Flatpak ref does not match policy")
    return entry


def refresh(policy, index_file):
    sources = read_policy(policy)
    data = json.loads(index_file.read_text())
    if data.get("Registry") != "https://ghcr.io":
        raise ValueError("Only the public GHCR index is supported")
    # Policy is the authority for which repository may publish each ref.
    owners = {(s["architecture"], s["ref"]): s["repository"] for s in sources}
    for result in data["Results"]:
        for image in result["Images"]:
            owner = owners.get((image["Architecture"], updater.app_ref(image)))
            if owner is not None and owner != result["Name"]:
                raise ValueError("Existing application repository conflicts with policy")
    for source in sources:
        entry = pull_entry(source)
        updater.merge_entry(data, source["repository"], entry)
    # No partial publication when a later source fails. Replace atomically on
    # the same filesystem, and remove the temporary file even if writing fails.
    candidate = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=index_file.parent, delete=False) as stream:
            candidate = Path(stream.name)
            stream.write(json.dumps(data, indent=2) + "\n")
        candidate.chmod(index_file.stat().st_mode & 0o777)
        os.replace(candidate, index_file)
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--index-file", type=Path, required=True)
    args = parser.parse_args()
    refresh(args.policy, args.index_file)


if __name__ == "__main__":
    main()
