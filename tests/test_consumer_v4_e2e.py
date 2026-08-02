from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from rotation.ai_contracts import SessionLocalRuntime
from rotation.consumer_v4 import (
    FORBIDDEN_BLIND_KEYS,
    export_consumer_v4,
    load_and_validate_consumer_v4,
)
from rotation.provenance import stable_hash
from rotation.validation import ContractError, load_json

ROOT = Path(__file__).resolve().parents[1]


def assessment_for(blind: dict) -> dict:
    return {
        "assessment_contract_version": "1.0",
        "generation_id": blind["generation_id"],
        "analysis_id": blind["analysis_id"],
        "blind_projection_sha256": stable_hash(blind),
        "theme_set_identity": blind["theme_set_identity"],
        "evidence_cutoff": blind["data_date"],
        "assessment_mode": "session_local",
        "themes": [{
            "theme_id": theme_id, "assessment_status": "assessed",
            "independent_ai_rank": rank, "confidence": 0.6, "evidence_refs": [],
        } for rank, theme_id in enumerate(blind["theme_ids"], 1)],
    }


def counter_for(assessment: dict) -> dict:
    return {
        "artifact_type": "COUNTER_THESIS",
        "generation_id": assessment["generation_id"],
        "analysis_id": assessment["analysis_id"],
        "ai_assessment_sha256": stable_hash(assessment),
        "themes": [{
            "theme_id": row["theme_id"],
            "strongest_counterevidence": ["market beta may explain the move"],
        } for row in assessment["themes"]],
        "exploratory_proposals": [],
    }


class ConsumerV4E2ETests(unittest.TestCase):
    def setUp(self):
        self.snapshot = load_json(ROOT / "tests" / "fixtures" / "latest_normal.json")

    def test_fixture_export_reload_and_ten_phase_session(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "v4"
            pointer = export_consumer_v4(self.snapshot, root)
            loaded = load_and_validate_consumer_v4(root)
            self.assertEqual(loaded["pointer"], pointer)
            self.assertEqual(set(loaded["packages"]), {
                "facts", "blind", "companies", "blind-handoff",
                "mechanical", "reconciliation-handoff",
            })
            rendered_blind = json.dumps({
                key: loaded["packages"][key]
                for key in ("facts", "blind", "companies", "blind-handoff")
            }, sort_keys=True)
            for forbidden in FORBIDDEN_BLIND_KEYS:
                self.assertNotIn(f'"{forbidden}"', rendered_blind)
            runtime = SessionLocalRuntime(loaded)
            with self.assertRaisesRegex(ContractError, "before AI assessment fixation"):
                runtime.reconciliation_inputs()
            phase1 = runtime.advance("更新")
            assessment = assessment_for(loaded["packages"]["blind"])
            runtime.fix_ai_assessment(assessment)
            changed = copy.deepcopy(assessment)
            changed["themes"][0]["confidence"] = 0.1
            with self.assertRaisesRegex(ContractError, "immutable"):
                runtime.fix_ai_assessment(changed)
            runtime.fix_counter_thesis(counter_for(assessment))
            phases = [phase1] + [runtime.advance("次") for _ in range(9)]
            self.assertEqual([row["phase"] for row in phases], list(range(1, 11)))
            self.assertTrue(runtime.state.completed)
            self.assertEqual(phases[-1]["ledger_status"], "not_persisted_session_local")
            self.assertFalse(phases[-1]["runtime_available"])
            with self.assertRaisesRegex(ContractError, "complete"):
                runtime.advance("次")

    def test_tamper_fails_closed(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "v4"
            export_consumer_v4(self.snapshot, root)
            loaded = load_and_validate_consumer_v4(root)
            generation_id = loaded["pointer"]["generation_id"]
            part = root / "generations" / generation_id / "blind" / "part-1.json"
            value = load_json(part)
            value["fragment"] += " "
            part.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ContractError):
                load_and_validate_consumer_v4(root)

    def test_remote_equivalent_copy_reloads(self):
        with tempfile.TemporaryDirectory() as name:
            root, copy_root = Path(name) / "v4", Path(name) / "reloaded"
            export_consumer_v4(self.snapshot, root)
            shutil.copytree(root, copy_root)
            self.assertEqual(load_and_validate_consumer_v4(root), load_and_validate_consumer_v4(copy_root))

    def test_exact_commands_only(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name) / "v4"
            export_consumer_v4(self.snapshot, root)
            runtime = SessionLocalRuntime(load_and_validate_consumer_v4(root))
            for command in ("更新してください", " 次", "next", ""):
                with self.assertRaises(ContractError):
                    runtime.advance(command)
            with self.assertRaisesRegex(ContractError, "start with 更新"):
                runtime.advance("次")


if __name__ == "__main__":
    unittest.main()
