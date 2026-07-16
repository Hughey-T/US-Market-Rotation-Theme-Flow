# Test classification

Each Python test method belongs to exactly one CI category.

| CI category | Files | Methods |
|---|---|---:|
| Schema and canonical fixtures | `test_condition_audit.py`, `test_immutable_judgments.py` | 8 |
| Unit and rule contracts | `test_spec_cases.py`, `test_rule_reachability.py`, `test_semantic_validation.py` | 76 |
| Pipeline integration | `test_pipeline_contract.py`, `test_generation_e2e.py` | 23 |
| Production orchestration E2E | `test_production_orchestration_e2e.py` | 9 |
| Repository operations and transactional publish | `test_publication_contract.py`, `test_membership_contract.py` | 13 |
| Judgment projection semantics | `test_judgment_projection.py` | 3 |
| Publication recovery E2E | `test_publication_hardening.py` | 12 |
| Workflow contracts | `test_lock_and_workflow_contract.py` | 10 |
| **Total** | 13 files | **154** |

T01–T70 remain the 70 numbered design contracts. The other 84 methods are
independent reachability, semantic, repository, membership, mutation, and raw
orchestration contracts. No test file is invoked by more than one CI category.

The production orchestration category starts with synthetic pandas OHLCV
frames and invokes `scripts.generate_weekly.main()`. The older
`test_generation_e2e.py` suite is a component/pipeline integration layer that
starts from normalized observations and is intentionally not labelled as the
production E2E gate.
