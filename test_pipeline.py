import unittest
import pandas as pd
from pipeline import analyze, clean, sample_data


class PipelineTests(unittest.TestCase):
    def test_reproducible(self):
        a, b = sample_data()
        c, d = sample_data()
        pd.testing.assert_frame_equal(a, c)
        pd.testing.assert_frame_equal(b, d)

    def test_known_defects_and_totals(self):
        result = analyze(*sample_data())
        self.assertEqual(result["audit"]["source_rows"], 413)
        self.assertEqual(result["audit"]["accepted_rows"], 360)
        self.assertEqual(result["audit"]["reasons"], {"duplicate event id": 30, "unmatched asset": 8, "missing or negative measure": 12, "invalid date": 3})
        self.assertEqual(sum(x["cost_usd"] for x in result["accepted"]), result["clean_cost_usd"])
        self.assertEqual(sum(x["events"] for x in result["summary"]), 360)
        self.assertGreater(result["cost_distortion_usd"], 0)
        self.assertTrue(all(result["checks"].values()))

    def test_duplicate_dimension_is_rejected(self):
        events, assets = sample_data()
        with self.assertRaisesRegex(ValueError, "unique"):
            clean(events, pd.concat([assets, assets.iloc[:1]]))

    def test_duplicate_policy_keeps_first(self):
        events, assets = sample_data()
        good, bad, audit = clean(events, assets)
        self.assertEqual(float(good.loc[good.event_id == "E0000", "cost_usd"].iloc[0]), float(events.iloc[0].cost_usd))
        self.assertEqual(len(good) + len(bad), len(events))

    def test_empty_input_and_missing_identifier(self):
        events, assets = sample_data()
        result = analyze(events.iloc[:0], assets)
        self.assertEqual(result["clean_cost_usd"], 0)
        self.assertEqual(result["audit"]["source_rows"], 0)
        events.loc[0, "event_id"] = None
        good, bad, audit = clean(events, assets)
        self.assertEqual(audit["reasons"]["missing event id"], 1)

    def test_left_join_does_not_multiply_records(self):
        events, assets = sample_data()
        good, bad, audit = clean(events, assets)
        self.assertEqual(len(good), good.event_id.nunique())
        self.assertFalse(good.region.isna().any())


if __name__ == "__main__":
    unittest.main()
