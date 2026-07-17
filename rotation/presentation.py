"""Plain-Japanese six-stage presentation layer."""
from __future__ import annotations

from .metrics import finite

REGIME_LABELS = {
    "broad_risk_on": "上昇する銘柄や業種が広がりつつあります",
    "large_growth_concentration": "大型成長株の一部に上昇が偏っています",
    "defensive_shift": "値動きの安定した業種が選ばれています",
    "real_asset_leadership": "資源関連の株価が市場平均より強くなっています",
    "cyclical_recovery_expectation": "景気敏感株に回復期待が表れています",
    "liquidity_contraction": "市場全体でリスクを取りにくい状態です",
    "mixed": "強い動きと弱い動きが混在しています",
    "directionless": "市場全体に明確な方向感はありません",
    "unclassifiable": "利用できるデータが足りず、市場の方向はまだ判断できません",
}


def _names(items: list[dict]) -> str:
    return "、".join(item["label"] for item in items) if items else "該当なし"


def _section(conclusion: str, meaning: str, cautions: list[str], next_checks: list[str]) -> dict:
    return {"conclusion": conclusion, "investment_meaning": meaning, "cautions": cautions, "next_checks": next_checks}


def build_user_view(*, regime: dict, style_factor: dict, sectors: dict, industries: dict, themes: dict, dynamic: dict, buckets: dict, companies: list[dict], history_weeks: int) -> dict:
    initial = history_weeks < 3
    primary = regime.get("classification", {}).get("primary_regime", "unclassifiable")
    phase1 = _section(
        REGIME_LABELS.get(primary, REGIME_LABELS["unclassifiable"]) + "。",
        "市場全体の広がりを確認してから、新規調査の範囲を決めます。",
        ([f"今回は初期観測のため、現在の強弱だけを評価しています。変化の判定にはあと{3-history_weeks}週分の履歴が必要です。"] if initial else []) + ["実際の資金流入額は確認できません。"],
        ["市場平均を上回る業種の数が次週も増えるか"],
    )
    ranked_style = sorted((value.get("rel_spy_4w"), value.get("label")) for value in style_factor.values() if finite(value.get("rel_spy_4w")) is not None)
    strong_style = ranked_style[-1][1] if ranked_style else "判断できません"
    phase2 = _section(f"現在は「{strong_style}」が相対的に強い状態です。", "強いスタイルと逆方向の銘柄は、調査の優先度を下げます。", ["ETFは傾向を示す代理指標で、個別企業の質を保証しません。"], ["最近の強さが長めの傾向と一致するか"])
    dynamic_names = [dynamic["candidates"][key]["label"] for key in dynamic.get("candidate_ids", [])]
    top_sector = sectors.get("rank_by_rel_spy_4w", [])[:3]
    sector_labels = [sectors["etfs"][key]["label"] for key in top_sector]
    phase3 = _section(
        f"強いセクターは{'、'.join(sector_labels) if sector_labels else '確認できません'}です。固定テーマ外では{'、'.join(dynamic_names) if dynamic_names else '新しい候補は見つかっていません'}。",
        "固定テーマとは別に、複数企業へ強さが広がる業種だけを後続調査へ渡します。",
        ["単一企業だけの急騰や、構成企業が3社未満の業種は候補にしません。"],
        ["新たに見つかった業種の構成企業が市場平均を上回り続けるか"],
    )
    phase4 = _section(
        f"個別企業を調べる対象は{_names(buckets['research_now'])}です。条件・優先順位待ちは{_names(buckets['watch_recovery'])}、現在は避ける対象は{_names(buckets['avoid_now'])}です。",
        "条件を満たす対象が少ない週は、件数を埋めず現金余力と調査時間を温存します。",
        ["政策や長期材料が良くても、現在の株価が弱い対象は自動的に昇格しません。"],
        ["条件・優先順位待ちの対象が50日移動平均線と市場平均比を回復するか"],
    )
    company_text = "、".join(f"{item['ticker']}（{item['theme_label']}）" for item in companies) if companies else "該当なし"
    phase5 = _section(f"個別企業の調査候補は{company_text}です。", "1対象につき最大2社とし、代表企業と広がり確認用企業を分けて調べます。", ["候補は売買推奨ではなく、決算・競争力・割高感を調べる入口です。"], ["次回決算と会社見通しが株価の強さを裏付けるか"])
    phase6 = _section(
        f"今週は{REGIME_LABELS.get(primary, REGIME_LABELS['unclassifiable'])}。詳しく調べる対象は{_names(buckets['research_now'])}、条件・優先順位待ちは{_names(buckets['watch_recovery'])}、避ける対象は{_names(buckets['avoid_now'])}です。",
        f"個別企業は{company_text}から確認します。",
        ["直接的な資金フロー、過去時点の時価総額、決算直前日程は取得できない場合があります。"],
        ["市場の広がり、候補テーマの50日線上比率、企業業績の裏付けを次週確認します。"],
    )
    return {"presentation_version": "1.0", "analysis_mode": "initial_observation" if initial else "trend", "phases": [phase1, phase2, phase3, phase4, phase5, phase6]}


def render_phase(user_view: dict, phase_number: int) -> str:
    if phase_number not in range(1, 7):
        raise ValueError("phase_number must be 1..6")
    section = user_view["phases"][phase_number - 1]
    return "\n".join([
        f"今回わかったこと: {section['conclusion']}", "", "投資判断への意味", section["investment_meaning"], "", "注意点",
        *[f"- {value}" for value in section["cautions"]], "", "次に確認すること", *[f"- {value}" for value in section["next_checks"]],
    ])
