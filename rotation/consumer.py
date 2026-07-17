"""Deterministic, size-bounded Custom GPT consumer projections."""
from __future__ import annotations

import copy
from pathlib import Path

from .identity import validate_safe_id
from .provenance import canonical_bytes
from .validation import ContractError, load_json, validate_public_latest, validate_schema


CONSUMER_CONTRACT_VERSION = "1.0"
CONSUMER_CANONICAL_SIZE_LIMIT = 32 * 1024
CONSUMER_FILE_SIZE_LIMIT = 32 * 1024
SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas"
CONSUMER_SCHEMA = load_json(SCHEMA_ROOT / "consumer_snapshot.schema.json")
DETAILS_SCHEMA = load_json(SCHEMA_ROOT / "consumer_details.schema.json")
LATEST_SCHEMA = load_json(SCHEMA_ROOT / "rotation_snapshot.schema.json")
CONSUMER_META_FIELDS = (
    "run_id", "source_commit", "source_snapshot", "source_sha256", "generated_at",
    "data_date", "valid_until", "hard_stop_after", "status", "failure_reason",
)
DETAILS_CONTRACT_VERSION = "1.0"
DETAILS_PHASES = tuple(range(1, 7))
DETAILS_CANONICAL_SIZE_LIMIT = 32 * 1024
DETAILS_FILE_SIZE_LIMIT = 32 * 1024


def _identity(authoritative_latest: dict) -> dict:
    meta = authoritative_latest["meta"]
    return {
        "source_identity": {
            "analysis_id": validate_safe_id(meta.get("run_id"), "analysis_id"),
            "generation_id": source_generation_id(authoritative_latest),
        },
        "meta": {
            "run_id": meta.get("run_id"),
            "source_commit": meta.get("source_commit"),
            "source_sha256": meta.get("source_sha256"),
            "data_date": meta.get("data_date"),
            "status": meta.get("status"),
        },
    }


def _metric(name: str, label: str, value, explanation: str) -> dict:
    return {"name": name, "label": label, "value": value, "explanation": explanation}


def _not_implemented_labels(snapshot: dict) -> list[str]:
    labels = {
        "direct_etf_flow": "ETF・fundの直接的な資金フローデータ",
        "earnings_revision": "業績予想の上方・下方修正データ",
        "positioning": "投資家ポジショニングデータ",
        "point_in_time_market_cap": "時点整合した時価総額データ",
    }
    return [labels.get(item, "追加の未実装データ") for item in snapshot.get("not_implemented") or []]


def _ranked_items(section: dict, *, limit: int | None = None) -> list[dict]:
    etfs = section.get("etfs") or {}
    ranking = list(section.get("rank_by_rel_spy_4w") or [])
    if limit is not None:
        ranking = ranking[:limit]
    return [
        {
            "ticker": ticker,
            "label": (etfs.get(ticker) or {}).get("label", ticker),
            "return_1w": (etfs.get(ticker) or {}).get("return_1w"),
            "return_4w": (etfs.get(ticker) or {}).get("return_4w"),
            "return_13w": (etfs.get(ticker) or {}).get("return_13w"),
            "relative_strength_4w": (etfs.get(ticker) or {}).get("rel_spy_4w"),
            "above_50dma": (etfs.get(ticker) or {}).get("above_50dma"),
            "above_200dma": (etfs.get(ticker) or {}).get("above_200dma"),
        }
        for ticker in ranking
    ]


