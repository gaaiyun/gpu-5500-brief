import importlib.util
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
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

    def test_forecast_date_does_not_roll(self):
        review = update.forecast_status(self.evidence, self.checks, date(2026, 10, 26))
        self.assertEqual(review["issued_at"], "2026-10-25")

    def test_old_anchor_disables_numbers(self):
        review = update.forecast_status(self.evidence, self.checks, date(2026, 11, 14))
        self.assertFalse(review["numeric_forecast_active"])
        self.assertEqual(review["status"], "expired")

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

    def test_unknown_or_future_dates_rejected(self):
        xml = b'<rss><channel><item><title>RTX PRO 5500</title><link>https://example.com</link><pubDate>Sun, 25 Oct 2036 01:00:00 GMT</pubDate></item></channel></rss>'
        self.assertEqual(update.parse_feed(xml, "test", "2026-10-25T20:00:00+08:00"), [])


if __name__ == "__main__":
    unittest.main()
