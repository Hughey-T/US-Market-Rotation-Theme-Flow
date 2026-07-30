# Requirements 1–35 compliance matrix

The production path is `generate_weekly.ticker_observation/load_fundamental_bundle → pipeline.build_snapshot.v3_inputs → analysis_v3.build_authoritative_v3 → consumer_v3.build_consumer_v3 → export_consumer_v3`. Status values use only the requested vocabulary.

|§|requirement|production input / implementation|schema|positive test|negative test|CI / validator|status|
|---|---|---|---|---|---|---|---|
|1|deterministic display|`v3_inputs`; `build_authoritative_v3`|phase v3|production E2E|tamper E2E|full discovery / v3 reload|implemented and verified|
|2|v3 compatibility|weekly exporter; v2/v1 unchanged|pointer/manifest/chunk|consumer suites|invalid contract|full discovery / repository validator|implemented and verified|
|3|immutable generation|`export_consumer_v3`|pointer v3|rerun/byte equality|generation collision|full discovery / exact inventory|implemented and verified|
|4|integrity|canonical disk bytes; `validate_consumer_v3`|pointer/manifest/chunk|remote reload|byte/hash tamper|full discovery / remote-equivalent reload|implemented and verified|
|5|limits/reconstruction|combined Phase+detail counters|chunk v3|strict reconstruction|sparse/duplicate/root conflict|full discovery / v3 reload|implemented and verified|
|6|Phase5|weekly candidates; per-theme ranking|Phase5 oneOf|production E2E|missing/type/extra fields|full discovery / schema reload|implemented and verified|
|7|Phase6|dedicated producer summary|Phase6 oneOf|no Phase5 duplication|cross-Phase company injection|full discovery / schema reload|implemented and verified|
|8|display values|theme metrics; `display_percent`|assessment schema|margin synthetic|wrong type schema|full discovery / schema reload|implemented and verified|
|9|dates/validity|immutable snapshot times + consumer safety gate|pointer/manifest/Phase1/6|fresh/stale boundary|hard-stop boundary|full discovery / identity comparison|implemented and verified|
|10|GPT boundary|v3 presentation fields|instructions|instruction contract|reserved prefix|full discovery / instruction audit|implemented and verified|
|11|exact commands|`ConversationSession`|N/A|user experience|embedded commands|full discovery|implemented and verified|
|12|state|pointer generation/hash/mode|pointer schema|mode identity|mode mismatch|full discovery / remote validator|implemented and verified|
|13|errors|remote validation error classes|all v3 schemas|valid reload|tamper/hard stop|full discovery / validator|implemented and verified|
|14|untrusted payload|`_scan_untrusted`|phase/detail/handoff|normal payload|reserved prefix|full discovery / remote validator|implemented and verified|
|15|classification semantics|candidate buckets|Phase4|four buckets|cross-Phase schema|full discovery / schema reload|implemented and verified|
|16|flow semantics|`FLOW_NOTICE`|Phase1/6|producer E2E|instruction audit|full discovery / validator|implemented and verified|
|17|margin/confidence|theme metrics; `threshold_assessment`|assessment|synthetic boundary|missing observation|full discovery / schema reload|implemented and verified|
|18|persistence/churn|saved candidate bucket/version/price status in `history_weekly`|persistence object|trend E2E|insufficient history|full discovery / remote reload|implemented and verified|
|19|risk adjustment|date-keyed 60-day theme/SPY returns|risk object|available production E2E|date mismatch/zero variance|full discovery / schema reload|implemented and verified|
|20|selection stability/forward|realized theme/SPY outcomes + constituent hash|stability object|five-sample E2E|future leakage rejection|full discovery / schema reload|implemented and verified|
|21|overlap|constituents, dated returns, configured factors|Phase3 pair objects|deterministic cluster/correlation|insufficient dates|full discovery / schema reload|implemented and verified|
|22|fundamentals|`data/fundamentals/{data_date}.json`; hash-bound bundle|snapshot v3 input / fundamental object|available production E2E|as-of mismatch/missing fields|full discovery / snapshot validation|implemented and verified|
|23|point-in-time constituents|effective master membership|Phase3 constituent object|generation projection|membership boundaries|full discovery / schema reload|implemented and verified|
|24|coverage|core coverage plus explicit optional not-assessed paths|coverage object|coverage E2E|low coverage warning|full discovery / schema reload|implemented and verified|
|25|handoff|structured Phase5 candidates|handoff v1|remote handoff reload|identity/schema tamper|full discovery / v3 reload|implemented and verified|
|26|traceability|authoritative `/themes`, `/v3_inputs`, `/meta` paths|detail oneOf|detail reload|self-reference/extra field|full discovery / schema reload|implemented and verified|
|27|Phase layout|authoritative six objects|Phase oneOf|all six positive|Phase mixing|full discovery / schema reload|implemented and verified|
|28|fetch/fallback|fixed publication raw URLs|instructions|URL contract|arbitrary/path-traversal prohibition|full discovery / instruction audit|implemented and verified|
|29|backward compatibility|existing compatibility exporters|existing schemas|legacy/v1/v2 suites|invalid higher contract|full discovery / repository validator|implemented and verified|
|30|tests|production/unit/integration/E2E inputs|all schemas|260+ suite|mutation suites|full-discovery CI|implemented and verified|
|31|workflow|weekly v3 export and remote byte diff|all v3 schemas|workflow contract|unregistered test guard|full discovery / repository validator|implemented and verified|
|32|documentation|instructions/contract/matrix|N/A|instruction audit|missing-term audit|full discovery / validator|implemented and verified|
|33|quality|shared producer/validator/constants|closed schemas|compileall|schema mutation|CI compile / validator|implemented and verified|
|34|completion|required command set|N/A|full suite|fail-closed checks|PR CI jobs|implemented and verified|
|35|reporting|commit/PR test report|N/A|git audit|N/A|PR body|implemented and verified|