def _phase_1(snapshot: dict) -> dict:
    regime = snapshot.get("market_regime") or {}
    classification = regime.get("classification") or {}
    inputs = regime.get("inputs") or {}
    quality = snapshot["meta"].get("global_quality") or {}
    indicator_specs = (
        ("spy_r_4w", "S&P 500の4週騰落率", "市場平均そのものの中期的な方向を示します。"),
        ("qqq_rel_spy_4w", "大型成長株の相対強度", "NASDAQ 100がS&P 500を4週間でどれだけ上回ったかを示します。"),
        ("rsp_minus_spy_4w", "均等加重の広がり", "大型株だけでなく幅広い銘柄へ上昇が及んでいるかを見る目安です。"),
        ("iwm_minus_spy_4w", "小型株の相対強度", "小型株が市場平均を上回っているかを見る目安です。"),
        ("hyg_minus_lqd_4w", "信用リスク選好", "低格付け債と高格付け債の差からリスク選好を確認します。"),
        ("vix_change_4w", "VIXの4週変化", "市場の不安感が拡大したか低下したかを見る補助指標です。"),
    )
    return {
        "title": "市場環境の監査説明",
        "market_environment": {
            "classification": classification.get("primary_regime", "unavailable"),
            "secondary": classification.get("secondary_regimes") or [],
            "confidence": classification.get("confidence", "unavailable"),
            "explanation": "複数の市場指標を同時に照合した分類です。単一指標だけで判断していません。",
        },
        "representative_indicators": [
            _metric(name, label, inputs.get(name), explanation)
            for name, label, explanation in indicator_specs
        ],
        "breadth": {
            "sector_advance_ratio_4w": inputs.get("sector_advance_ratio_4w"),
            "explanation": "主要11セクターのうち4週間で上昇した割合です。上昇の広がりを確認します。",
        },
        "risk_posture": [
            "景気敏感株・防御株・実物資産・信用市場を横断し、偏りを確認しています。",
            "価格変化だけを資金流入または流出の直接証拠とは扱いません。",
        ],
        "global_quality": {
            "coverage_ratio": quality.get("coverage_ratio"),
            "requested_ticker_count": quality.get("requested_ticker_count"),
            "usable_ticker_count": quality.get("usable_ticker_count"),
            "critical_missing": copy.deepcopy(quality.get("critical_missing") or []),
        },
        "warnings": copy.deepcopy(quality.get("warnings") or []),
        "constraints": [f"未実装: {item}" for item in _not_implemented_labels(snapshot)],
    }


def _phase_2(snapshot: dict) -> dict:
    styles = snapshot.get("style_factor") or {}
    comparisons = []
    moving = []
    for ticker in sorted(styles):
        item = styles[ticker]
        comparisons.append({
            "ticker": ticker, "label": item.get("label", ticker),
            "return_1w": item.get("return_1w"), "return_4w": item.get("return_4w"),
            "return_13w": item.get("return_13w"), "relative_strength_1w": item.get("rel_spy_1w"),
            "relative_strength_4w": item.get("rel_spy_4w"), "relative_strength_13w": item.get("rel_spy_13w"),
        })
        moving.append({
            "ticker": ticker, "above_50dma": item.get("above_50dma"),
            "above_200dma": item.get("above_200dma"),
            "explanation": "50日線は中期、200日線は長期の価格位置を確認する目安です。",
        })
    return {
        "title": "スタイル・factorの監査説明",
        "comparisons": comparisons,
        "moving_average_state": moving,
        "interpretation_notes": [
            "1週・4週・13週を併記し、短期だけの変化を長期傾向と混同しません。",
            "相対強度はS&P 500との差であり、直接的な資金フローではありません。",
        ],
    }


def _phase_3(snapshot: dict) -> dict:
    sectors = snapshot.get("sectors") or {}
    sector_rank = list(sectors.get("rank_by_rel_spy_4w") or [])
    bottom_ids = list(reversed(sector_rank[-3:]))
    bottom_section = {"etfs": sectors.get("etfs") or {}, "rank_by_rel_spy_4w": bottom_ids}
    discovery = snapshot.get("dynamic_discovery") or {}
    candidates = discovery.get("candidates") or {}
    rejected = discovery.get("rejected") or {}
    rejection_labels = {
        "industry_etf_relative_strength_below_3pct": "業種ETFの4週相対強度が採用基準に届きませんでした。",
        "recent_company_strength_not_positive": "構成企業の直近の強さが採用基準に届きませんでした。",
        "fewer_than_half_above_50dma": "50日線を上回る企業が半数未満でした。",
        "median_company_not_above_market": "構成企業の中央値が市場平均を上回りませんでした。",
        "single_company_concentration_or_unknown": "一社集中を否定できないため除外しました。",
        "too_few_valid_companies": "有効な構成企業数が不足しました。",
    }
    selected = [
        {"id": item_id, "label": (candidates.get(item_id) or {}).get("label", item_id), "explanation": "ETF相対強度と複数企業の広がりが設定済み基準を満たしました。"}
        for item_id in sorted(discovery.get("candidate_ids") or [])
    ]
    excluded = [
        {
            "id": item_id,
            "label": (candidates.get(item_id) or {}).get("label", item_id),
            "explanation": " ".join(rejection_labels.get(reason, "設定済み基準を満たしませんでした。") for reason in reasons),
        }
        for item_id, reasons in sorted(rejected.items())
    ]
    quality = snapshot["meta"].get("global_quality") or {}
    return {
        "title": "セクター・業種の監査説明",
        "top_sectors": _ranked_items(sectors, limit=3),
        "bottom_sectors": _ranked_items(bottom_section),
        "top_industries": _ranked_items(snapshot.get("industries") or {}, limit=5),
        "dynamic_selected": selected,
        "dynamic_excluded": excluded,
        "breadth_and_concentration": [
            "順位はS&P 500に対する4週相対強度を基準にしています。",
            "単一銘柄だけの上昇か、複数銘柄へ広がっているかはテーマ段階でも別に確認します。",
        ],
        "data_gaps": copy.deepcopy(quality.get("missing_tickers") or []),
    }


