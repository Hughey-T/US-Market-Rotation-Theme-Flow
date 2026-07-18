"""Deterministic small-payload Custom GPT consumer contract 2.0."""
from __future__ import annotations

import copy
from pathlib import Path

from .consumer import build_consumer_details, build_consumer_snapshot
from .provenance import canonical_bytes
from .validation import ContractError, load_json, validate_schema


CONSUMER_V2_CONTRACT_VERSION = "2.0"
CONSUMER_V2_FILE_SIZE_LIMIT = 4 * 1024
CONSUMER_V2_CHUNK_TARGET = 3500
CONSUMER_V2_TEXT_FRAGMENT_LIMIT = 900

SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
CONSUMER_V2_MANIFEST_SCHEMA = load_json(
    SCHEMA_ROOT / "consumer_manifest_v2.schema.json"
)
CONSUMER_V2_CHUNK_SCHEMA = load_json(
    SCHEMA_ROOT / "consumer_chunk_v2.schema.json"
)


def consumer_v2_file_bytes(value: dict) -> bytes:
    '''Return the exact permitted bytes for one v2 JSON file.'''
    return canonical_bytes(value) + b"\n"


def load_consumer_v2_file(path: Path, label: str) -> dict:
    '''Load one size-bounded canonical v2 JSON file.'''
    raw = path.read_bytes()
    if len(raw) > CONSUMER_V2_FILE_SIZE_LIMIT:
        raise ContractError(
            f"{label} exceeds {CONSUMER_V2_FILE_SIZE_LIMIT} bytes: "
            f"{len(raw)}"
        )
    value = load_json(path)
    if raw != consumer_v2_file_bytes(value):
        raise ContractError(
            f"{label} is not canonical minified JSON with one LF"
        )
    return value


def _escape_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _unescape_pointer_token(value: str) -> str:
    return value.replace("~1", "/").replace("~0", "~")


def _assign_fragment(container, key, value) -> None:
    if isinstance(container, dict):
        if key not in container:
            container[key] = copy.deepcopy(value)
            return
        existing = container[key]
        if isinstance(existing, str) and isinstance(value, str):
            container[key] = existing + value
            return
        raise ContractError(
            f"consumer v2 duplicate non-text fragment path: {key}"
        )

    if not isinstance(container, list) or not key.isdigit():
        raise ContractError(
            "consumer v2 fragment path does not match its container"
        )

    index = int(key)
    while len(container) <= index:
        container.append(None)

    existing = container[index]
    if existing is None:
        container[index] = copy.deepcopy(value)
        return
    if isinstance(existing, str) and isinstance(value, str):
        container[index] = existing + value
        return
    raise ContractError(
        f"consumer v2 duplicate non-text fragment index: {index}"
    )


def reconstruct_fragments(fragments: list[dict]):
    """Reconstruct the original JSON value from ordered fragments."""
    root = {}

    for fragment in fragments:
        pointer = fragment.get("field")
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ContractError(
                "consumer v2 fragment field must be a JSON pointer"
            )

        if pointer == "/":
            if root:
                raise ContractError(
                    "consumer v2 root fragment conflicts with child fragments"
                )
            root = copy.deepcopy(fragment.get("value"))
            continue

        tokens = [
            _unescape_pointer_token(token)
            for token in pointer[1:].split("/")
        ]
        current = root

        for position, token in enumerate(tokens):
            final = position == len(tokens) - 1

            if final:
                _assign_fragment(
                    current,
                    token,
                    fragment.get("value"),
                )
                continue

            next_token = tokens[position + 1]
            next_is_list = next_token.isdigit()

            if isinstance(current, dict):
                if token not in current:
                    current[token] = [] if next_is_list else {}
                child = current[token]

            elif isinstance(current, list) and token.isdigit():
                index = int(token)
                while len(current) <= index:
                    current.append(None)
                if current[index] is None:
                    current[index] = [] if next_is_list else {}
                child = current[index]

            else:
                raise ContractError(
                    "consumer v2 fragment path has incompatible structure"
                )

            if not isinstance(child, (dict, list)):
                raise ContractError(
                    "consumer v2 fragment path traverses a scalar"
                )
            current = child

    return root


