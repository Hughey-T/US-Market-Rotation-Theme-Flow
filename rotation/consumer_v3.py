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
POINTER_SCHEMA = load_json(SCHEMA_ROOT / "consumer_pointer_v3.schema.json")
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
            "status": meta["status"], "generated_at": meta["generated_at"],
            "valid_until": meta["valid_until"], "hard_stop_after": meta["hard_stop_after"], "timezone": "UTC"}


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


def build_consumer_v3(authoritative: dict, *, evaluation_at: str | None = None):
    snapshot = build_consumer_snapshot(authoritative); projection = build_authoritative_v3(authoritative, evaluation_at=evaluation_at)
    if projection["validity"]["status"] == "hard_stop": raise ContractError("E_HARD_STOP")
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
        if phase_inv[-1]["fragment_count"] + detail_inv[-1]["fragment_count"] > MAX_PHASE_FRAGMENTS: raise ContractError("combined phase fragment limit exceeded")
    for index, handoff in enumerate(projection["handoffs"], 1):
        validate_schema(handoff, HANDOFF_SCHEMA, f"v3 handoff {index}")
        if handoff["generation_id"] != identity["generation_id"]: raise ContractError("E_GENERATION_IDENTITY")
    handoff_chunks = _chunks({"handoffs": projection["handoffs"]}, identity, "handoff", 6)
    handoff_inventory = _inventory(6, handoff_chunks, {"handoffs": projection["handoffs"]})
    manifest = {"consumer_contract_version": CONTRACT_VERSION, "identity": identity,
                "presentation": {"presentation_version": "1.2", "analysis_mode": snapshot["user_view"]["analysis_mode"]},
                "validity": projection["validity"], "fundamental_identity": projection["fundamental_identity"],
                "phase_inventory": phase_inv, "detail_inventory": detail_inv, "handoff_inventory": handoff_inventory}
    validate_schema(manifest, MANIFEST_SCHEMA, "v3 generation manifest")
    pointer = {"consumer_contract_version": CONTRACT_VERSION, "generation_id": identity["generation_id"],
               "generation_manifest_path": f"generations/{identity['generation_id']}/manifest.json",
               "generation_manifest_sha256": sha256(canonical_file_bytes(manifest)), "identity": identity,
               "validity": projection["validity"]}
    validate_schema(pointer, POINTER_SCHEMA, "v3 latest pointer")
    return pointer, manifest, phases, detail_chunks, handoff_chunks