def _theme_detail(snapshot: dict, item: dict) -> dict:
    item_id = item.get("id")
    source = item.get("source", "fixed_theme")
    if source == "dynamic_industry":
        value = ((snapshot.get("dynamic_discovery") or {}).get("candidates") or {}).get(item_id, {})
    else:
        value = (snapshot.get("themes") or {}).get(item_id, {})
    metrics = value.get("metrics") or {}
    context = value.get("structural_context") or {}
    contrary = (value.get("condition_flags") or {}).get("contrary_evidence") or []
    decision = value.get("decision") or {}
    classification_explanations = {
        "research_now": "現在の相対強度、広がり、集中度が調査を進める条件を満たしています。",
        "watch_recovery": "中期の強さを残す一方、直近の回復確認が必要です。",
        "long_term_context_price_weak": "構造的背景は確認済みですが、足元の価格と広がりが弱い状態です。",
        "avoid_now": "現在の価格、広がり、集中度または反対材料から、調査優先度を下げています。",
    }
    return {
        "id": item_id,
        "label": item.get("label", value.get("label", item_id)),
        "source": source,
        "classification_explanation": classification_explanations.get(
            item.get("classification_reason"), "生成済みの分類条件に基づく候補です。"
        ),
        "relative_strength_4w": metrics.get("equal_weight_rel_spy_4w"),
        "breadth_above_50dma": metrics.get("pct_above_50dma"),
        "concentration_top1": metrics.get("top1_contribution_ratio"),
        "structural_context_status": context.get("status", "not_assessed"),
        "recovery_condition": "相対強度と上昇銘柄の広がりが同時に改善するかを次回確認します。",
        "largest_counter_evidence": (
            "反対条件が検出されています。次回の価格と広がりで再確認します。"
            if contrary else
            ("直接的な資金フロー確認はありません。" if decision.get("direct_flow_confirmation") == "unavailable" else "明示的な反対条件は検出されていません。")
        ),
    }


def _phase_4(snapshot: dict) -> dict:
    buckets = snapshot.get("candidate_buckets") or {}
    labels = {
        "research_now": "今調べる候補", "watch_recovery": "回復確認候補",
        "long_term_context_price_weak": "長期文脈はあるが価格が弱い候補", "avoid_now": "今は避ける候補",
    }
    explanations = {
        "research_now": "相対強度、広がり、集中度などが現在の調査条件を満たしています。",
        "watch_recovery": "現時点では不足があり、回復条件の確認を待つ分類です。",
        "long_term_context_price_weak": "構造的背景と足元の価格状態を分けて扱う分類です。",
        "avoid_now": "反対材料または弱い価格条件が優勢な分類です。",
    }
    values = []
    for key in labels:
        items = buckets.get(key) or []
        values.append({
            "bucket": key, "label": labels[key], "explanation": explanations[key],
            "items": [_theme_detail(snapshot, item) for item in items],
        })
    return {"title": "テーマ4分類の監査説明", "buckets": values}


def _phase_5(snapshot: dict) -> dict:
    role_labels = {"representative": "代表企業", "breadth_check": "広がり確認用企業"}
    companies = []
    for item in snapshot.get("company_candidates") or []:
        role = item.get("selection_role")
        companies.append({
            "theme_id": item.get("theme_id"), "theme_label": item.get("theme_label"),
            "ticker": item.get("ticker"), "role": role,
            "role_label": role_labels.get(role, "確認用企業"),
            "why": item.get("why"), "key_check": item.get("key_check"),
            "counter_evidence": item.get("counter_evidence"),
            "research_lens_explanation": (
                "テーマを代表する企業として業績の裏付けを確認します。"
                if role == "representative" else
                "同じテーマの別企業にも改善が広がっているかを確認します。"
            ),
        })
    return {
        "title": "企業候補の監査説明", "companies": companies,
        "caution": "企業候補はテーマ検証の観測対象であり、売買推奨ではありません。",
    }


