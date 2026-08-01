"""Deterministic US Market Rotation & Theme Flow engine."""

DATA_SCHEMA_VERSION = "1.2"
METHODOLOGY_VERSION = "1.2.0"
INSTRUCTION_VERSION = "1.6.0"
PUBLICATION_CONTRACT_VERSION = "1.1"
JUDGMENT_SCHEMA_VERSION = "1.0"
THEME_MASTER_SCHEMA_VERSION = "1.0"

# Keep the original v3 implementation immutable and apply the dynamic-industry
# handoff compatibility layer before downstream modules import the function.
from . import analysis_v3 as _analysis_v3
from . import analysis_v3_compat as _analysis_v3_compat

_analysis_v3.build_authoritative_v3 = (
    _analysis_v3_compat.build_authoritative_v3
)
