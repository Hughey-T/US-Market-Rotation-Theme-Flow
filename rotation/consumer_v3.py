"""Immutable, content-addressed consumer contract 3.0.

V3 deliberately wraps the established presentation projection rather than
changing the compatibility exporters.  Every byte published below a generation
directory is inventoried and can therefore be verified by a remote consumer.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from .consumer import build_consumer_snapshot
from .analysis_v3 import build_authoritative_v3
from .consumer_v2 import _flatten_fragments
from .provenance import canonical_bytes
from .validation import ContractError, load_json, validate_schema

CONTRACT_VERSION = "3.0"
PHASES = tuple(range(1, 7))
MAX_PHASE_PARTS = 8
MAX_DETAIL_PARTS = 32
MAX_PHASE_BYTES = 128 * 1024
MAX_PHASE_FRAGMENTS = 1000
PART_TARGET_BYTES = 12 * 1024
RESERVED_PREFIXES = ("進行状態:",)
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
MANIFEST_SCHEMA = load_json(SCHEMA_ROOT / "consumer_manifest_v3.schema.json")
CHUNK_SCHEMA = load_json(SCHEMA_ROOT / "consumer_chunk_v3.schema.json")
PHASE_SCHEMA = load_json(SCHEMA_ROOT / "consumer_phase_v3.schema.json")
DETAIL_SCHEMA = load_json(SCHEMA_ROOT / "consumer_detail_phase_v3.schema.json")
HANDOFF_SCHEMA = load_json(SCHEMA_ROOT / "handoff_v1.schema.json")
# The repository validator is intentionally offline and does not resolve
# cross-file references.  Bind the single shared definition before validation.
CHUNK_SCHEMA["properties"]["identity"] = copy.deepcopy(
    MANIFEST_SCHEMA["$defs"]["identity"]
)


def canonical_file_bytes(value: dict) -> bytes:
    return canonical_bytes(value) + b"\n"


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _scan_untrusted(value) -> None:
    if isinstance(value, str) and any(p in value for p in RESERVED_PREFIXES):
        raise ContractError("E_PRESENTATION_CONTRACT: reserved prefix in payload")
    if isinstance(value, dict):
        for item in value.values():
            _scan_untrusted(item)
    elif isinstance(value, list):
        for item in value:
            _scan_untrusted(item)


def reconstruct_fragments(fragments: list[dict]):
    """Strict JSON-Pointer reconstruction (no sparse arrays or path reuse)."""
    root = None
    previous = None
    seen: dict[str, object] = {}
    for position, fragment in enumerate(fragments):
        pointer = fragment.get("field")
        if not isinstance(pointer, str) or not pointer.startswith("/"):
            raise ContractError("E_RECONSTRUCT: invalid JSON Pointer")
        value = copy.deepcopy(fragment.get("value"))
        if pointer in seen:
            if pointer != previous or not isinstance(seen[pointer], str) or not isinstance(value, str):
                raise ContractError("E_RECONSTRUCT: invalid duplicate fragment")
            seen[pointer] += value
            # Locate and append to the already assigned scalar.
            tokens = pointer[1:].split("/")
            current = root
            for token in tokens[:-1]:
                token = token.replace("~1", "/").replace("~0", "~")
                current = current[int(token)] if isinstance(current, list) else current[token]
            key = tokens[-1].replace("~1", "/").replace("~0", "~")
            if isinstance(current, list): current[int(key)] += value
            else: current[key] += value
            previous = pointer
            continue
        if pointer == "/":
            if position or len(fragments) != 1:
                raise ContractError("E_RECONSTRUCT: root/child conflict")
            root = value; seen[pointer] = value; previous = pointer; continue
        if root is None: root = {}
        tokens = [t.replace("~1", "/").replace("~0", "~") for t in pointer[1:].split("/")]
        current = root
        for index, token in enumerate(tokens):
            final = index == len(tokens) - 1
            if isinstance(current, list):
                if not token.isdigit() or int(token) > len(current):
                    raise ContractError("E_RECONSTRUCT: sparse or repeated array index")
                position = int(token)
                if final:
                    if position != len(current): raise ContractError("E_RECONSTRUCT: repeated array index")
                    current.append(value); break
                if position == len(current):
                    child = [] if tokens[index + 1].isdigit() else {}; current.append(child)
                else:
                    child = current[position]
                    if not isinstance(child, (dict, list)): raise ContractError("E_RECONSTRUCT: scalar/container conflict")
                current = child
            elif isinstance(current, dict):
                if final:
                    if token in current: raise ContractError("E_RECONSTRUCT: duplicate path")
                    current[token] = value; break
                if token not in current: current[token] = [] if tokens[index + 1].isdigit() else {}
                if not isinstance(current[token], (dict, list)): raise ContractError("E_RECONSTRUCT: scalar/container conflict")
                current = current[token]
            else: raise ContractError("E_RECONSTRUCT: scalar/container conflict")
        seen[pointer] = value; previous = pointer
    if root is None: raise ContractError("E_RECONSTRUCT: empty fragments")
    return root


def _identity(snapshot: dict) -> dict:
    meta = snapshot["meta"]
    return {"analysis_id": snapshot["source_identity"]["analysis_id"],
            "generation_id": snapshot["source_identity"]["generation_id"],
            "run_id": meta["run_id"], "source_commit": meta["source_commit"],
            "source_sha256": meta["source_sha256"], "data_date": meta["data_date"],
            "status": meta["status"]}


def _chunks(view: dict, identity: dict, kind: str, phase: int) -> list[dict]:
    fragments = _flatten_fragments(view)
    if len(fragments) > MAX_PHASE_FRAGMENTS: raise ContractError("fragment limit exceeded")
    groups, group = [], []
    for fragment in fragments:
        probe = {"consumer_contract_version": CONTRACT_VERSION, "identity": identity, "kind": kind,
                 "phase": phase, "part": 1, "part_count": 1, "fragments": group + [fragment]}
        if group and len(canonical_file_bytes(probe)) > PART_TARGET_BYTES: groups.append(group); group = []
        group.append(fragment)
    groups.append(group)
    limit = MAX_PHASE_PARTS if kind == "phase" else MAX_DETAIL_PARTS
    if len(groups) > limit: raise ContractError(f"{kind} part limit exceeded")
    result = []
    for part, values in enumerate(groups, 1):
        chunk = {"consumer_contract_version": CONTRACT_VERSION, "identity": copy.deepcopy(identity),
                 "kind": kind, "phase": phase, "part": part, "part_count": len(groups), "fragments": values}
        validate_schema(chunk, CHUNK_SCHEMA, f"v3 {kind} chunk")
        result.append(chunk)
    return result


def _inventory(phase: int, chunks: list[dict], reconstructed: dict) -> dict:
    raws = [canonical_file_bytes(c) for c in chunks]
    return {"phase": phase, "part_count": len(chunks),
            "fragment_count": sum(len(c["fragments"]) for c in chunks),
            "total_bytes": sum(map(len, raws)), "reconstructed_sha256": sha256(canonical_bytes(reconstructed)),
            "parts": [{"part": i, "bytes": len(raw), "sha256": sha256(raw)} for i, raw in enumerate(raws, 1)]}


def build_consumer_v3(authoritative: dict):
    snapshot = build_consumer_snapshot(authoritative); projection = build_authoritative_v3(authoritative)
    identity = _identity(snapshot); phases = {}; detail_chunks = {}; phase_inv = []; detail_inv = []
    for phase in PHASES:
        view = projection["phases"][phase]
        detail = projection["details"][phase]
        validate_schema(view, PHASE_SCHEMA, f"v3 phase {phase} object")
        validate_schema(detail, DETAIL_SCHEMA, f"v3 phase {phase} detail object")
        _scan_untrusted(view); _scan_untrusted(detail)
        phases[phase] = _chunks(view, identity, "phase", phase)
        detail_chunks[phase] = _chunks(detail, identity, "detail", phase)
        phase_inv.append(_inventory(phase, phases[phase], view)); detail_inv.append(_inventory(phase, detail_chunks[phase], detail))
        if phase_inv[-1]["total_bytes"] + detail_inv[-1]["total_bytes"] > MAX_PHASE_BYTES: raise ContractError("phase payload limit exceeded")
    for index, handoff in enumerate(projection["handoffs"], 1):
        validate_schema(handoff, HANDOFF_SCHEMA, f"v3 handoff {index}")
        if handoff["generation_id"] != identity["generation_id"]: raise ContractError("E_GENERATION_IDENTITY")
    handoff_chunks = _chunks({"handoffs": projection["handoffs"]}, identity, "handoff", 6)
    handoff_inventory = _inventory(6, handoff_chunks, {"handoffs": projection["handoffs"]})
    manifest = {"consumer_contract_version": CONTRACT_VERSION, "identity": identity,
                "presentation": {"presentation_version": "1.2", "analysis_mode": snapshot["user_view"]["analysis_mode"]},
                "phase_inventory": phase_inv, "detail_inventory": detail_inv, "handoff_inventory": handoff_inventory}
    validate_schema(manifest, MANIFEST_SCHEMA, "v3 generation manifest")
    pointer = {"consumer_contract_version": CONTRACT_VERSION, "generation_id": identity["generation_id"],
               "generation_manifest_sha256": sha256(canonical_file_bytes(manifest)), "identity": identity}
    return pointer, manifest, phases, detail_chunks, handoff_chunks


def validate_consumer_v3(pointer, manifest, phases, details, handoffs=None) -> None:
    validate_schema(manifest, MANIFEST_SCHEMA, "v3 generation manifest")
    if pointer["generation_manifest_sha256"] != sha256(canonical_file_bytes(manifest)):
        raise ContractError("E_MANIFEST_HASH")
    if pointer["identity"] != manifest["identity"] or pointer["generation_id"] != manifest["identity"]["generation_id"]:
        raise ContractError("E_GENERATION_IDENTITY")
    for kind, collection, inventory in (("phase", phases, manifest["phase_inventory"]), ("detail", details, manifest["detail_inventory"])):
        for item in inventory:
            phase = item["phase"]; chunks = collection.get(phase, [])
            if [c.get("part") for c in chunks] != list(range(1, item["part_count"] + 1)): raise ContractError("E_PART_SEQUENCE")
            if len(chunks) != item["part_count"]: raise ContractError("E_CHUNK_FETCH")
            for chunk, part in zip(chunks, item["parts"]):
                raw = canonical_file_bytes(chunk)
                if len(raw) != part["bytes"] or sha256(raw) != part["sha256"]: raise ContractError("E_CHUNK_HASH")
                if chunk["identity"] != manifest["identity"]: raise ContractError("E_CHUNK_IDENTITY")
            fragments = [f for c in chunks for f in c["fragments"]]
            if len(fragments) != item["fragment_count"]: raise ContractError("E_RECONSTRUCT")
            if sha256(canonical_bytes(reconstruct_fragments(fragments))) != item["reconstructed_sha256"]: raise ContractError("E_RECONSTRUCT_HASH")
    if handoffs is not None:
        item = manifest["handoff_inventory"]
        if [c["part"] for c in handoffs] != list(range(1, item["part_count"] + 1)): raise ContractError("E_PART_SEQUENCE")
        for chunk, part in zip(handoffs, item["parts"]):
            raw = canonical_file_bytes(chunk)
            if len(raw) != part["bytes"] or sha256(raw) != part["sha256"]: raise ContractError("E_CHUNK_HASH")
        value = reconstruct_fragments([f for c in handoffs for f in c["fragments"]])
        if sha256(canonical_bytes(value)) != item["reconstructed_sha256"]: raise ContractError("E_RECONSTRUCT_HASH")