def _phase_6(snapshot: dict) -> dict:
    buckets = snapshot.get("candidate_buckets") or {}
    phase_one = (snapshot.get("market_regime") or {}).get("classification") or {}
    quality = snapshot["meta"].get("global_quality") or {}
    return {
        "title": "最終判断要約の監査説明",
        "market_basis": [
            f"市場分類: {phase_one.get('primary_regime', 'unavailable')}",
            f"信頼度: {phase_one.get('confidence', 'unavailable')}",
            "市場、スタイル、セクター、テーマ、企業の順に同一snapshotを確認しています。",
        ],
        "bucket_counts": {key: len(buckets.get(key) or []) for key in (
            "research_now", "watch_recovery", "long_term_context_price_weak", "avoid_now"
        )},
        "company_count": len(snapshot.get("company_candidates") or []),
        "analysis_mode": (snapshot.get("user_view") or {}).get("analysis_mode", "initial_observation"),
        "constraints": copy.deepcopy(quality.get("warnings") or []),
        "change_conditions": [
            "次週に相対強度、上昇銘柄の広がり、移動平均位置、集中度が変化した場合は分類が変わり得ます。",
            "新しい公開データは「更新」でのみ取得し、会話途中に別generationを混ぜません。",
        ],
        "not_implemented": [f"{item}は現在の分析に直接使用していません。" for item in _not_implemented_labels(snapshot)],
    }


DETAIL_BUILDERS = (_phase_1, _phase_2, _phase_3, _phase_4, _phase_5, _phase_6)


def build_consumer_details(authoritative_latest: dict) -> list[dict]:
    """Build all six human-readable phase details from one authoritative snapshot."""
    identity = _identity(authoritative_latest)
    return [
        {
            "details_contract_version": DETAILS_CONTRACT_VERSION,
            **copy.deepcopy(identity),
            "phase": phase,
            "detail_view": builder(authoritative_latest),
        }
        for phase, builder in enumerate(DETAIL_BUILDERS, 1)
    ]


def validate_consumer_detail(detail: dict, authoritative_latest: dict, *, phase: int) -> None:
    if phase not in DETAILS_PHASES or detail.get("phase") != phase:
        raise ContractError("consumer detail phase mismatch")
    validate_schema(detail, DETAILS_SCHEMA, f"consumer phase {phase} details")
    expected = build_consumer_details(authoritative_latest)[phase - 1]
    for field in ("source_identity", "meta"):
        if detail.get(field) != expected[field]:
            raise ContractError(f"consumer detail {field.replace('_', ' ')} mismatch")
    if canonical_bytes(detail) != canonical_bytes(expected):
        raise ContractError("consumer detail differs from deterministic authoritative projection")
    size = len(canonical_bytes(detail))
    if size > DETAILS_CANONICAL_SIZE_LIMIT:
        raise ContractError(f"consumer detail canonical JSON exceeds {DETAILS_CANONICAL_SIZE_LIMIT} bytes: {size}")


def validate_consumer_details(details: list[dict], authoritative_latest: dict) -> None:
    if len(details) != 6 or {item.get("phase") for item in details} != set(DETAILS_PHASES):
        raise ContractError("consumer details require exactly phases 1 through 6")
    for phase in DETAILS_PHASES:
        validate_consumer_detail(next(item for item in details if item.get("phase") == phase), authoritative_latest, phase=phase)


def source_generation_id(authoritative_latest: dict) -> str:
    source = authoritative_latest.get("meta", {}).get("source_snapshot", "")
    parts = Path(source).as_posix().split("/")
    if len(parts) != 4 or parts[:2] != ["output", "generations"] or parts[3] != "archive.json":
        raise ContractError("source_snapshot must identify one authoritative generation")
    return validate_safe_id(parts[2], "generation_id")  # type: ignore[return-value]


def build_consumer_snapshot(authoritative_latest: dict) -> dict:
    """Project one authoritative snapshot without recomputation or clock-dependent values."""
    meta = authoritative_latest.get("meta", {})
    run_id = validate_safe_id(meta.get("run_id"), "analysis_id")
    global_quality = meta.get("global_quality", {})
    return {
        "consumer_contract_version": CONSUMER_CONTRACT_VERSION,
        "source_identity": {
            "analysis_id": run_id,
            "generation_id": source_generation_id(authoritative_latest),
        },
        "meta": {
            **{field: copy.deepcopy(meta.get(field)) for field in CONSUMER_META_FIELDS},
            "global_quality": {
                "critical_missing": copy.deepcopy(global_quality.get("critical_missing", [])),
                "warnings": copy.deepcopy(global_quality.get("warnings", [])),
            },
        },
        "user_view": copy.deepcopy(authoritative_latest.get("user_view")),
    }


