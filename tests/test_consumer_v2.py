import copy
import tempfile
import unittest
from pathlib import Path

from rotation.consumer import (
    build_consumer_details,
    build_consumer_snapshot,
)
from rotation.consumer_v2 import (
    CONSUMER_V2_FILE_SIZE_LIMIT,
    _flatten_fragments,
    _pack_fragments,
    build_consumer_v2_payloads,
    consumer_v2_file_bytes,
    load_consumer_v2_file,
    reconstruct_fragments,
    validate_consumer_v2_payloads,
)
from rotation.provenance import canonical_bytes
from rotation.publication import publish_generation
from rotation.validation import ContractError, load_json
from scripts.export_consumer_v2 import export_consumer_v2
from scripts.generate_weekly import history_item
from tests.test_publication_contract import generation


class ConsumerV2Tests(unittest.TestCase):
    def setUp(self):
        self.latest = generation(
            "2026-07-17",
            "consumer-v2-tests",
        )
        (
            self.manifest,
            self.phase_chunks,
            self.detail_chunks,
        ) = build_consumer_v2_payloads(self.latest)

    def test_manifest_chunks_identity_size_and_lossless_reconstruction(self):
        self.assertEqual(
            self.manifest["consumer_contract_version"],
            "2.0",
        )
        self.assertLessEqual(
            len(canonical_bytes(self.manifest)),
            CONSUMER_V2_FILE_SIZE_LIMIT,
        )

        self.assertEqual(
            [
                item["phase"]
                for item in self.manifest["phase_inventory"]
            ],
            list(range(1, 7)),
        )
        self.assertEqual(
            [
                item["phase"]
                for item in self.manifest["detail_inventory"]
            ],
            list(range(1, 7)),
        )

        v1 = build_consumer_snapshot(self.latest)
        v1_details = build_consumer_details(self.latest)

        for kind, collection, inventory, expected_views in (
            (
                "phase",
                self.phase_chunks,
                self.manifest["phase_inventory"],
                v1["user_view"]["phases"],
            ),
            (
                "detail",
                self.detail_chunks,
                self.manifest["detail_inventory"],
                [
                    item["detail_view"]
                    for item in v1_details
                ],
            ),
        ):
            counts = {
                item["phase"]: item["part_count"]
                for item in inventory
            }

            for phase in range(1, 7):
                chunks = collection[phase]
                self.assertEqual(len(chunks), counts[phase])

                for part, chunk in enumerate(chunks, 1):
                    self.assertEqual(chunk["kind"], kind)
                    self.assertEqual(chunk["phase"], phase)
                    self.assertEqual(chunk["part"], part)
                    self.assertEqual(
                        chunk["part_count"],
                        len(chunks),
                    )
                    self.assertEqual(
                        chunk["source_identity"],
                        self.manifest["source_identity"],
                    )
                    self.assertLessEqual(
                        len(canonical_bytes(chunk)),
                        CONSUMER_V2_FILE_SIZE_LIMIT,
                    )

                fragments = [
                    fragment
                    for chunk in chunks
                    for fragment in chunk["fragments"]
                ]
                reconstructed = reconstruct_fragments(
                    fragments
                )
                self.assertEqual(
                    canonical_bytes(reconstructed),
                    canonical_bytes(
                        expected_views[phase - 1]
                    ),
                )

    def test_large_view_is_split_without_information_loss(self):
        v1 = build_consumer_snapshot(self.latest)
        view = {
            "items": [
                f"{index}:" + ("?" * 700)
                for index in range(12)
            ]
        }
        fragments = _flatten_fragments(view)
        chunks = _pack_fragments(
            v1_snapshot=v1,
            kind="detail",
            phase=4,
            fragments=fragments,
        )

        self.assertGreater(len(chunks), 1)

        for chunk in chunks:
            self.assertLessEqual(
                len(canonical_bytes(chunk)),
                CONSUMER_V2_FILE_SIZE_LIMIT,
            )

        exported_fragments = [
            fragment
            for chunk in chunks
            for fragment in chunk["fragments"]
        ]
        self.assertEqual(
            canonical_bytes(
                reconstruct_fragments(exported_fragments)
            ),
            canonical_bytes(view),
        )

    def test_deterministic_generation_and_tampering_rejection(self):
        rebuilt = build_consumer_v2_payloads(
            copy.deepcopy(self.latest)
        )

        self.assertEqual(
            canonical_bytes(self.manifest),
            canonical_bytes(rebuilt[0]),
        )

        for observed, expected in (
            (self.phase_chunks, rebuilt[1]),
            (self.detail_chunks, rebuilt[2]),
        ):
            for phase in range(1, 7):
                self.assertEqual(
                    [
                        canonical_bytes(item)
                        for item in observed[phase]
                    ],
                    [
                        canonical_bytes(item)
                        for item in expected[phase]
                    ],
                )

        tampered = copy.deepcopy(self.phase_chunks)
        value = tampered[1][0]["fragments"][0]["value"]
        if isinstance(value, str):
            tampered[1][0]["fragments"][0][
                "value"
            ] = value + "???"
        else:
            tampered[1][0]["fragments"][0][
                "value"
            ] = "???"

        with self.assertRaisesRegex(
            ContractError,
            "deterministic projection",
        ):
            validate_consumer_v2_payloads(
                self.manifest,
                tampered,
                self.detail_chunks,
                self.latest,
            )

    def test_file_reader_rejects_padding_and_oversize_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.json"
            raw = consumer_v2_file_bytes(self.manifest)
            path.write_bytes(raw)

            self.assertEqual(
                load_consumer_v2_file(path, "test manifest"),
                self.manifest,
            )

            path.write_bytes(raw + b" ")
            with self.assertRaisesRegex(
                ContractError,
                "canonical minified JSON",
            ):
                load_consumer_v2_file(path, "test manifest")

            path.write_bytes(
                raw + (b" " * CONSUMER_V2_FILE_SIZE_LIMIT)
            )
            with self.assertRaisesRegex(
                ContractError,
                "exceeds",
            ):
                load_consumer_v2_file(path, "test manifest")

    def test_exported_tree_is_exact_minified_and_below_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            publish_generation(
                output,
                self.latest,
                history_item(self.latest),
                {
                    "index_version": "1.0",
                    "records": [],
                },
            )

            destination = output / "consumer" / "v2"
            paths = export_consumer_v2(
                output,
                destination,
            )

            expected_count = (
                1
                + sum(
                    item["part_count"]
                    for item in self.manifest[
                        "phase_inventory"
                    ]
                )
                + sum(
                    item["part_count"]
                    for item in self.manifest[
                        "detail_inventory"
                    ]
                )
            )
            self.assertEqual(
                len(paths),
                expected_count,
            )

            actual_files = {
                path
                for path in destination.rglob("*")
                if path.is_file()
            }
            self.assertEqual(set(paths), actual_files)

            first_export = {}

            for path in sorted(actual_files):
                raw = path.read_bytes()
                value = load_json(path)

                self.assertEqual(
                    raw,
                    canonical_bytes(value) + b"\n",
                )
                self.assertLessEqual(
                    len(raw),
                    CONSUMER_V2_FILE_SIZE_LIMIT,
                )
                first_export[
                    path.relative_to(destination).as_posix()
                ] = raw

            export_consumer_v2(
                output,
                destination,
            )

            second_export = {
                path.relative_to(destination).as_posix():
                    path.read_bytes()
                for path in destination.rglob("*")
                if path.is_file()
            }
            self.assertEqual(
                first_export,
                second_export,
            )



if __name__ == "__main__":
    unittest.main()
