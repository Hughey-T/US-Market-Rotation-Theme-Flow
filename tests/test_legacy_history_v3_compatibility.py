import tempfile
import unittest
from pathlib import Path

from rotation.provenance import snapshot_source_hash
from rotation.publication import load_current_generation, publish_generation
from rotation.validation import ContractError
from scripts.generate_weekly import history_item
from tests.test_publication_contract import generation


LEGACY_THEME_HISTORY_FIELDS = {
    "equal_weight_rel_spy_4w",
    "advance_count_4w",
    "above_50dma_count",
    "pct_above_50dma",
    "volume_ratio_20d_60d",
}


def legacy_history_item(snapshot: dict) -> dict:
    item = history_item(snapshot)
    item["themes"] = {
        theme_id: {
            field: value
            for field, value in theme.items()
            if field in LEGACY_THEME_HISTORY_FIELDS
        }
        for theme_id, theme in item["themes"].items()
    }
    return item


class LegacyHistoryV3CompatibilityTests(unittest.TestCase):
    def test_pre_v3_current_generation_accepts_legacy_history_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            snapshot = generation("2026-07-23", "legacy-history")
            snapshot.pop("v3_inputs", None)
            snapshot["meta"]["source_sha256"] = snapshot_source_hash(snapshot)

            pointer = publish_generation(
                output,
                snapshot,
                legacy_history_item(snapshot),
                {"index_version": "1.0", "records": []},
            )

            current = load_current_generation(output)
            self.assertEqual(current[0], pointer)
            self.assertEqual(current[3], snapshot)
            self.assertNotIn("candidate_bucket", current[4]["themes"][next(iter(current[4]["themes"]))])

    def test_v3_generation_still_requires_extended_history_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            snapshot = generation("2026-07-30", "v3-history")
            self.assertIn("v3_inputs", snapshot)
            item = history_item(snapshot)
            extended = next(theme for theme in item["themes"].values() if "candidate_bucket" in theme)
            del extended["candidate_bucket"]

            with self.assertRaisesRegex(ContractError, "history semantic mismatch"):
                publish_generation(
                    output,
                    snapshot,
                    item,
                    {"index_version": "1.0", "records": []},
                )


if __name__ == "__main__":
    unittest.main()
