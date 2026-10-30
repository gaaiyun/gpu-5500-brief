import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import alerts

TZ = timezone(timedelta(hours=8))
NOON = datetime(2026, 10, 31, 14, 10, tzinfo=TZ)


def row(rid, kind, native, day="2026-10-31", **kw):
    base = {"id": rid, "label": rid, "kind": kind, "url": f"https://example.com/{rid}", "date": day, "native": native,
            "quote_key": native, "converted": False, "cny_vat": None, "text": native, "note": ""}
    return dict(base, **kw)


def listing(price, cny_vat):
    native = f"€{price:,.2f}（含当地增值税 20%）"
    return row("de_b2b", "海外零售", native, "2026-10-30", label="德国 B2B", quote_key=f"{price}EUR", price=price,
               converted=True, cny_vat=cny_vat, text=f"≈¥{cny_vat:,} 含税")


def state(*rows, day="2026-10-31"):
    return {"date": day, "price_board": {"rows": list(rows), "domestic": {"low": 85000, "high": 95000, "count": 4}}}


def log(day="2026-10-31", **kw):
    return dict({"dingtalk": day, "pushplus": day}, **kw)


class EventTests(unittest.TestCase):
    def test_new_team_quote_is_news(self):
        quote = row("quote:7", "团队询价", "¥88,000", label="团队询价 · 供应商报价", note="含税；未公开核实")
        found = alerts.events(state(quote), state())
        self.assertEqual(len(found), 1)
        self.assertIn("¥88,000", found[0]["text"])
        self.assertIn("未公开核实", found[0]["text"])

    def test_retail_repricing_shows_both_prices_and_the_move(self):
        found = alerts.events(state(listing(13500.0, 113755)), state(listing(13894.0, 117077)))
        self.assertEqual(len(found), 1)
        text = found[0]["text"]
        self.assertIn("€13,894.00 → €13,500.00", text)
        self.assertIn("-2.8%", text)
        self.assertIn("≈¥113,755 含税", text)
        self.assertEqual(found[0]["tag"], "海外零售")

    def test_first_sighting_of_a_listing_is_not_news(self):
        self.assertEqual(alerts.events(state(listing(13894.0, 117077)), state()), [])

    def test_rate_move_is_not_news(self):
        self.assertEqual(alerts.events(state(listing(13894.0, 117500)), state(listing(13894.0, 117077))), [])

    def test_backfilled_old_report_is_not_news(self):
        old = row("feed:x", "媒体报道", "¥92,000", day="2026-10-20")
        self.assertEqual(alerts.events(state(old), state()), [])

    def test_changed_channel_quote_is_news_whatever_its_date(self):
        before = row("channel_min_ask", "渠道挂牌", "¥86,000", day="2026-09-22", quote_key="86000@2026-09-22")
        after = dict(before, native="¥84,000", quote_key="84000@2026-09-22")
        found = alerts.events(state(after), state(before))
        self.assertIn("¥86,000 → ¥84,000", found[0]["text"])

    def test_big_move_flagged_for_review(self):
        found = alerts.events(state(listing(9900.0, 83420)), state(listing(13894.0, 117077)))
        self.assertIn("待人工核对", found[0]["text"])

    def test_without_a_report_nothing_is_news(self):
        self.assertEqual(alerts.events(state(listing(13500.0, 113755)), None), [])


class PolicyTests(unittest.TestCase):
    def test_daytime_after_the_morning_report_may_send(self):
        self.assertIsNone(alerts.blocked(log(), NOON))

    def test_quiet_at_night(self):
        self.assertIn("夜间", alerts.blocked(log(), NOON.replace(hour=23)))
        self.assertIn("夜间", alerts.blocked(log(), NOON.replace(hour=7)))

    def test_waits_for_the_morning_report(self):
        self.assertIn("晨报", alerts.blocked(log(day="2026-10-30"), NOON))

    def test_two_alerts_a_day(self):
        sent = [{"at": "2026-10-31T09:10", "keys": ["a"]}, {"at": "2026-10-31T11:10", "keys": ["b"]}]
        self.assertIn("2 次", alerts.blocked(log(alerts=sent), NOON))
        self.assertIsNone(alerts.blocked(log(alerts=sent[:1] + [{"at": "2026-10-30T15:10", "keys": ["c"]}]), NOON))

    def test_sent_events_are_not_repeated(self):
        found = [{"key": "a"}, {"key": "b"}]
        self.assertEqual(alerts.unsent(found, log(alerts=[{"at": "2026-10-29T09:10", "keys": ["a"]}])), [{"key": "b"}])

    def test_record_keeps_a_week(self):
        old = {"at": "2026-10-20T09:10", "keys": ["old"]}
        updated = alerts.record(log(alerts=[old]), [{"key": "new"}], ["dingtalk"], NOON)
        self.assertEqual([p["keys"] for p in updated["alerts"]], [["new"]])
        self.assertEqual(updated["dingtalk"], "2026-10-31")


class MainTests(unittest.TestCase):
    def test_first_run_sets_baseline_then_finds_news(self):
        import json
        import os
        import tempfile
        from unittest import mock
        import push_log
        saved = (push_log.PATH, push_log.STATE, push_log.REPORTED)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {}, clear=False):
            for key in ("DINGTALK_WEBHOOK", "PUSHPLUS_TOKEN"):
                os.environ.pop(key, None)
            push_log.PATH, push_log.STATE, push_log.REPORTED = Path(tmp) / "push_log.json", Path(tmp) / "state.json", Path(tmp) / "reported"
            try:
                push_log.save(log())
                push_log.STATE.write_text(json.dumps(state(listing(13894.0, 117077))), encoding="utf-8")
                self.assertEqual(alerts.main(NOON.replace(hour=23)), 0)
                self.assertFalse(push_log.REPORTED.exists())
                self.assertEqual(alerts.main(NOON), 0)
                self.assertTrue((push_log.REPORTED / "2026-10-31.json").exists())
                push_log.STATE.write_text(json.dumps(state(listing(13500.0, 113755))), encoding="utf-8")
                with mock.patch.object(alerts, "send", side_effect=AssertionError("no channel configured")) as send:
                    self.assertEqual(alerts.main(NOON), 0)
                    send.assert_not_called()
                self.assertNotIn("alerts", push_log.load())
            finally:
                push_log.PATH, push_log.STATE, push_log.REPORTED = saved


class MessageTests(unittest.TestCase):
    def test_dingtalk_text_carries_keyword_and_plain_links(self):
        found = alerts.events(state(listing(13500.0, 113755)), state(listing(13894.0, 117077)))
        msg = alerts.dingtalk_message(found, state(), {"low": 85000, "high": 90000}, NOON)
        self.assertIn("5500", msg["markdown"]["title"])
        self.assertIn("https://example.com/de_b2b", msg["markdown"]["text"])
        self.assertNotIn("](", msg["markdown"]["text"])
        self.assertIn("85,000-90,000", msg["markdown"]["text"])


if __name__ == "__main__":
    unittest.main()
