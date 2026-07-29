# Requirements 1–35 compliance matrix

All verification commands below are offline. “N/A” means the numbered section
is an objective or reporting/process rule rather than a separate artifact.

| § | requirement | implementation | schema | test | verification | status |
|---|---|---|---|---|---|---|
|1|deterministic verified display|`analysis_v3.build_authoritative_v3`|phase v3|analysis E2E|full unittest|implemented and verified|
|2|v3 and compatibility|`consumer_v3`; compatibility exporters unchanged|manifest/chunk v3|consumer v3|repository validator|implemented and verified|
|3|immutable generations|`export_consumer_v3`|manifest v3|immutable export|analysis/consumer tests|implemented and verified|
|4|content integrity|`validate_consumer_v3`|manifest/chunk v3|tamper tests|consumer tests|implemented and verified|
|5|limits and reconstruction|`reconstruct_fragments`|chunk/phase v3|strict reconstruction|consumer tests|implemented and verified|
|6|structured Phase5|`build_authoritative_v3`|phase v3|Phase5 E2E|analysis tests|implemented and verified|
|7|dedicated Phase6|`build_authoritative_v3`|phase/detail v3|no Phase5 duplication|analysis tests|implemented and verified|
|8|prebuilt display values|`display_percent`|phase v3|display/margin test|analysis tests|implemented and verified|
|9|dates and validity display|Phase1/6 projection; instructions|phase v3|schema/E2E|consumer tests|implemented and verified|
|10|GPT boundary|instructions 1.7.0|N/A|instruction contracts|full unittest|implemented and verified|
|11|exact commands|`interaction.ConversationSession`; instructions|N/A|user experience|full unittest|implemented and verified|
|12|strict state|instructions 1.7.0|N/A|instruction contract|full unittest|implemented and verified|
|13|error separation|validator codes; instructions|N/A|tamper/contract tests|consumer tests|implemented and verified|
|14|untrusted payload|`_scan_untrusted`; instructions|phase v3|reserved prefix|consumer tests|implemented and verified|
|15|classification semantics|Phase4 projection|phase v3|projection E2E|analysis tests|implemented and verified|
|16|flow semantics|`FLOW_NOTICE`|phase v3|projection E2E|analysis tests|implemented and verified|
|17|margin and confidence|`threshold_assessment`|phase v3|synthetic threshold|analysis tests|implemented and verified|
|18|persistence/churn|persistence projection with explicit missingness|phase v3|initial observation E2E|analysis tests|implemented and verified|
|19|beta/volatility path|`risk_adjusted_metrics`|phase v3|synthetic risk|analysis tests|implemented and verified|
|20|multiple comparisons/forward return|`multiple_comparison`|phase v3|synthetic statistics|analysis tests|implemented and verified|
|21|overlap clusters|`overlap_clusters`|phase v3|order-independent cluster|analysis tests|implemented and verified|
|22|fundamental path|`fundamentals` adapter; confirmation|phase v3|saved fixture|analysis tests|implemented and verified|
|23|point-in-time constituents|`point_in_time_constituents`|phase v3|projection E2E|analysis tests|implemented and verified|
|24|coverage|`coverage`|phase v3|projection E2E|analysis tests|implemented and verified|
|25|handoff contract|handoff projection/inventory|handoff v1|handoff E2E|analysis tests|implemented and verified|
|26|traceability|detail source fields|detail v3|schema/E2E|consumer tests|implemented and verified|
|27|Phase layout|authoritative six objects|phase v3|schema/E2E|consumer tests|implemented and verified|
|28|fetch/fallback|instructions 1.7.0|N/A|instruction contracts|full unittest|implemented and verified|
|29|backward compatibility|v2/v1/legacy unchanged|existing schemas|existing suites|full unittest|implemented and verified|
|30|unit/integration/E2E|analysis and consumer tests|all v3 schemas|test modules|full unittest|implemented and verified|
|31|workflow publication|weekly v3 export and byte diff|manifest v3|workflow tests|full unittest|implemented and verified|
|32|documentation|instructions, contract, matrix|N/A|repository validator|validator|implemented and verified|
|33|implementation quality|shared pure modules/constants|strict schemas|compile/tests|compileall|implemented and verified|
|34|completion checks|this matrix and verification record|N/A|all suites|required commands|implemented and verified|
|35|final reporting|final response and PR body|N/A|N/A|git/PR metadata|implemented and verified|
