# Fixtures

このフォルダのJSONは、すべて**架空のテストデータ**であり、実在する市場・企業・投資判断を表さない。

| file | purpose |
|---|---|
| `latest_normal.json` | 正常・広範risk-on・theme拡散＋改善 |
| `latest_missing.json` | 必須field欠損、coverage/history不足 |
| `latest_overheat_outflow.json` | 価格過熱と流出示唆の同時成立 |
| `latest_single_name_concentration.json` | 一銘柄集中、market-cap主導、peripheral偏重 |
| `latest_p1_diffusion.json` | P1だけが成立する拡散・inflow例 |
| `latest_p2_overheat_diffusion.json` | P2だけが成立する過熱＋拡散flag・inflow例 |
| `latest_p5_low_priority.json` | P5へ到達する全期間非正・generated flow-suggested/outflow例 |
| `judgment_record.json` | 正常fixtureから作るimmutable判断記録 |
| `theme_master.json` | 6銘柄、3role、重複許可の最小master |

日付、commit、hashは形式検証用の固定値である。実装testではcurrent timeへ依存させず、clockを注入または固定する。
