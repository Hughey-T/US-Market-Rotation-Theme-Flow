from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CustomGPTStaleCacheContractTests(unittest.TestCase):
    def test_moving_manifests_are_cache_busted_and_cross_checked(self):
        text = (
            ROOT / "docs" / "custom_gpt_instructions_current.md"
        ).read_text(encoding="utf-8")

        self.assertLessEqual(len(text), 8000)
        for required in (
            "正本指示 1.8.3",
            "output/current.json",
            "16桁以上の英数字nonce",
            "?cb=<nonce>",
            "前回キャッシュを使用しない",
            "currentの`generation_id`",
            "新しいnonceで一度だけ両方を再取得",
            "E_FETCH_TRANSIENT",
            "queryは取得時のcache回避専用",
        ):
            self.assertIn(required, text)


if __name__ == "__main__":
    unittest.main()
