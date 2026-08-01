import unittest
from unittest.mock import patch

from rotation.consumer_v2 import _flatten_fragments
from rotation.consumer_v3 import (
    MAX_PHASE_FRAGMENTS,
    _chunks,
    reconstruct_fragments,
)
from rotation.consumer_v3_compact import (
    FRAGMENT_TARGET_BYTES,
    compact_fragments,
)
from rotation.provenance import canonical_bytes
from rotation.validation import ContractError


class ConsumerV3FragmentCompactionTests(unittest.TestCase):
    @staticmethod
    def identity():
        return {
            "analysis_id": "a" * 64,
            "generation_id": "b" * 64,
            "run_id": "c" * 64,
            "source_commit": "d" * 40,
            "source_sha256": "e" * 64,
            "data_date": "2026-08-01",
            "status": "success",
            "generated_at": "2026-08-01T00:00:00Z",
            "valid_until": "2026-08-08T00:00:00Z",
            "hard_stop_after": "2026-08-15T00:00:00Z",
            "timezone": "UTC",
        }

    @staticmethod
    def production_sized_phase():
        assessments = []
        for theme_index in range(40):
            assessments.append(
                {
                    "theme_id": f"theme_{theme_index:02d}",
                    "theme_display_name": f"Theme {theme_index:02d}",
                    "display_metric": {
                        f"metric_{metric_index:02d}": (
                            theme_index + metric_index
                        )
                        / 1000
                        for metric_index in range(35)
                    },
                    "threshold_assessment": {
                        f"flag_{flag_index:02d}": flag_index % 2 == 0
                        for flag_index in range(10)
                    },
                    "history": [
                        {
                            "week": week,
                            "value": (theme_index + week) / 100,
                        }
                        for week in range(4)
                    ],
                }
            )
        return {
            "phase": 1,
            "data_date_display": "2026-08-01",
            "generated_at_display": "2026-08-01T00:00:00Z",
            "analysis_mode_display": "trend",
            "flow_notice": "observed price and breadth flow proxy",
            "coverage": {
                "configured_theme_count": 40,
                "assessed_theme_count": 40,
            },
            "theme_assessments": assessments,
        }

    def test_large_phase_compacts_without_information_loss(self):
        view = self.production_sized_phase()
        leaf_fragments = _flatten_fragments(view)
        self.assertGreater(len(leaf_fragments), MAX_PHASE_FRAGMENTS)

        compact = compact_fragments(view)
        self.assertLessEqual(len(compact), MAX_PHASE_FRAGMENTS)
        self.assertTrue(
            all(
                len(canonical_bytes(fragment)) <= FRAGMENT_TARGET_BYTES
                for fragment in compact
            )
        )

        chunks = _chunks(view, self.identity(), "phase", 1)
        fragments = [
            fragment
            for chunk in chunks
            for fragment in chunk["fragments"]
        ]
        self.assertEqual(reconstruct_fragments(fragments), view)
        self.assertLessEqual(len(chunks), 8)

    def test_fragment_limit_error_names_kind_phase_and_count(self):
        fragments = [
            {"field": f"/items/{index}", "value": index}
            for index in range(MAX_PHASE_FRAGMENTS + 1)
        ]
        with patch(
            "rotation.consumer_v3_compact.compact_fragments",
            return_value=fragments,
        ):
            with self.assertRaisesRegex(
                ContractError,
                r"phase fragment limit exceeded for phase 4: "
                r"1001 > 1000",
            ):
                _chunks({}, self.identity(), "phase", 4)


if __name__ == "__main__":
    unittest.main()
