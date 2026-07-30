import copy, tempfile, unittest
from pathlib import Path
from rotation.consumer_v3 import build_consumer_v3, reconstruct_fragments, validate_consumer_v3, canonical_file_bytes, sha256, evaluate_generation_gate
from rotation.validation import ContractError
from rotation.provenance import canonical_bytes
from rotation.validation import load_json, validate_schema
from rotation.consumer_v3 import PHASE_SCHEMA, POINTER_SCHEMA
from scripts.export_consumer_v3 import export_consumer_v3
from tests.test_publication_contract import generation
from rotation.publication import publish_generation
from scripts.generate_weekly import history_item

class ConsumerV3Tests(unittest.TestCase):
    def setUp(self):
        self.latest = generation("2026-07-17", "consumer-v3-tests")
        self.pointer, self.manifest, self.phases, self.details, self.handoffs = build_consumer_v3(self.latest)

    def test_integrity_and_inventory(self):
        validate_consumer_v3(self.pointer, self.manifest, self.phases, self.details, self.handoffs)
        self.assertEqual([x["phase"] for x in self.manifest["phase_inventory"]], list(range(1, 7)))
        self.assertTrue(all(x["part_count"] <= 8 for x in self.manifest["phase_inventory"]))
        for phase,detail in zip(self.manifest["phase_inventory"],self.manifest["detail_inventory"]):
            self.assertLessEqual(phase["fragment_count"]+detail["fragment_count"],1000)

    def test_tamper_fails_closed(self):
        phases = copy.deepcopy(self.phases); phases[1][0]["fragments"][0]["value"] = "tampered"
        with self.assertRaisesRegex(ContractError, "E_CHUNK_HASH"):
            validate_consumer_v3(self.pointer, self.manifest, phases, self.details)

    def test_strict_reconstruction(self):
        with self.assertRaises(ContractError): reconstruct_fragments([{"field":"/a/1", "value":"x"}])
        with self.assertRaises(ContractError): reconstruct_fragments([{"field":"/a", "value":1},{"field":"/a", "value":2}])
        with self.assertRaises(ContractError): reconstruct_fragments([{"field":"/", "value":{}},{"field":"/a", "value":1}])

    def test_immutable_export(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); publish_generation(root / "output", self.latest, history_item(self.latest), {"index_version":"1.0", "records":[]})
            destination = root / "consumer" / "v3"; export_consumer_v3(root / "output", destination)
            export_consumer_v3(root / "output", destination)
            manifest = destination / "generations" / self.pointer["generation_id"] / "manifest.json"
            manifest.write_text("{}")
            with self.assertRaisesRegex(ContractError, "immutable generation collision"):
                export_consumer_v3(root / "output", destination)

    def test_two_offline_exports_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); publish_generation(root/"output",self.latest,history_item(self.latest),{"index_version":"1.0","records":[]})
            first=root/"first"/"v3"; second=root/"second"/"v3"
            export_consumer_v3(root/"output",first); export_consumer_v3(root/"output",second)
            one={p.relative_to(first):p.read_bytes() for p in first.rglob("*") if p.is_file()}
            two={p.relative_to(second):p.read_bytes() for p in second.rglob("*") if p.is_file()}
            self.assertEqual(one,two)

    def test_pointer_phase_and_mode_contracts_fail_closed(self):
        bad=copy.deepcopy(self.pointer); bad["unexpected"]=1
        with self.assertRaises(ContractError): validate_schema(bad,POINTER_SCHEMA,"pointer")
        phase6=copy.deepcopy(self.phases[6]); phase6[0]["fragments"].append({"field":"/companies","value":[]})
        with self.assertRaises(ContractError): validate_consumer_v3(self.pointer,self.manifest,{**self.phases,6:phase6},self.details,self.handoffs)
        manifest=copy.deepcopy(self.manifest); manifest["presentation"]["analysis_mode"]="trend"
        pointer=copy.deepcopy(self.pointer); pointer["generation_manifest_sha256"]=sha256(canonical_file_bytes(manifest))
        with self.assertRaises(ContractError): validate_consumer_v3(pointer,manifest,self.phases,self.details,self.handoffs)

    def test_validity_boundaries_and_hard_stop(self):
        self.assertEqual(evaluate_generation_gate(self.manifest,"2026-07-20T00:00:00Z")["status"],"fresh")
        self.assertEqual(evaluate_generation_gate(self.manifest,"2026-07-23T00:00:00Z")["status"],"stale_but_displayable")
        self.assertEqual(evaluate_generation_gate(self.manifest,"2026-07-25T00:00:01Z")["status"],"hard_stop")

    def test_coordinated_manifest_and_chunk_tamper_still_fails_schema(self):
        manifest=copy.deepcopy(self.manifest); phases=copy.deepcopy(self.phases); pointer=copy.deepcopy(self.pointer)
        chunk=phases[1][0]; chunk["unexpected_metadata"]="tampered"
        raw=canonical_file_bytes(chunk); part=manifest["phase_inventory"][0]["parts"][0]
        manifest["phase_inventory"][0]["total_bytes"] += len(raw)-part["bytes"]
        part.update(bytes=len(raw),sha256=sha256(raw))
        pointer["generation_manifest_sha256"]=sha256(canonical_file_bytes(manifest))
        with self.assertRaises(ContractError): validate_consumer_v3(pointer,manifest,phases,self.details,self.handoffs)

    def test_remote_kind_part_and_combined_byte_limits(self):
        manifest=copy.deepcopy(self.manifest); pointer=copy.deepcopy(self.pointer)
        item=manifest["phase_inventory"][0]; item["part_count"]=9
        item["parts"]=[{"part":i,"bytes":1,"sha256":"a"*64} for i in range(1,10)]
        pointer["generation_manifest_sha256"]=sha256(canonical_file_bytes(manifest))
        with self.assertRaises(ContractError): validate_consumer_v3(pointer,manifest,self.phases,self.details,self.handoffs)
        manifest=copy.deepcopy(self.manifest); pointer=copy.deepcopy(self.pointer)
        manifest["phase_inventory"][0]["total_bytes"]=80*1024; manifest["detail_inventory"][0]["total_bytes"]=60*1024
        pointer["generation_manifest_sha256"]=sha256(canonical_file_bytes(manifest))
        with self.assertRaisesRegex(ContractError,"combined phase byte"): validate_consumer_v3(pointer,manifest,self.phases,self.details,self.handoffs)

    def test_pointer_path_must_match_generation_id(self):
        pointer=copy.deepcopy(self.pointer); pointer["generation_manifest_path"]=f"generations/{'b'*64}/manifest.json"
        with self.assertRaisesRegex(ContractError,"E_GENERATION_IDENTITY"): validate_consumer_v3(pointer,self.manifest,self.phases,self.details,self.handoffs)

    def test_phase_schema_rejects_missing_wrong_extra_and_cross_phase(self):
        from rotation.analysis_v3 import build_authoritative_v3
        values=build_authoritative_v3(self.latest)["phases"]
        for phase,mutation in (
            (5,lambda x:x[5].pop("companies")),
            (5,lambda x:x[5].__setitem__("companies",{})),
            (5,lambda x:x[5].__setitem__("unexpected",True)),
            (6,lambda x:x[6].__setitem__("companies",[])),
        ):
            changed=copy.deepcopy(values); mutation(changed)
            with self.assertRaises(ContractError): validate_schema(changed[phase],PHASE_SCHEMA,"phase")
        assessment=copy.deepcopy(values[1]["theme_assessments"][0]); field=assessment["fundamental_confirmation"]["fields"]["revenue_growth"]
        for mutation in (
            lambda x:x.update(status="available",value=None,as_of=None,confirmation=True),
            lambda x:x.update(status="not_available",confirmation=True),
            lambda x:x.update(unknown=True),
        ):
            changed=copy.deepcopy(values[1]); target=changed["theme_assessments"][0]["fundamental_confirmation"]["fields"]["revenue_growth"]; mutation(target)
            with self.assertRaises(ContractError): validate_schema(changed,PHASE_SCHEMA,"phase1 fundamental")

if __name__ == "__main__": unittest.main()