def _split_text(value: str) -> list[str]:
    """Split UTF-8 text without altering its exact concatenated value."""
    if len(value.encode("utf-8")) <= CONSUMER_V2_TEXT_FRAGMENT_LIMIT:
        return [value]

    punctuation = frozenset("???.!??,;?:?")
    chunks: list[str] = []
    buffer: list[str] = []

    for character in value:
        candidate = "".join(buffer) + character
        if len(candidate.encode("utf-8")) <= CONSUMER_V2_TEXT_FRAGMENT_LIMIT:
            buffer.append(character)
            continue

        cut = None
        minimum_preferred = max(1, len(buffer) // 2)
        for index in range(len(buffer) - 1, minimum_preferred - 1, -1):
            if buffer[index] in punctuation:
                cut = index + 1
                break

        if cut is None:
            chunks.append("".join(buffer))
            buffer = [character]
        else:
            chunks.append("".join(buffer[:cut]))
            buffer = buffer[cut:] + [character]

    if buffer:
        chunks.append("".join(buffer))

    if "".join(chunks) != value:
        raise ContractError("consumer v2 text fragmentation changed source text")
    if any(
        len(chunk.encode("utf-8")) > CONSUMER_V2_TEXT_FRAGMENT_LIMIT
        for chunk in chunks
    ):
        raise ContractError("consumer v2 text fragment exceeds configured limit")
    return chunks


def _flatten_fragments(value, path: str = "") -> list[dict]:
    """Flatten one view into ordered JSON-pointer fragments."""
    pointer = path or "/"

    if isinstance(value, dict):
        if not value:
            return [{"field": pointer, "value": {}}]
        fragments: list[dict] = []
        for key, item in value.items():
            child = f"{path}/{_escape_pointer_token(str(key))}"
            fragments.extend(_flatten_fragments(item, child))
        return fragments

    if isinstance(value, list):
        if not value:
            return [{"field": pointer, "value": []}]
        fragments = []
        for index, item in enumerate(value):
            child = f"{path}/{index}"
            fragments.extend(_flatten_fragments(item, child))
        return fragments

    if isinstance(value, str):
        return [
            {"field": pointer, "value": part}
            for part in _split_text(value)
        ]

    return [{"field": pointer, "value": copy.deepcopy(value)}]


def _chunk_identity(v1_snapshot: dict) -> tuple[dict, dict]:
    meta = v1_snapshot["meta"]
    return (
        copy.deepcopy(v1_snapshot["source_identity"]),
        {
            "run_id": meta["run_id"],
            "source_commit": meta["source_commit"],
            "source_sha256": meta["source_sha256"],
            "data_date": meta["data_date"],
            "status": meta["status"],
        },
    )


def _make_chunk(
    *,
    v1_snapshot: dict,
    kind: str,
    phase: int,
    part: int,
    part_count: int,
    fragments: list[dict],
) -> dict:
    source_identity, meta = _chunk_identity(v1_snapshot)
    return {
        "consumer_contract_version": CONSUMER_V2_CONTRACT_VERSION,
        "source_identity": source_identity,
        "meta": meta,
        "kind": kind,
        "phase": phase,
        "part": part,
        "part_count": part_count,
        "fragments": copy.deepcopy(fragments),
    }


def _pack_fragments(
    *,
    v1_snapshot: dict,
    kind: str,
    phase: int,
    fragments: list[dict],
) -> list[dict]:
    if kind not in {"phase", "detail"}:
        raise ContractError("consumer v2 chunk kind is invalid")
    if phase not in range(1, 7):
        raise ContractError("consumer v2 phase is invalid")
    if not fragments:
        raise ContractError("consumer v2 phase requires at least one fragment")

    groups: list[list[dict]] = []
    current: list[dict] = []

    for fragment in fragments:
        probe = _make_chunk(
            v1_snapshot=v1_snapshot,
            kind=kind,
            phase=phase,
            part=999,
            part_count=999,
            fragments=[*current, fragment],
        )

        if (
            current
            and len(consumer_v2_file_bytes(probe)) > CONSUMER_V2_CHUNK_TARGET
        ):
            groups.append(current)
            current = [fragment]
        else:
            current.append(fragment)

        single_probe = _make_chunk(
            v1_snapshot=v1_snapshot,
            kind=kind,
            phase=phase,
            part=999,
            part_count=999,
            fragments=current,
        )
        if len(consumer_v2_file_bytes(single_probe)) > CONSUMER_V2_FILE_SIZE_LIMIT:
            raise ContractError(
                f"consumer v2 {kind} phase {phase} contains "
                "an unsplittable fragment"
            )

    if current:
        groups.append(current)

    part_count = len(groups)
    chunks = [
        _make_chunk(
            v1_snapshot=v1_snapshot,
            kind=kind,
            phase=phase,
            part=index,
            part_count=part_count,
            fragments=group,
        )
        for index, group in enumerate(groups, 1)
    ]

    for chunk in chunks:
        validate_schema(
            chunk,
            CONSUMER_V2_CHUNK_SCHEMA,
            f"consumer v2 {kind} phase {phase} part {chunk['part']}",
        )
        size = len(consumer_v2_file_bytes(chunk))
        if size > CONSUMER_V2_FILE_SIZE_LIMIT:
            raise ContractError(
                f"consumer v2 {kind} phase {phase} part "
                f"{chunk['part']} exceeds "
                f"{CONSUMER_V2_FILE_SIZE_LIMIT} bytes: {size}"
            )

    return chunks


def build_consumer_v2_payloads(
    authoritative_latest: dict,
) -> tuple[dict, dict[int, list[dict]], dict[int, list[dict]]]:
    """Build the manifest and every deterministic small consumer chunk."""
    v1_snapshot = build_consumer_snapshot(authoritative_latest)
    detail_views = build_consumer_details(authoritative_latest)

    phase_chunks: dict[int, list[dict]] = {}
    detail_chunks: dict[int, list[dict]] = {}

    for phase in range(1, 7):
        phase_view = v1_snapshot["user_view"]["phases"][phase - 1]
        phase_fragments = _flatten_fragments(phase_view)
        phase_chunks[phase] = _pack_fragments(
            v1_snapshot=v1_snapshot,
            kind="phase",
            phase=phase,
            fragments=phase_fragments,
        )
        if canonical_bytes(
            reconstruct_fragments(phase_fragments)
        ) != canonical_bytes(phase_view):
            raise ContractError(
                f"consumer v2 phase {phase} fragmentation is not lossless"
            )

        detail_view = detail_views[phase - 1]["detail_view"]
        detail_fragments = _flatten_fragments(detail_view)
        detail_chunks[phase] = _pack_fragments(
            v1_snapshot=v1_snapshot,
            kind="detail",
            phase=phase,
            fragments=detail_fragments,
        )
        if canonical_bytes(
            reconstruct_fragments(detail_fragments)
        ) != canonical_bytes(detail_view):
            raise ContractError(
                f"consumer v2 detail phase {phase} "
                "fragmentation is not lossless"
            )

    manifest = {
        "consumer_contract_version": CONSUMER_V2_CONTRACT_VERSION,
        "source_identity": copy.deepcopy(v1_snapshot["source_identity"]),
        "meta": copy.deepcopy(v1_snapshot["meta"]),
        "presentation": {
            "presentation_version": v1_snapshot["user_view"][
                "presentation_version"
            ],
            "analysis_mode": v1_snapshot["user_view"]["analysis_mode"],
        },
        "phase_inventory": [
            {"phase": phase, "part_count": len(phase_chunks[phase])}
            for phase in range(1, 7)
        ],
        "detail_inventory": [
            {"phase": phase, "part_count": len(detail_chunks[phase])}
            for phase in range(1, 7)
        ],
    }

    validate_schema(
        manifest,
        CONSUMER_V2_MANIFEST_SCHEMA,
        "consumer v2 manifest",
    )
    manifest_size = len(consumer_v2_file_bytes(manifest))
    if manifest_size > CONSUMER_V2_FILE_SIZE_LIMIT:
        raise ContractError(
            f"consumer v2 manifest exceeds "
            f"{CONSUMER_V2_FILE_SIZE_LIMIT} bytes: {manifest_size}"
        )

    return manifest, phase_chunks, detail_chunks


def _validate_chunk_collection(
    chunks: dict[int, list[dict]],
    *,
    expected: dict[int, list[dict]],
    kind: str,
    manifest: dict,
) -> None:
    if set(chunks) != set(range(1, 7)):
        raise ContractError(f"consumer v2 {kind} phases are incomplete")

    inventory_name = (
        "phase_inventory" if kind == "phase" else "detail_inventory"
    )
    inventory = {
        item["phase"]: item["part_count"]
        for item in manifest[inventory_name]
    }

    for phase in range(1, 7):
        values = chunks[phase]
        if len(values) != inventory[phase]:
            raise ContractError(
                f"consumer v2 {kind} phase {phase} part count mismatch"
            )

        for index, chunk in enumerate(values, 1):
            validate_schema(
                chunk,
                CONSUMER_V2_CHUNK_SCHEMA,
                f"consumer v2 {kind} phase {phase} part {index}",
            )
            if chunk["kind"] != kind:
                raise ContractError("consumer v2 chunk kind mismatch")
            if chunk["phase"] != phase:
                raise ContractError("consumer v2 chunk phase mismatch")
            if chunk["part"] != index:
                raise ContractError("consumer v2 chunk part sequence mismatch")
            if chunk["part_count"] != len(values):
                raise ContractError("consumer v2 chunk part count mismatch")
            if chunk["source_identity"] != manifest["source_identity"]:
                raise ContractError(
                    "consumer v2 chunk source identity mismatch"
                )
            for field in (
                "run_id",
                "source_commit",
                "source_sha256",
                "data_date",
                "status",
            ):
                if chunk["meta"][field] != manifest["meta"][field]:
                    raise ContractError(
                        f"consumer v2 chunk meta mismatch: {field}"
                    )
            size = len(consumer_v2_file_bytes(chunk))
            if size > CONSUMER_V2_FILE_SIZE_LIMIT:
                raise ContractError(
                    f"consumer v2 {kind} phase {phase} part "
                    f"{index} exceeds size limit"
                )
            if canonical_bytes(chunk) != canonical_bytes(
                expected[phase][index - 1]
            ):
                raise ContractError(
                    f"consumer v2 {kind} phase {phase} part "
                    f"{index} differs from deterministic projection"
                )


def validate_consumer_v2_payloads(
    manifest: dict,
    phase_chunks: dict[int, list[dict]],
    detail_chunks: dict[int, list[dict]],
    authoritative_latest: dict,
) -> None:
    """Validate v2 payloads against one authoritative generation."""
    validate_schema(
        manifest,
        CONSUMER_V2_MANIFEST_SCHEMA,
        "consumer v2 manifest",
    )

    expected_manifest, expected_phases, expected_details = (
        build_consumer_v2_payloads(authoritative_latest)
    )

    if canonical_bytes(manifest) != canonical_bytes(expected_manifest):
        raise ContractError(
            "consumer v2 manifest differs from deterministic projection"
        )

    if len(consumer_v2_file_bytes(manifest)) > CONSUMER_V2_FILE_SIZE_LIMIT:
        raise ContractError("consumer v2 manifest exceeds size limit")

    _validate_chunk_collection(
        phase_chunks,
        expected=expected_phases,
        kind="phase",
        manifest=manifest,
    )
    _validate_chunk_collection(
        detail_chunks,
        expected=expected_details,
        kind="detail",
        manifest=manifest,
    )
