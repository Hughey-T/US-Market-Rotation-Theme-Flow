import unittest

from rotation.classification import evaluate_priority, evaluate_timing, priority_matches, timing_matches
from test_spec_cases import direct_theme, fixture_theme


class PriorityReachability(unittest.TestCase):
    def assert_priority(self, theme, value, rule):
        observed, observed_rule, _ = evaluate_priority(theme)
        self.assertEqual((observed, observed_rule), (value, rule))
        self.assertTrue(priority_matches(theme)[rule] if rule != "fallback" else True)

    def test_reachability_P0(self):
        self.assert_priority(direct_theme(eligible=False), "unclassifiable", "P0")

    def test_reachability_P1(self):
        self.assert_priority(fixture_theme("latest_p1_diffusion.json"), "dd_priority", "P1")

    def test_reachability_P2(self):
        self.assert_priority(fixture_theme("latest_p2_overheat_diffusion.json"), "dd_priority", "P2")

    def test_reachability_P3(self):
        theme = direct_theme(phase="initial", direction="improving", level="relative_preference_suggested", evidence_direction="inflow")
        self.assert_priority(theme, "dd_candidate", "P3")

    def test_reachability_P4(self):
        theme = direct_theme(phase="unclassifiable", direction="improving", concentrated=True)
        self.assert_priority(theme, "watch", "P4")

    def test_reachability_P5(self):
        self.assert_priority(fixture_theme("latest_p5_low_priority.json"), "low_priority", "P5")

    def test_reachability_priority_fallback(self):
        self.assert_priority(direct_theme(), "watch", "fallback")


class TimingReachability(unittest.TestCase):
    def assert_timing(self, theme, value, rule):
        observed, observed_rule, _ = evaluate_timing(theme)
        self.assertEqual((observed, observed_rule), (value, rule))
        self.assertTrue(timing_matches(theme)[rule] if rule != "fallback" else True)

    def test_reachability_T0(self):
        self.assert_timing(direct_theme(eligible=False), "unclassifiable", "T0")

    def test_reachability_T1(self):
        self.assert_timing(direct_theme(phase="price_overheat"), "price_overheat", "T1")

    def test_reachability_T2(self):
        self.assert_timing(direct_theme(direction="outflow_signal"), "deteriorating", "T2")

    def test_reachability_T3(self):
        self.assert_timing(direct_theme(phase="initial"), "early_unconfirmed", "T3")

    def test_reachability_T4(self):
        self.assert_timing(direct_theme(phase="diffusion", direction="flat"), "favorable", "T4")

    def test_reachability_timing_fallback(self):
        self.assert_timing(direct_theme(phase="unclassifiable", direction="improving"), "unclassifiable", "fallback")

    def test_T1_precedes_T2_but_direction_is_preserved(self):
        theme = direct_theme(phase="price_overheat", direction="outflow_signal")
        matches = timing_matches(theme)
        self.assertTrue(matches["T1"] and matches["T2"])
        self.assert_timing(theme, "price_overheat", "T1")
        self.assertEqual(theme["classifications"]["direction"], "outflow_signal")


if __name__ == "__main__":
    unittest.main()
