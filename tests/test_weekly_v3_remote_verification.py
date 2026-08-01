from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WeeklyV3RemoteVerificationTests(unittest.TestCase):
    def test_remote_verification_ignores_retained_immutable_generations(self):
        workflow = (ROOT / ".github" / "workflows" / "weekly.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            'cmp "$VERIFY_ROOT/output/consumer/v3/manifest.json" '
            '"$VERIFY_EXPORT/v3/manifest.json"',
            workflow,
        )
        self.assertIn('V3_GENERATION_ID="$(python - ', workflow)
        self.assertIn(
            '"$VERIFY_ROOT/output/consumer/v3/generations/$V3_GENERATION_ID"',
            workflow,
        )
        self.assertIn(
            '"$VERIFY_EXPORT/v3/generations/$V3_GENERATION_ID"',
            workflow,
        )
        self.assertIn(
            'find "$VERIFY_EXPORT/v3/generations" -mindepth 1 -maxdepth 1 -type d',
            workflow,
        )
        self.assertNotIn(
            'diff -qr "$VERIFY_ROOT/output/consumer/v3" "$VERIFY_EXPORT/v3"',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
