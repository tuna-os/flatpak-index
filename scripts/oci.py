"""Minimal read-only OCI registry client used by the index scripts.

Only supports what the index needs: anonymous (or token-authenticated) pulls of
a manifest and its config blob, so the image's labels can be read back.
"""

import json
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


_HEAD_DIGEST_HEADER = "docker-content-digest"


def _curl_head(url, headers=(), attempts=4):
    """HEAD the URL; return the response headers as a lower-case dict.

    The registry echoes the digest a tag currently resolves to in the
    ``Docker-Content-Digest`` header, which is how a freshness check sees a
    publish that has moved a tag past the digest the index recorded.
    """
    cmd = ["curl", "-sSL", "-I", "--fail-with-body"]
    for header in headers:
        cmd += ["-H", header]
    cmd.append(url)
    last = None
    for attempt in range(attempts):
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and result.stdout.strip():
            headers_out = {}
            for chunk in result.stdout.split(b"\r\n"):
                line = chunk.decode("utf-8", "replace").strip()
                if ":" in line and not line.upper().startswith("HTTP"):
                    key, _, value = line.partition(":")
                    headers_out[key.strip().lower()] = value.strip()
            return headers_out
        last = result
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    stderr = (last.stderr or b"").decode("utf-8", "replace").strip()
    stdout = (last.stdout or b"").decode("utf-8", "replace").strip()
    raise RegistryError(f"HEAD {url} failed: rc={last.returncode} {stderr or stdout}")


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
        headers = (self._auth_header(repository), f"Accept: {MANIFEST_ACCEPT}")
        url = f"https://{self.host}/v2/{repository}/manifests/{reference}"
        return json.loads(_curl(url, headers))

    def blob(self, repository, digest):
        headers = (self._auth_header(repository),)
        url = f"https://{self.host}/v2/{repository}/blobs/{digest}"
        return json.loads(_curl(url, headers))

    def image_labels(self, repository, reference):
        """Return the config labels of the image at ``reference``."""
        manifest = self.manifest(repository, reference)
        if "config" not in manifest:
            raise RegistryError(
                f"{repository}@{reference} is a manifest list, not an image manifest"
            )
        config = self.blob(repository, manifest["config"]["digest"])
        return config.get("config", {}).get("Labels") or {}


    def reference_digest(self, repository, reference, architecture=None):
        """Return the digest the registry currently assigns to ``reference``.

        ``reference`` is a tag such as ``latest``. The served index records the
        digest a tag resolved to when it was published; resolving the tag again
        here shows whether a newer publish has moved it, which is how the
        freshness check detects an index that lags production.

        The served index stores a per-arch digest, so for a manifest list the
        digest of the sub-manifest for ``architecture`` is returned; for a
        single-arch manifest the tag's own digest is returned. Comparing the
        tag's current digest against the recorded one flags a moved tag.
        """
        headers = (self._auth_header(repository),)
        url = f"https://{self.host}/v2/{repository}/manifests/{reference}"
        body = json.loads(_curl(url, headers))
        if "manifests" in body:
            if architecture is None:
                raise RegistryError(
                    f"{repository}@{reference} is a manifest list, not an image manifest"
                )
            for sub in body["manifests"]:
                if sub.get("platform", {}).get("architecture") == architecture:
                    return sub["digest"]
            raise RegistryError(
                f"{repository}@{reference} has no {architecture} sub-manifest"
            )
        response_headers = _curl_head(url, headers)
        digest = response_headers.get(_HEAD_DIGEST_HEADER)
        if not digest:
            raise RegistryError(
                f"{repository}@{reference} response carried no "
                f"{_HEAD_DIGEST_HEADER} header"
            )
        return digest
