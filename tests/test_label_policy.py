"""Contract test pinning scripts/update-index.py's label filter to scripts/oci.py's.

Which labels survive into the Flatpak index is one rule with two independent
implementations:

- scripts/update-index.py (vendored into application repos, must stay a
  single standard-library-only file, so it cannot import oci.py) decides what
  *enters* the index at publish time.
- scripts/oci.py's keep_label()/filter_labels() (used by enrich-index.py)
  decides what a published entry *should have carried* at audit time, via
  check-metadata.yml against the live remote.

The two copies are not merged here because update-index.py's single-file
constraint is a real, documented requirement (AGENTS.md, CONTRIBUTING.md) --
not an oversight. Instead, this file asserts the two declarations agree,
so a change to one that silently diverges from the other fails here instead
of as an asymmetric publish/audit mismatch:

- publisher narrower than auditor: enrich-index.py reports a label the
  publisher never kept as a "problem", and republishing can never clear it
- auditor narrower than publisher: the audit blesses an index entry that
  software centres cannot render

See tuna-os/flatpak-index#104.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import oci  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "update_index", ROOT / "scripts" / "update-index.py"
)
update_index = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(update_index)

# Label names to classify through both filters. Includes the exact near-misses
# that a sloppy edit to either copy turns into a silent divergence: a prefix
# written without its trailing dot, and a lookalike that should NOT match.
LABEL_CORPUS = (
    "org.flatpak.ref",
    "org.flatpak.metadata",
    "org.flatpak.commit",
    "org.freedesktop.appstream.appdata",
    "org.freedesktop.appstream.icon-64",
    "org.freedesktop.appstream.icon-128",
    "org.flatpakish.ref",  # must NOT match "org.flatpak" without its dot
    "org.freedesktop.appstreamx.appdata",  # must NOT match without the dot
    "org.opencontainers.image.created",
    "maintainer",
)


class LabelPolicyContractTests(unittest.TestCase):
    def test_prefixes_match_as_a_set(self):
        """The two declarations name the same prefixes, independent of order."""
        self.assertEqual(
            set(update_index.KEEP_LABEL_PREFIXES),
            {oci.FLATPAK_LABEL_PREFIX, oci.APPSTREAM_LABEL_PREFIX},
        )

    def test_filters_classify_the_corpus_identically(self):
        """Every label in the corpus is kept-or-dropped the same way by both."""
        for name in LABEL_CORPUS:
            publisher_keeps = name.startswith(update_index.KEEP_LABEL_PREFIXES)
            auditor_keeps = oci.keep_label(name)
            self.assertEqual(
                publisher_keeps,
                auditor_keeps,
                f"{name!r}: publisher keeps={publisher_keeps}, auditor keeps={auditor_keeps}",
            )

    def test_filter_labels_functions_agree_on_the_corpus(self):
        """filter_labels() in both modules keeps the same subset of a mixed dict."""
        labels = {name: "x" for name in LABEL_CORPUS}
        self.assertEqual(
            set(update_index.filter_labels(labels)),
            set(oci.filter_labels(labels)),
        )

    def test_auditor_appstream_labels_are_all_publisher_kept(self):
        """check-metadata.yml cannot demand a label publication would drop."""
        for name in oci.APPSTREAM_LABELS:
            self.assertTrue(
                name.startswith(update_index.KEEP_LABEL_PREFIXES),
                f"{name!r} is in oci.APPSTREAM_LABELS but update-index.py's "
                "KEEP_LABEL_PREFIXES would filter it out of the published index",
            )

    def test_both_copies_list_the_same_appstream_labels(self):
        self.assertEqual(set(update_index.APPSTREAM_LABELS), set(oci.APPSTREAM_LABELS))

    def test_required_labels_survive_both_filters(self):
        """REQUIRED_LABELS must come through update-index.py's own filter too --
        otherwise the publisher's own output would be missing a label it just
        validated as present on the source image."""
        for name in update_index.REQUIRED_LABELS:
            self.assertTrue(
                name.startswith(update_index.KEEP_LABEL_PREFIXES),
                f"{name!r} is required but update-index.py's own filter drops it",
            )
            self.assertTrue(
                oci.keep_label(name),
                f"{name!r} is required but the auditor's filter drops it",
            )


if __name__ == "__main__":
    unittest.main()
