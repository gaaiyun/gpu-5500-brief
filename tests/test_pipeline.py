import importlib.util
import unittest
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("update", ROOT / "scripts/update.py")
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.evidence = update.read_json(ROOT / "data/evidence.json")
        self.checks = [{"source_id":"smm","status":"ok"}, {"source_id":"nvidia","status":"ok","signals":{"coming_soon":True}}]

    def test_challenge_page_rejected(self):
        with self.assertRaises(ValueError):
            update.extract_signals("nvidia", "Please verify you are human")

    def test_missing_coming_soon_needs_review(self):
        signals = update.extract_signals("nvidia", "NVIDIA RTX PRO 5500 84 GB Specifications")
        self.assertTrue(signals["needs_review"])
        self.assertNotIn("released", signals)

    def test_smm_historical_quote_required(self):
        with self.assertRaises(ValueError):
            update.extract_signals("smm", "RTX PRO 5500 9.5万元/张 行业预测")

    def test_aggregate_always_excluded(self):
        self.assertTrue(update.extract_signals("qudao", "RTX PRO 5500 91400")["excluded"])

    def forecast(self):
        return {"forecast": {"version": "2026-10-29-v2", "issued_at": "2026-10-29", "horizon_end": "2026-12-28",
                             "anchor_source_id": "trendforce", "anchor_observed_at": "2026-10-21"}}

    def test_forecast_date_does_not_roll(self):
        checks = self.checks + [{"source_id": "trendforce", "status": "ok"}]
        review = update.forecast_status(self.forecast(), checks, date(2026, 10, 30))
        self.assertEqual(review["issued_at"], "2026-10-29")
        self.assertEqual(review["status"], "low_confidence")

    def test_anchor_source_is_the_one_checked(self):
        review = update.forecast_status(self.forecast(), self.checks, date(2026, 10, 30))
        self.assertIn("预测锚点来源本轮未成功复现", review["reasons"])

    def test_old_anchor_disables_numbers(self):
        review = update.forecast_status(self.forecast(), self.checks, date(2026, 11, 20))
        self.assertTrue(review["numeric_forecast_active"])
        review = update.forecast_status(self.forecast(), self.checks, date(2026, 11, 21))
        self.assertFalse(review["numeric_forecast_active"])
        self.assertEqual(review["status"], "expired")

    def test_forecast_versions_are_well_formed(self):
        versions = self.evidence.get("forecast_history", []) + [self.evidence["forecast"]]
        prices = {p["id"] for p in self.evidence["prices"]}
        for f in versions:
            self.assertIn(f["anchor_price_id"], prices)
            ids = [s["id"] for s in f["scenarios"]]
            self.assertEqual(ids, ["soft", "base", "tight"])
            bands = [(s["low"], s["high"]) for s in f["scenarios"]]
            self.assertTrue(all(lo < hi for lo, hi in bands))
            self.assertTrue(all(a[1] == b[0] for a, b in zip(bands, bands[1:])))

    def test_failure_keeps_last_success(self):
        original = update.fetch
        update.fetch = lambda _: (_ for _ in ()).throw(RuntimeError("network unavailable"))
        try:
            result = update.check_source(self.evidence["sources"][0], {"last_success_at":"2026-10-24T00:35:00+08:00", "signals":{"coming_soon":True}}, "2026-10-25T00:35:00+08:00")
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["last_success_at"], "2026-10-24T00:35:00+08:00")
            self.assertTrue(result["signals"]["coming_soon"])
        finally:
            update.fetch = original

    def test_headlines_cannot_be_prices(self):
        xml = b'<rss><channel><item><title>RTX PRO 5500 price 95000</title><link>https://example.com/a</link><pubDate>Sun, 25 Oct 2026 01:00:00 GMT</pubDate><source url="https://example.com">Example</source></item></channel></rss>'
        items = update.parse_feed(xml, "test", "2026-10-25T20:00:00+08:00")
        self.assertEqual(items[0]["verification"], "headline_only")
        self.assertNotIn("value_cny", items[0])

    def test_reprinted_headlines_merge(self):
        item = lambda pub, day: f'<item><title>天阳科技公告签署销售合同 采购2万张英伟达RTX PRO 5500 GPU - {pub}</title><link>https://example.com/{pub}</link><pubDate>{day} Oct 2026 01:00:00 GMT</pubDate><source url="https://example.com">{pub}</source></item>'
        xml = ('<rss><channel>' + item('第一财经', 'Tue, 13') + item('证券时报', 'Wed, 14') + item('财富号', 'Wed, 14') + '</channel></rss>').encode()
        rows = update.merge_headlines([{"entries": update.parse_feed(xml, "test", "2026-10-25T20:00:00+08:00")}])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "天阳科技公告签署销售合同 采购2万张英伟达RTX PRO 5500 GPU")
        self.assertEqual(rows[0]["publisher"], "第一财经")
        # Self-media reposts are not listed even as reprints.
        self.assertEqual(rows[0]["reprints"], ["证券时报"])

    def test_changes_compare_against_previous_day(self):
        self.assertEqual(update.previous_day_state(date(2026, 10, 26))["date"], "2026-10-25")
        self.assertEqual(update.previous_day_state(date(2026, 10, 1)), {})

    def test_unknown_or_future_dates_rejected(self):
        xml = b'<rss><channel><item><title>RTX PRO 5500</title><link>https://example.com</link><pubDate>Sun, 25 Oct 2036 01:00:00 GMT</pubDate></item></channel></rss>'
        self.assertEqual(update.parse_feed(xml, "test", "2026-10-25T20:00:00+08:00"), [])


if __name__ == "__main__":
    unittest.main()
