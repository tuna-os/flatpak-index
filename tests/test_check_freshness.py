"""Unit tests for scripts/check-freshness.py.

The network resolver is replaced by an in-memory one, so evaluate() and main()
run fast, offline and deterministically while still exercising the real
classification and CLI logic.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("check_freshness", SCRIPTS / "check-freshness.py")
check_freshness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_freshness)

APPDATA = "<component><screenshots><screenshot>x</screenshot></screenshots></component>"


def make_index(registry="https://ghcr.io", entries=()):
    """Build a served-index document from (repo, arch, digest, tags, labels) tuples."""
    results = []
    for repo, arch, digest, tags, labels in entries:
        results.append(
            {
                "Name": repo,
                "Images": [
                    {
                        "Digest": digest,
                        "OS": "linux",
                        "Architecture": arch,
                        "Tags": tags,
                        "Labels": labels,
                    }
                ],
            }
        )
    return {"Registry": registry, "Results": results}


def full_labels():
    return {
        "org.flatpak.commit": "abc",
        "org.freedesktop.appstream.appdata": APPDATA,
        "org.freedesktop.appstream.icon-64": "i64",
        "org.freedesktop.appstream.icon-128": "i128",
    }


class FakeResolver:
    """Maps (repository, tag, architecture) to the digest the registry serves.

    A value of None means the tag no longer resolves (uninstallable).
    """

    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def __call__(self, repository, tag, architecture):
        self.calls.append((repository, tag, architecture))
        return self.mapping.get((repository, tag, architecture))



def digest(letter):
    return f"sha256:{letter * 64}"


class EvaluateTests(unittest.TestCase):
    def test_fresh_entry_with_full_metadata(self):
        served = digest("a")
        resolver = FakeResolver({("tuna-os/mariner", "latest", "amd64"): served})
        index = make_index(
            entries=[("tuna-os/mariner", "amd64", served, ["latest"], full_labels())]
        )

        results = check_freshness.evaluate(index, resolver)

        self.assertEqual(len(results), 1)
        entry = results[0]
        self.assertFalse(entry.stale)
        self.assertFalse(entry.uninstallable)
        self.assertFalse(entry.missing_metadata)
        self.assertEqual(entry.current_digest, served)

    def test_stale_when_registry_tag_moved(self):
        served = digest("a")
        resolver = FakeResolver({("tuna-os/mariner", "latest", "amd64"): digest("b")})
        index = make_index(
            entries=[("tuna-os/mariner", "amd64", served, ["latest"], full_labels())]
        )

        entry = check_freshness.evaluate(index, resolver)[0]

        self.assertTrue(entry.stale)
        self.assertEqual(entry.current_digest, digest("b"))

    def test_uninstallable_when_tag_no_longer_resolves(self):
        served = digest("a")
        resolver = FakeResolver({})  # tag absent -> None
        index = make_index(
            entries=[("tuna-os/mariner", "amd64", served, ["latest"], full_labels())]
        )

        entry = check_freshness.evaluate(index, resolver)[0]

        self.assertTrue(entry.uninstallable)
        self.assertIsNone(entry.current_digest)
        self.assertFalse(entry.stale)

    def test_missing_metadata_flagged(self):
        served = digest("a")
        resolver = FakeResolver({("tuna-os/letters", "latest", "amd64"): served})
        labels = {"org.flatpak.commit": "abc"}  # no appstream labels
        index = make_index(
            entries=[("tuna-os/letters", "amd64", served, ["latest"], labels)]
        )

        entry = check_freshness.evaluate(index, resolver)[0]

        self.assertTrue(entry.missing_metadata)

    def test_no_tags_is_neither_stale_nor_uninstallable(self):
        # Without tags there is nothing to re-resolve, so freshness cannot be
        # judged; the entry is not reported as a problem on that account.
        served = digest("a")
        resolver = FakeResolver({})
        index = make_index(
            entries=[("tuna-os/tables", "amd64", served, [], full_labels())]
        )

        entry = check_freshness.evaluate(index, resolver)[0]

        self.assertFalse(entry.stale)
        self.assertFalse(entry.uninstallable)

    def test_each_architecture_classified_independently(self):
        served = digest("a")
        resolver = FakeResolver(
            {
                ("tuna-os/mariner", "latest", "amd64"): served,
                ("tuna-os/mariner", "latest", "arm64"): digest("b"),
            }
        )
        index = make_index(
            entries=[
                ("tuna-os/mariner", "amd64", served, ["latest"], full_labels()),
                ("tuna-os/mariner", "arm64", digest("z"), ["latest"], full_labels()),
            ]
        )

        results = check_freshness.evaluate(index, resolver)

        by_arch = {r.label: r for r in results}
        self.assertFalse(by_arch["tuna-os/mariner (amd64)"].stale)
        self.assertTrue(by_arch["tuna-os/mariner (arm64)"].stale)


class SummarizeTests(unittest.TestCase):
    def test_splits_into_three_problem_lists(self):
        results = [
            check_freshness.EntryResult("a (amd64)", digest("a"), digest("a"), False, False, False),
            check_freshness.EntryResult("b (amd64)", digest("b"), digest("c"), True, False, False),
            check_freshness.EntryResult("c (amd64)", digest("d"), None, False, True, False),
            check_freshness.EntryResult("d (amd64)", digest("e"), digest("e"), False, False, True),
        ]

        stale, uninstallable, missing_metadata = check_freshness.summarize(results)

        self.assertEqual([r.label for r in stale], ["b (amd64)"])
        self.assertEqual([r.label for r in uninstallable], ["c (amd64)"])
        self.assertEqual([r.label for r in missing_metadata], ["d (amd64)"])


class ShortDigestTests(unittest.TestCase):
    def test_truncates_long_payload(self):
        digest = "sha256:" + "a" * 64
        short = check_freshness._short_digest(digest)
        self.assertTrue(short.startswith("aaaaaaa"))
        self.assertTrue(short.endswith("aaaa"))
        self.assertIn("…", short)

    def test_unresolved_reports_as_such(self):
        self.assertEqual(check_freshness._short_digest(None), "(unresolved)")


class MainTests(unittest.TestCase):
    """Cover main() in scripts/check-freshness.py.

    The network boundary (_registry_resolver) is patched to return an in-memory
    resolver and argv is patched, so main() runs offline and deterministically.
    """

    def _run(self, index, resolver):
        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            json.dump(index, tmp)
            tmp_path = Path(tmp.name)
        try:
            with patch.object(check_freshness, "_registry_resolver") as mock_resolver:
                mock_resolver.return_value = resolver
                with patch("sys.argv", ["check-freshness.py", str(tmp_path), "--check"]):
                    return check_freshness.main()
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_main_exits_zero_when_fresh(self):
        served = digest("a")
        index = make_index(
            entries=[("tuna-os/mariner", "amd64", served, ["latest"], full_labels())]
        )
        resolver = FakeResolver({("tuna-os/mariner", "latest", "amd64"): served})
        self.assertEqual(self._run(index, resolver), 0)

    def test_main_exits_nonzero_when_stale(self):
        served = digest("a")
        index = make_index(
            entries=[("tuna-os/mariner", "amd64", served, ["latest"], full_labels())]
        )
        resolver = FakeResolver({("tuna-os/mariner", "latest", "amd64"): digest("b")})
        self.assertEqual(self._run(index, resolver), 1)

    def test_main_exits_nonzero_when_uninstallable(self):
        served = digest("a")
        index = make_index(
            entries=[("tuna-os/mariner", "amd64", served, ["latest"], full_labels())]
        )
        self.assertEqual(self._run(index, FakeResolver({})), 1)


if __name__ == "__main__":
    unittest.main()