def validate_consumer_v3(pointer, manifest, phases, details, handoffs=None) -> None:
    validate_schema(pointer, POINTER_SCHEMA, "v3 latest pointer")
    validate_schema(manifest, MANIFEST_SCHEMA, "v3 generation manifest")
    if pointer["generation_manifest_sha256"] != sha256(canonical_file_bytes(manifest)):
        raise ContractError("E_MANIFEST_HASH")
    if pointer["identity"] != manifest["identity"] or pointer["generation_id"] != manifest["identity"]["generation_id"]:
        raise ContractError("E_GENERATION_IDENTITY")
    if pointer["validity"] != manifest["validity"]: raise ContractError("E_GENERATION_IDENTITY")
    for field in ("generated_at","valid_until","hard_stop_after","timezone"):
        if manifest["validity"][field] != manifest["identity"][field]: raise ContractError("E_GENERATION_IDENTITY")
    if manifest["fundamental_identity"].get("as_of") not in (None, manifest["identity"]["data_date"]): raise ContractError("E_GENERATION_IDENTITY")
    reconstructed = {}
    for kind, collection, inventory in (("phase", phases, manifest["phase_inventory"]), ("detail", details, manifest["detail_inventory"])):
        for item in inventory:
            phase = item["phase"]; chunks = collection.get(phase, [])
            if [c.get("part") for c in chunks] != list(range(1, item["part_count"] + 1)): raise ContractError("E_PART_SEQUENCE")
            if len(chunks) != item["part_count"]: raise ContractError("E_CHUNK_FETCH")
            observed_bytes=0
            for chunk, part in zip(chunks, item["parts"]):
                validate_schema(chunk, CHUNK_SCHEMA, f"remote v3 {kind} chunk")
                if chunk["consumer_contract_version"] != CONTRACT_VERSION or chunk["kind"] != kind or chunk["phase"] != phase or chunk["part_count"] != item["part_count"]:
                    raise ContractError("E_CHUNK_IDENTITY")
                raw = canonical_file_bytes(chunk)
                observed_bytes += len(raw)
                if len(raw) != part["bytes"] or sha256(raw) != part["sha256"]: raise ContractError("E_CHUNK_HASH")
                if chunk["identity"] != manifest["identity"]: raise ContractError("E_CHUNK_IDENTITY")
            if observed_bytes != item["total_bytes"]: raise ContractError("E_CHUNK_HASH")
            fragments = [f for c in chunks for f in c["fragments"]]
            if len(fragments) != item["fragment_count"]: raise ContractError("E_RECONSTRUCT")
            value = reconstruct_fragments(fragments); _scan_untrusted(value)
            validate_schema(value, PHASE_SCHEMA if kind == "phase" else DETAIL_SCHEMA, f"remote v3 {kind} object")
            if sha256(canonical_bytes(value)) != item["reconstructed_sha256"]: raise ContractError("E_RECONSTRUCT_HASH")
            reconstructed[(kind,phase)] = value
        for phase in PHASES:
            phase_item=manifest["phase_inventory"][phase-1]; detail_item=manifest["detail_inventory"][phase-1]
            if phase_item["fragment_count"] + detail_item["fragment_count"] > MAX_PHASE_FRAGMENTS: raise ContractError("E_RECONSTRUCT")
    mode=manifest["presentation"]["analysis_mode"]
    if reconstructed[("phase",1)]["analysis_mode_display"] != mode or reconstructed[("phase",6)]["analysis_mode_display"] != mode:
        raise ContractError("E_PRESENTATION_CONTRACT")
    if any(item["persistence"]["analysis_mode"] != mode for item in reconstructed[("phase",1)]["theme_assessments"]):
        raise ContractError("E_PRESENTATION_CONTRACT")
    if reconstructed[("phase",1)]["validity_status_display"] != manifest["validity"]["status_display"] or reconstructed[("phase",6)]["validity_status_display"] != manifest["validity"]["status_display"]:
        raise ContractError("E_PRESENTATION_CONTRACT")
    if handoffs is not None:
        item = manifest["handoff_inventory"]
        if [c["part"] for c in handoffs] != list(range(1, item["part_count"] + 1)): raise ContractError("E_PART_SEQUENCE")
        observed_bytes=0
        for chunk, part in zip(handoffs, item["parts"]):
            validate_schema(chunk, CHUNK_SCHEMA, "remote v3 handoff chunk")
            if chunk["identity"] != manifest["identity"] or chunk["kind"] != "handoff" or chunk["phase"] != 6 or chunk["part_count"] != item["part_count"]: raise ContractError("E_CHUNK_IDENTITY")
            raw = canonical_file_bytes(chunk)
            observed_bytes += len(raw)
            if len(raw) != part["bytes"] or sha256(raw) != part["sha256"]: raise ContractError("E_CHUNK_HASH")
        if observed_bytes != item["total_bytes"] or sum(len(c["fragments"]) for c in handoffs) != item["fragment_count"]: raise ContractError("E_CHUNK_HASH")
        value = reconstruct_fragments([f for c in handoffs for f in c["fragments"]])
        _scan_untrusted(value)
        for index, handoff in enumerate(value["handoffs"],1): validate_schema(handoff,HANDOFF_SCHEMA,f"remote handoff {index}")
        if sha256(canonical_bytes(value)) != item["reconstructed_sha256"]: raise ContractError("E_RECONSTRUCT_HASH")


