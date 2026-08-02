from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CustomGPTSequentialFetchBudgetTests(unittest.TestCase):
    def test_instructions_require_bounded_sequential_fetches(self):
        text = (ROOT / "docs" / "custom_gpt_instructions_current.md").read_text(
            encoding="utf-8"
        )
        self.assertLessEqual(len(text), 8000)
        for required in (
            "正本指示 1.8.5",
            "1 tool callにつき1 URL",
            "複数URLの同時open、並列取得、batch取得を禁止",
            "current→latest manifest→immutable generation manifest",
            "各partを検証してから次の1 partだけを取得",
            "`更新`ではPhase1以外、detail、handoffを取得しない",
            "`次`でも次の1 Phase以外を先読みしない",
            "同一応答内でbatch方式へ切り替えない",
            "同一応答内で該当URLを1回だけ直列再取得",
            "再試行にも失敗した場合だけ`E_FETCH_TRANSIENT`",
            "1回のassistant応答内で対象Phaseを最後まで完了する",
            "途中報告・処理予告・確認文だけを単独回答として返し",
            "完全な対象Phaseまたは規定エラーのどちらかだけを返す",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
