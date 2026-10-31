"""Minimal read-only OCI registry client used by the index scripts.

Only supports what the index needs: anonymous (or token-authenticated) pulls of
a manifest and its config blob, so the image's labels can be read back.
"""

import hashlib
import json
import re
import subprocess
import time
import urllib.parse

MANIFEST_ACCEPT = ",".join(
    [
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    ]
)

# Labels that must survive into index/static. Flatpak reads the org.flatpak.*
# labels to resolve and install a ref, and the org.freedesktop.appstream.*
# labels to build the remote's AppStream catalogue -- which is what gives
# software centres (Bazaar, GNOME Software, KDE Discover) an app name, summary,
# icon, licence, screenshots and release notes. Dropping the appstream labels
# leaves users looking at a bare application ID.
FLATPAK_LABEL_PREFIX = "org.flatpak."
APPSTREAM_LABEL_PREFIX = "org.freedesktop.appstream."

APPSTREAM_LABELS = (
    "org.freedesktop.appstream.appdata",
    "org.freedesktop.appstream.icon-64",
    "org.freedesktop.appstream.icon-128",
)


class RegistryError(RuntimeError):
    pass


def _validate_digest(digest):
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise RegistryError(f"Unsupported or invalid sha256 digest: {digest!r}")


def _check_digest(body, digest):
    """Check raw bytes against a canonical sha256 OCI digest before parsing."""
    _validate_digest(digest)
    actual = "sha256:" + hashlib.sha256(body).hexdigest()
    if actual != digest:
        raise RegistryError(f"Digest mismatch: expected {digest}, got {actual}")


def keep_label(name):
    """Return True for labels that belong in the published index."""
    return name.startswith(FLATPAK_LABEL_PREFIX) or name.startswith(APPSTREAM_LABEL_PREFIX)


def filter_labels(labels):
    return {k: v for k, v in (labels or {}).items() if keep_label(k)}


def _curl(url, headers=(), attempts=4):
    cmd = ["curl", "-sSL", "--fail-with-body"]
    for header in headers:
        cmd += ["-H", header]
    cmd.append(url)
    last = None
    for attempt in range(attempts):
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
        last = result
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    stderr = (last.stderr or b"").decode("utf-8", "replace").strip()
    stdout = (last.stdout or b"").decode("utf-8", "replace").strip()
    raise RegistryError(f"GET {url} failed: rc={last.returncode} {stderr or stdout}")


class Registry:
    """Reads manifests and config blobs from one OCI registry."""

    def __init__(self, registry_url, token=None):
        parsed = urllib.parse.urlparse(registry_url)
        self.host = parsed.netloc or parsed.path
        self.static_token = token
        self._tokens = {}

    def _auth_header(self, repository):
        if self.static_token:
            return f"Authorization: Bearer {self.static_token}"
        if repository not in self._tokens:
            url = (
                f"https://{self.host}/token"
                f"?scope=repository:{repository}:pull&service={self.host}"
            )
            payload = json.loads(_curl(url))
            token = payload.get("token") or payload.get("access_token")
            if not token:
                raise RegistryError(
                    f"{self.host} refused an anonymous pull token for {repository}: "
                    f"{json.dumps(payload)[:200]}"
                )
            self._tokens[repository] = token
        return f"Authorization: Bearer {self._tokens[repository]}"

    def manifest(self, repository, reference):
        if ":" in reference:
            _validate_digest(reference)
        headers = (self._auth_header(repository), f"Accept: {MANIFEST_ACCEPT}")
        url = f"https://{self.host}/v2/{repository}/manifests/{reference}"
        body = _curl(url, headers)
        # Tags are mutable and cannot be validated against their own name.
        # A digest reference, however, must match the exact response bytes.
        if ":" in reference:
            _check_digest(body, reference)
        return json.loads(body)

    def blob(self, repository, digest):
        # Reject unsupported or malformed descriptors before constructing a URL.
        _validate_digest(digest)
        headers = (self._auth_header(repository),)
        url = f"https://{self.host}/v2/{repository}/blobs/{digest}"
        body = _curl(url, headers)
        _check_digest(body, digest)
        return json.loads(body)

    def image_labels(self, repository, reference):
        """Return the config labels of the image at ``reference``."""
        manifest = self.manifest(repository, reference)
        if "config" not in manifest:
            raise RegistryError(
                f"{repository}@{reference} is a manifest list, not an image manifest"
            )
        config = self.blob(repository, manifest["config"]["digest"])
        return config.get("config", {}).get("Labels") or {}
