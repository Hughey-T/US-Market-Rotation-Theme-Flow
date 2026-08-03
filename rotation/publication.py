"""Publication API with read compatibility for pre-v3 histories and consumer v4."""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from types import ModuleType

from . import publication_core as _core
from .consumer_v4 import load_and_validate_consumer_v4
from .validation import ContractError

_LEGACY_THEME_HISTORY_FIELDS = frozenset({
    "equal_weight_rel_spy_4w", "advance_count_4w", "above_50dma_count",
    "pct_above_50dma", "volume_ratio_20d_60d",
})
_ORIGINAL_EXPECTED_HISTORY = _core._expected_history
_ORIGINAL_VALIDATE_CONSUMER = _core._validate_consumer


def _expected_history(snapshot: dict) -> dict:
    expected = _ORIGINAL_EXPECTED_HISTORY(snapshot)
    if "v3_inputs" in snapshot:
        return expected
    for theme in expected["themes"].values():
        for field in tuple(theme):
            if field not in _LEGACY_THEME_HISTORY_FIELDS:
                del theme[field]
    return expected


def instruction_version_for_data_schema(schema_version: str) -> str:
    """Return the historical canonical identity for an existing data schema."""
    return "1.1.1" if schema_version == "1.1" else "1.6.0"


def instruction_versions_for_data_schema(schema_version: str) -> set[str]:
    """Accept historical identities plus the v4 Custom GPT contracts."""
    if schema_version == "1.1":
        return {"1.1.1"}
    return {"1.3.0", "1.4.0", "1.5.0", "1.6.0", "2.0.0", "2.0.1", "2.0.2"}


def _validate_consumer(output: Path, current: tuple, files: set[str], *, required: bool) -> None:
    v4 = output / "consumer" / "v4"
    if not v4.exists() and not v4.is_symlink():
        _ORIGINAL_VALIDATE_CONSUMER(output, current, files, required=required)
        return
    if v4.is_symlink() or not v4.is_dir():
        raise ContractError("consumer v4 publication directory is invalid")
    loaded = load_and_validate_consumer_v4(v4)
    if loaded["pointer"]["generation_id"] != current[2]["generation_id"]:
        raise ContractError("consumer v4/current publication generation mismatch")
    with tempfile.TemporaryDirectory(prefix="publication-v4-compat-") as name:
        temporary_output = Path(name) / "output"
        temporary_consumer = temporary_output / "consumer"
        temporary_consumer.mkdir(parents=True)
        for entry in (output / "consumer").iterdir():
            if entry.name == "v4":
                continue
            destination = temporary_consumer / entry.name
            if entry.is_symlink():
                raise ContractError("consumer symlink is forbidden")
            if entry.is_dir():
                shutil.copytree(entry, destination)
            elif entry.is_file():
                shutil.copy2(entry, destination)
            else:
                raise ContractError("invalid consumer publication entry")
        legacy_files: set[str] = set()
        _ORIGINAL_VALIDATE_CONSUMER(temporary_output, current, legacy_files, required=required)
        files.update(legacy_files)
    for entry in sorted(v4.rglob("*")):
        if entry.is_symlink():
            raise ContractError("consumer v4 symlink is forbidden")
        if entry.is_file():
            files.add(_core.output_relative_path(output, entry))


_core._expected_history = _expected_history
_core.instruction_version_for_data_schema = instruction_version_for_data_schema
_core.instruction_versions_for_data_schema = instruction_versions_for_data_schema
_core._validate_consumer = _validate_consumer

for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

globals()["_expected_history"] = _expected_history
globals()["instruction_version_for_data_schema"] = instruction_version_for_data_schema
globals()["instruction_versions_for_data_schema"] = instruction_versions_for_data_schema
globals()["_validate_consumer"] = _validate_consumer


class _PublicationFacade(ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        if not name.startswith("__") and hasattr(_core, name):
            setattr(_core, name, value)

    def __delattr__(self, name: str) -> None:
        super().__delattr__(name)
        if not name.startswith("__") and hasattr(_core, name):
            delattr(_core, name)


sys.modules[__name__].__class__ = _PublicationFacade
