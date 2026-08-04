"""Deterministic US Market Rotation & Theme Flow engine."""

DATA_SCHEMA_VERSION = "1.2"
METHODOLOGY_VERSION = "1.2.0"
INSTRUCTION_VERSION = "2.0.3"
PUBLICATION_CONTRACT_VERSION = "1.1"
JUDGMENT_SCHEMA_VERSION = "1.0"
THEME_MASTER_SCHEMA_VERSION = "1.0"

# Keep the original v3 implementation immutable and apply the dynamic-industry
# handoff compatibility layer before downstream modules import the function.
from . import analysis_v3 as _analysis_v3
from . import analysis_v3_compat as _analysis_v3_compat

_analysis_v3.build_authoritative_v3 = _analysis_v3_compat.build_authoritative_v3

# Retain the immutable consumer v3 implementation while replacing only its
# fragmentation strategy and limit diagnostics.
from . import consumer_v3 as _consumer_v3
from . import consumer_v3_compact as _consumer_v3_compact

_consumer_v3_compact.install(_consumer_v3)

# Retain the immutable consumer v4 transport while layering explainable gates,
# candidate scope, sealed disclosure, and producer-owned selection decisions.
from . import consumer_v4 as _consumer_v4
from . import consumer_v4_enhanced as _consumer_v4_enhanced

_consumer_v4_enhanced.install(_consumer_v4)

from . import ai_contracts as _ai_contracts
from . import ai_contracts_enhanced as _ai_contracts_enhanced

_ai_contracts_enhanced.install(_ai_contracts)
