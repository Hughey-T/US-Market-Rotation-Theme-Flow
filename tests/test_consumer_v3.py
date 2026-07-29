import copy, tempfile, unittest
from pathlib import Path
from rotation.consumer_v3 import build_consumer_v3, reconstruct_fragments, validate_consumer_v3
from rotation.validation import ContractError
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

if __name__ == "__main__": unittest.main()
