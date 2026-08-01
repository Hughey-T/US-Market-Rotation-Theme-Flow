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
            "正本指示 1.8.0",
            "1 tool callにつき1 URL",
            "複数URLの同時open、並列取得、batch取得を禁止",
            "current→latest manifest→immutable generation manifest",
            "各partを検証してから次の1 partだけを取得",
            "`更新`ではPhase1以外、detail、handoffを取得しない",
            "`次`でも次の1 Phase以外を先読みしない",
            "同一応答内でbatch方式へ切り替えない",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