def validate_consumer_snapshot(
    consumer: dict,
    authoritative_latest: dict,
    *,
    pointer: dict | None = None,
    manifest: dict | None = None,
) -> None:
    """Validate the lightweight projection and bind it to its authoritative generation."""
    if consumer.get("consumer_contract_version") != CONSUMER_CONTRACT_VERSION:
        raise ContractError("unsupported consumer contract version")
    meta = consumer.get("meta") or {}
    if meta.get("status") != "success":
        raise ContractError("consumer requires status=success")
    if meta.get("failure_reason") is not None:
        raise ContractError("successful consumer requires failure_reason=null")
    if meta.get("global_quality", {}).get("critical_missing") != []:
        raise ContractError("consumer requires critical_missing=[]")
    validate_schema(consumer, CONSUMER_SCHEMA, "consumer snapshot")

    expected = build_consumer_snapshot(authoritative_latest)
    identity = consumer["source_identity"]
    if identity.get("generation_id") != expected["source_identity"]["generation_id"]:
        raise ContractError("consumer source generation ID mismatch")
    if identity.get("analysis_id") != expected["source_identity"]["analysis_id"]:
        raise ContractError("consumer analysis ID mismatch")
    for field, label in (
        ("run_id", "run ID"), ("source_sha256", "source SHA-256"),
        ("source_commit", "source commit"), ("source_snapshot", "source snapshot"),
    ):
        if meta.get(field) != expected["meta"].get(field):
            raise ContractError(f"consumer {label} mismatch")
    if consumer.get("user_view") != authoritative_latest.get("user_view"):
        raise ContractError("consumer user_view differs from authoritative snapshot")

    if pointer is not None:
        for field in ("analysis_id", "generation_id"):
            if identity.get(field) != pointer.get(field):
                raise ContractError(f"consumer {field.replace('_', ' ')} does not match current pointer")
        if meta.get("run_id") != pointer.get("run_id"):
            raise ContractError("consumer run ID does not match current pointer")
    if manifest is not None:
        for field in ("analysis_id", "generation_id"):
            if identity.get(field) != manifest.get(field):
                raise ContractError(f"consumer {field.replace('_', ' ')} does not match generation manifest")
        for field, label in (("run_id", "run ID"), ("source_sha256", "source SHA-256"), ("source_commit", "source commit")):
            if meta.get(field) != manifest.get(field):
                raise ContractError(f"consumer {label} does not match generation manifest")

    if canonical_bytes(consumer) != canonical_bytes(expected):
        raise ContractError("consumer projection differs from deterministic authoritative projection")
    size = len(canonical_bytes(consumer))
    if size > CONSUMER_CANONICAL_SIZE_LIMIT:
        raise ContractError(
            f"consumer canonical JSON exceeds {CONSUMER_CANONICAL_SIZE_LIMIT} bytes: {size}"
        )


def validate_legacy_full_consumer(
    consumer: dict,
    authoritative_latest: dict,
    *,
    pointer: dict | None = None,
    manifest: dict | None = None,
) -> None:
    """Validate the compatibility URL as an exact authoritative full snapshot."""
    if "consumer_contract_version" in consumer:
        raise ContractError("legacy compatibility consumer must remain a full snapshot")
    validate_schema(consumer, LATEST_SCHEMA, "legacy full-snapshot consumer")
    validate_public_latest(consumer, verify_source_hash=True)
    if canonical_bytes(consumer) != canonical_bytes(authoritative_latest):
        raise ContractError("legacy consumer export does not match authoritative current generation")


def validate_consumer_artifact(
    consumer: dict,
    authoritative_latest: dict,
    *,
    pointer: dict | None = None,
    manifest: dict | None = None,
) -> str:
    """Read-compatible validator retained for callers that inspect either format."""
    if "consumer_contract_version" in consumer:
        validate_consumer_snapshot(consumer, authoritative_latest, pointer=pointer, manifest=manifest)
        return "projection"
    validate_legacy_full_consumer(consumer, authoritative_latest, pointer=pointer, manifest=manifest)
    return "legacy_full_snapshot"
