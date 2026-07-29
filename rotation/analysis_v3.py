"""Deterministic auxiliary analysis and authoritative v3 presentation.

All paths are pure and offline.  Unavailable observations stay unavailable;
the module never substitutes estimates for absent market or fundamental data.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import math
from statistics import fmean

from .provenance import canonical_bytes

FLOW_NOTICE = "本分析でいうflowは、価格、相対強度、breadthなどから観測したローテーションの兆候であり、直接的な資金流入額・流出額を示すものではありません。"
FUNDAMENTAL_FIELDS = ("revenue_growth", "earnings_growth", "margin", "estimate_revisions", "orders_contracts", "capex", "management_outlook", "valuation", "theme_evidence")


def unavailable(source: str = "repository_fixture") -> dict:
    return {"status": "not_available", "value": None, "source": source, "as_of": None}


def display_percent(value, *, rank=None, threshold=None, comparison_text="") -> dict:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return {"raw_value": None, "display_value": "判定不能", "unit": "percent", "precision": 1,
                "rank": rank, "comparison_text": comparison_text, "threshold": threshold,
                "threshold_display": None if threshold is None else f"{threshold:+.1%}",
                "margin_to_threshold": None, "margin_to_threshold_display": "判定不能"}
    margin = None if threshold is None else value - threshold
    return {"raw_value": value, "display_value": f"{value:+.1%}", "unit": "percent", "precision": 1,
            "rank": rank, "comparison_text": comparison_text, "threshold": threshold,
            "threshold_display": None if threshold is None else f"{threshold:+.1%}",
            "margin_to_threshold": margin,
            "margin_to_threshold_display": "該当なし" if margin is None else f"{margin * 100:+.1f}pt"}


def threshold_assessment(observed, threshold: float, data_quality="complete") -> dict:
    if not isinstance(observed, (int, float)) or not math.isfinite(observed):
        return {"observed": None, "threshold": threshold, "margin": None, "passed": False,
                "borderline": False, "signal_confidence": "not_available", "classification_confidence": "not_available",
                "classification_change_boundary": threshold, "data_quality": data_quality, "missingness": ["observed"]}
    margin = observed - threshold
    confidence = "high" if abs(margin) >= .05 else "medium" if abs(margin) >= .02 else "low"
    return {"observed": observed, "threshold": threshold, "margin": margin, "passed": margin >= 0,
            "borderline": abs(margin) < .02, "signal_confidence": confidence,
            "classification_confidence": confidence, "classification_change_boundary": threshold,
            "data_quality": data_quality, "missingness": []}


def risk_adjusted_metrics(theme_returns: list[float], benchmark_returns: list[float], minimum_observations=20) -> dict:
    base = {"status": "not_available", "window": "daily_60_observations", "benchmark": "SPY",
            "minimum_observations": minimum_observations, "market_beta": None, "volatility": None,
            "beta_adjusted_return": None, "volatility_adjusted_return": None, "residual_momentum": None,
            "downside_relative_strength": None, "benchmark_comparison": "not_available"}
    pairs = [(float(a), float(b)) for a, b in zip(theme_returns, benchmark_returns)
             if isinstance(a, (int, float)) and isinstance(b, (int, float)) and math.isfinite(a) and math.isfinite(b)]
    if len(pairs) < minimum_observations: return base
    theme, bench = zip(*pairs); mb = fmean(bench); mt = fmean(theme)
    variance = fmean((x-mb)**2 for x in bench)
    beta = None if variance == 0 else fmean((x-mt)*(y-mb) for x, y in pairs) / variance
    vol = math.sqrt(fmean((x-mt)**2 for x in theme))
    residuals = [] if beta is None else [x-beta*y for x, y in pairs]
    downside = [x-y for x, y in pairs if y < 0]
    return {**base, "status": "available", "market_beta": beta, "volatility": vol,
            "beta_adjusted_return": None if beta is None else mt-beta*mb,
            "volatility_adjusted_return": None if vol == 0 else mt/vol,
            "residual_momentum": None if not residuals else fmean(residuals),
            "downside_relative_strength": None if not downside else fmean(downside),
            "benchmark_comparison": "above" if mt > mb else "below_or_equal"}


def multiple_comparison(score, universe_scores: list[float], persistence_weeks=None, retention=None, forward_returns=None) -> dict:
    usable = sorted(float(x) for x in universe_scores if isinstance(x, (int, float)) and math.isfinite(x))
    if not isinstance(score, (int, float)) or not usable:
        return {"status":"not_available", "method":"empirical_percentile_with_persistence_penalty", "universe_size":len(usable),
                "percentile":None, "adjusted_confidence":None, "single_week_penalty":None,
                "historical_retention":retention, "forward_return":{"status":"not_available","horizon_weeks":4,"sample_size":0,"mean":None}}
    percentile = sum(x <= score for x in usable) / len(usable)
    penalty = .15 if persistence_weeks in (None, 1) else 0
    adjusted = max(0, percentile - penalty) * (retention if isinstance(retention, (int,float)) else 1)
    forward = [x for x in (forward_returns or []) if isinstance(x,(int,float)) and math.isfinite(x)]
    return {"status":"available", "method":"empirical_percentile_with_persistence_penalty", "universe_size":len(usable),
            "percentile":percentile, "adjusted_confidence":adjusted, "single_week_penalty":penalty,
            "historical_retention":retention,
            "forward_return":{"status":"available" if len(forward)>=5 else "not_available", "horizon_weeks":4,
                              "sample_size":len(forward), "mean":fmean(forward) if len(forward)>=5 else None}}


def persistence_statistics(current_classification: str, current_value, history: list[dict]) -> dict:
    ordered = sorted(history, key=lambda x: x.get("data_date", ""))
    if not ordered:
        return {"analysis_mode":"initial_observation","signal_persistence_weeks":None,"prior_generation_delta":None,
                "classification_churn":None,"selection_status":"initial_observation","historical_retention":None,"history_insufficient":True}
    prior=ordered[-1]; classes=[x.get("classification") for x in ordered]+[current_classification]
    churn=sum(a!=b for a,b in zip(classes,classes[1:]))/max(1,len(classes)-1)
    persistence=1
    for classification in reversed(classes[:-1]):
        if classification != current_classification: break
        persistence+=1
    retained=sum(a==b for a,b in zip(classes,classes[1:]))/max(1,len(classes)-1)
    prior_value=prior.get("value"); delta=current_value-prior_value if isinstance(current_value,(int,float)) and isinstance(prior_value,(int,float)) else None
    return {"analysis_mode":"trend","signal_persistence_weeks":persistence,"prior_generation_delta":delta,
            "classification_churn":churn,"selection_status":"continuing" if persistence>1 else "new",
            "historical_retention":retained,"history_insufficient":False}


def fundamental_confirmation(record: dict | None, price_confirmed: bool | None) -> dict:
    record = record or {}; fields = {name: record.get(name, unavailable()) for name in FUNDAMENTAL_FIELDS}
    assessed = [v for v in fields.values() if isinstance(v, dict) and v.get("status") == "available"]
    positive = any(v.get("confirmation") is True for v in assessed)
    if price_confirmed is None and not assessed: status = "not_assessed"
    elif price_confirmed and positive: status = "price_and_fundamentals"
    elif price_confirmed: status = "price_only"
    elif positive: status = "fundamentals_only"
    else: status = "unconfirmed"
    return {"status": status, "adapter": "repository_point_in_time_fundamentals_v1", "fields": fields,
            "coverage": len(assessed)/len(FUNDAMENTAL_FIELDS)}


def _themes(snapshot: dict) -> list[tuple[str, dict]]:
    return sorted((snapshot.get("themes") or {}).items())


def point_in_time_constituents(snapshot: dict) -> list[dict]:
    date = snapshot["meta"]["data_date"]; universe = snapshot["meta"].get("universe_definition") or {}
    output=[]
    for theme_id, theme in _themes(snapshot):
        rows=[{"ticker":r.get("ticker"), "role":r.get("role"), "inclusion_reason":"effective_on_data_date"}
              for r in theme.get("constituents") or [] if r.get("ticker")]
        output.append({"theme_id":theme_id, "constituents":rows, "constituent_snapshot_date":date,
                       "source":"authoritative_generation", "constituents_hash":hashlib.sha256(canonical_bytes(rows)).hexdigest(),
                       "universe_version":str(universe.get("version") or universe.get("config_version") or "unknown"),
                       "exclusion_reasons":[], "missing_tickers":[],
                       "unavailable_tickers":[r.get("ticker") for r in theme.get("constituents") or [] if r.get("valid") is False]})
    return output


def overlap_clusters(snapshot: dict) -> list[dict]:
    themes={k:{r.get("ticker") for r in v.get("constituents") or [] if r.get("ticker")} for k,v in _themes(snapshot)}
    parent={k:k for k in themes}
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    candidate_tickers={}
    for candidate in snapshot.get("company_candidates") or []:
        candidate_tickers.setdefault(candidate.get("ticker"),set()).add(candidate.get("theme_id"))
    pairs=[]
    for i,a in enumerate(sorted(themes)):
        for b in sorted(themes)[i+1:]:
            shared=sorted(themes[a]&themes[b]); union=themes[a]|themes[b]; j=len(shared)/len(union) if union else 0
            overlap=len(shared)/min(len(themes[a]),len(themes[b])) if themes[a] and themes[b] else 0
            metrics_a=(snapshot["themes"][a].get("metrics") or {}); metrics_b=(snapshot["themes"][b].get("metrics") or {})
            corr="not_available"
            pairs.append({"theme_a":a,"theme_b":b,"constituent_overlap_rate":overlap,"jaccard_similarity":j,
                          "shared_top_constituents":shared[:5],"theme_return_correlation":corr,
                          "common_factor_exposure":sorted(set(metrics_a.get("factor_exposure") or [])&set(metrics_b.get("factor_exposure") or [])),
                          "duplicate_company_candidates":sorted(t for t,ids in candidate_tickers.items() if a in ids and b in ids)})
            if j>=.5: parent[find(b)]=find(a)
    groups={}
    for t in sorted(themes): groups.setdefault(find(t),[]).append(t)
    representatives={t:min(v) for t,v in groups.items()}
    for p in pairs:
        root=find(p["theme_a"]); p.update({"cluster_id":hashlib.sha256("|".join(groups[root]).encode()).hexdigest()[:12],
            "representative_theme":representatives[root], "breadth_overstatement_warning":p["jaccard_similarity"]>=.5,
            "independence_status":"overlapping" if p["jaccard_similarity"]>=.5 else "distinct"})
    return pairs


def coverage(snapshot: dict, fundamentals: dict) -> dict:
    themes=_themes(snapshot); configured=len(themes); complete=partial=unavailable_count=0; missing=[]
    prices=constituents=0; total=0
    for theme_id, theme in themes:
        rows=theme.get("constituents") or []; total+=len(rows); constituents+=sum(bool(r.get("ticker")) for r in rows)
        usable=sum(isinstance(r.get("return_4w"),(int,float)) for r in rows); prices+=usable
        if rows and usable==len(rows): complete+=1
        elif usable: partial+=1
        else: unavailable_count+=1; missing.append({"theme_id":theme_id,"reason":"price_data_unavailable"})
    ratio=complete/configured if configured else 0
    return {"configured_theme_count":configured,"evaluated_theme_count":complete,"partial_theme_count":partial,
            "unavailable_theme_count":unavailable_count,"missing_themes":missing,
            "constituent_coverage":constituents/total if total else 0,"price_coverage":prices/total if total else 0,
            "fundamental_coverage":sum(x["coverage"] for x in fundamentals.values())/configured if configured else 0,
            "status":"ok" if ratio>=.75 else "warning" if ratio>=.5 else "critical_missing",
            "warning":None if ratio>=.75 else "coverage不足のため該当なしとは結論しません。"}


def build_authoritative_v3(snapshot: dict) -> dict:
    themes=_themes(snapshot); scores=[(t.get("metrics") or {}).get("equal_weight_rel_spy_4w") for _,t in themes]
    fundamentals={tid:fundamental_confirmation((snapshot.get("fundamentals") or {}).get(tid),
        bool((theme.get("classifications") or {}).get("candidate"))) for tid,theme in themes}
    assessments=[]
    for rank,(tid,theme) in enumerate(sorted(themes,key=lambda x:((x[1].get("metrics") or {}).get("equal_weight_rel_spy_4w") is None,-((x[1].get("metrics") or {}).get("equal_weight_rel_spy_4w") or 0),x[0])),1):
        metric=(theme.get("metrics") or {}).get("equal_weight_rel_spy_4w")
        assessments.append({"theme_id":tid,"theme_display_name":theme.get("label",tid),"display_metric":display_percent(metric,rank=rank,threshold=.05),
            "threshold_assessment":threshold_assessment(metric,.05,(theme.get("quality") or {}).get("status","unknown")),
            "risk_adjustment":risk_adjusted_metrics(theme.get("daily_returns") or [],theme.get("benchmark_daily_returns") or []),
            "multiple_comparison":multiple_comparison(metric,scores,1,None,theme.get("forward_returns_4w")),
            "persistence":persistence_statistics(str((theme.get("classifications") or {}).get("candidate","unconfirmed")),metric,
                (snapshot.get("theme_history_v3") or {}).get(tid,[])),
            "fundamental_confirmation":fundamentals[tid]})
    candidates=[]
    for order,item in enumerate(snapshot.get("company_candidates") or [],1):
        tid=item.get("theme_id"); role=item.get("selection_role","other")
        candidates.append({"theme_id":tid,"theme_display_name":item.get("theme_label") or tid,"ticker":item.get("ticker"),
            "company_name":item.get("company_name") or item.get("ticker"),"candidate_role":role if role in {"representative","breadth_check"} else "other",
            "theme_rank":order,"selection_reason":item.get("why") or "producerの決定論的候補選定",
            "primary_check":item.get("key_check") or "not_available","counter_evidence":item.get("counter_evidence") or "not_available",
            "candidate_status":"research_candidate","data_quality":"available","source_fields":["/company_candidates"],
            "fundamental_confirmation_status":fundamentals.get(tid,{"status":"not_assessed"})["status"],
            "non_recommendation_notice":"テーマ検証の観測候補であり、売買推奨ではありません。"})
    cov=coverage(snapshot,fundamentals); constituents=point_in_time_constituents(snapshot); overlaps=overlap_clusters(snapshot)
    meta=snapshot["meta"]; mode="initial_observation"
    classification=[]
    buckets=snapshot.get("candidate_buckets") or {}
    labels={"research_now":"今調べる候補","watch_recovery":"条件改善待ち","long_term_context_price_weak":"長期文脈はあるが価格が弱い候補","avoid_now":"現時点では調査優先度が低い候補"}
    for key,label in labels.items(): classification.append({"classification":key,"display_name":label,"status":"present" if buckets.get(key) else "none_assessed","theme_ids":[x.get("id") for x in buckets.get(key) or []]})
    summary={"market_conclusion":f"市場分類: {((snapshot.get('market_regime') or {}).get('classification') or {}).get('primary_regime','判定不能')}",
        "research_priorities":[c["theme_id"] for c in candidates[:3]],"classification_summary":classification,
        "company_summary":[{"ticker":c["ticker"],"theme_id":c["theme_id"],"candidate_role":c["candidate_role"]} for c in candidates[:6]],
        "main_cautions":[FLOW_NOTICE]+([cov["warning"]] if cov["warning"] else []),"next_update_checks":["相対強度、breadth、threshold marginの変化"],
        "data_date_display":meta["data_date"],"generated_at_display":meta["generated_at"],"validity_status_display":"有効期限をmanifestで確認",
        "analysis_mode_display":mode}
    handoffs=[{"handoff_contract_version":"1.0","generation_id":snapshot.get("meta",{}).get("source_snapshot","").split("/")[-2],
        "data_date":meta["data_date"],"theme_id":c["theme_id"],"theme_status":"research_candidate","ticker":c["ticker"],
        "candidate_role":c["candidate_role"],"selection_reason":c["selection_reason"],"primary_checks":[c["primary_check"]],
        "counter_evidence":[c["counter_evidence"]],"price_signal_status":"available","fundamental_confirmation_status":c["fundamental_confirmation_status"],
        "data_quality":c["data_quality"],"warnings":[c["non_recommendation_notice"]]} for c in candidates]
    common={"data_date_display":meta["data_date"],"generated_at_display":meta["generated_at"],"analysis_mode_display":mode,"flow_notice":FLOW_NOTICE}
    phases={1:{"phase":1,**common,"coverage":cov,"theme_assessments":assessments},2:{"phase":2,"price_path":assessments},
            3:{"phase":3,"point_in_time_constituents":constituents,"overlap_clusters":overlaps},
            4:{"phase":4,"classification_summary":classification,"explicit_avoid":[]},
            5:{"phase":5,"companies":candidates,"non_recommendation_notice":"企業候補は売買推奨ではありません。"},
            6:{"phase":6,**summary}}
    details={i:{"phase":i,"traceability":{"source_fields":[f"/v3/phases/{i}"]},"methodology":phases[i]} for i in range(1,6)}
    details[6]={"phase":6,"traceability":{"source_fields":["/v3/phases/6"]},"methodology":{"summary_contract":"dedicated_no_phase5_duplication"}}
    return {"phases":phases,"details":details,"handoffs":handoffs,"coverage":cov,"constituent_snapshots":constituents,"overlap_clusters":overlaps}
