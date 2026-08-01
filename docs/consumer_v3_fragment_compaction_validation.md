# Validation plan

The regression suite constructs a production-sized Phase 1-shaped payload whose legacy leaf projection exceeds 1,000 fragments. The compact projection must stay within the existing limit, fit within the existing part limit, and reconstruct to the exact original JSON value. A separate regression verifies that fragment-limit failures include kind, phase, observed count, and maximum.