def load_and_validate_consumer_v3(root: Path):
    """Read an exact immutable v3 tree and apply remote-consumer validation."""
    if root.is_symlink() or not root.is_dir(): raise ContractError("invalid consumer v3 directory")
    pointer_path=root/"manifest.json"
    if pointer_path.is_symlink() or not pointer_path.is_file(): raise ContractError("invalid consumer v3 pointer")
    def read(path):
        if path.is_symlink() or not path.is_file(): raise ContractError(f"invalid v3 file: {path}")
        value=load_json(path)
        if path.read_bytes()!=canonical_file_bytes(value): raise ContractError(f"non-canonical v3 file: {path}")
        return value
    pointer=read(pointer_path); validate_schema(pointer,POINTER_SCHEMA,"v3 pointer")
    generation=root/pointer["generation_manifest_path"].split("/manifest.json")[0]
    if generation.is_symlink() or not generation.is_dir(): raise ContractError("invalid immutable v3 generation")
    if set(x.name for x in root.iterdir()) != {"manifest.json","generations"}: raise ContractError("unexpected consumer v3 root entry")
    generations=root/"generations"
    generation_names={x.name for x in generations.iterdir()}
    if generations.is_symlink() or pointer["generation_id"] not in generation_names or any(len(name)!=64 or any(c not in "0123456789abcdef" for c in name) for name in generation_names):
        raise ContractError("consumer v3 generation inventory mismatch")
    manifest_path=generation/"manifest.json"; manifest=read(manifest_path)
    if sha256(manifest_path.read_bytes()) != pointer["generation_manifest_sha256"]: raise ContractError("E_MANIFEST_HASH")
    def read_kind(kind, inventory):
        base=generation/kind; result={}
        expected={f"phase-{x['phase']}" for x in inventory}
        if base.is_symlink() or set(x.name for x in base.iterdir()) != expected: raise ContractError(f"v3 {kind} inventory mismatch")
        for item in inventory:
            directory=base/f"phase-{item['phase']}"; names={f"part-{i}.json" for i in range(1,item["part_count"]+1)}
            if directory.is_symlink() or set(x.name for x in directory.iterdir()) != names: raise ContractError(f"v3 {kind} part inventory mismatch")
            result[item["phase"]]=[read(directory/f"part-{i}.json") for i in range(1,item["part_count"]+1)]
        return result
    phases=read_kind("phases",manifest["phase_inventory"]); details=read_kind("details",manifest["detail_inventory"])
    handoff_dir=generation/"handoffs"; handoff_item=manifest["handoff_inventory"]
    names={f"part-{i}.json" for i in range(1,handoff_item["part_count"]+1)}
    if handoff_dir.is_symlink() or set(x.name for x in handoff_dir.iterdir()) != names: raise ContractError("v3 handoff inventory mismatch")
    handoffs=[read(handoff_dir/f"part-{i}.json") for i in range(1,handoff_item["part_count"]+1)]
    if set(x.name for x in generation.iterdir()) != {"manifest.json","phases","details","handoffs"}: raise ContractError("unexpected immutable v3 entry")
    validate_consumer_v3(pointer,manifest,phases,details,handoffs)
    for old_id in sorted(generation_names - {pointer["generation_id"]}):
        generation=generations/old_id
        if generation.is_symlink() or set(x.name for x in generation.iterdir()) != {"manifest.json","phases","details","handoffs"}:
            raise ContractError("invalid retained immutable v3 generation")
        old_manifest=read(generation/"manifest.json")
        old_pointer={"consumer_contract_version":CONTRACT_VERSION,"generation_id":old_id,
            "generation_manifest_path":f"generations/{old_id}/manifest.json",
            "generation_manifest_sha256":sha256((generation/"manifest.json").read_bytes()),
            "identity":old_manifest["identity"],"validity":old_manifest["validity"]}
        old_phases=read_kind("phases",old_manifest["phase_inventory"])
        old_details=read_kind("details",old_manifest["detail_inventory"])
        old_item=old_manifest["handoff_inventory"]; old_dir=generation/"handoffs"
        old_names={f"part-{i}.json" for i in range(1,old_item["part_count"]+1)}
        if old_dir.is_symlink() or set(x.name for x in old_dir.iterdir()) != old_names: raise ContractError("retained v3 handoff inventory mismatch")
        old_handoffs=[read(old_dir/f"part-{i}.json") for i in range(1,old_item["part_count"]+1)]
        validate_consumer_v3(old_pointer,old_manifest,old_phases,old_details,old_handoffs)
    return pointer,manifest,phases,details,handoffs
