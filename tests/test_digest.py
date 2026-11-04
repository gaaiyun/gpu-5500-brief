import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from digest import daily_digest


def state(**kw):
    base = {"date": "2026-10-30",
            "price_board": {"rows": [{"id": "theinformation_price", "label": "The Information 售价", "kind": "媒体报道",
                                      "since": "2026-10-21", "converted": False, "repriced": False}],
                            "changes": []},
            "fx": {"status": "ok", "label": "人民币汇率中间价", "date": "2026-10-29", "rates": {"USD": 6.7147}},
            "channel": {"watchlist": [{"model": "RTX PRO 6000 D 84G", "min_ask": 68500, "quote_date": "2026-10-16", "condition": "正常供应"}]},
            "checks": [{"source_id": "nvidia", "status": "ok", "signals": {"coming_soon": True}}],
            "feed": {"items": [], "leads": []}, "headlines": []}
    base.update(kw)
    return base


def baseline(**kw):
    base = state(date="2026-10-29", fx={"status": "ok", "label": "人民币汇率中间价", "date": "2026-10-28", "rates": {"USD": 6.7165}})
    base.update(kw)
    return base


class DigestTests(unittest.TestCase):
    def test_quiet_day_says_so_with_days_since_last_quote(self):
        result = daily_digest(state(fx=baseline()["fx"]), baseline())
        self.assertTrue(result["quiet"])
        self.assertEqual(result["days_since_quote"], 9)
        self.assertIn("距最近一次新报价 9 天", result["headline"])

    def test_large_rate_move_listed_but_not_counted_as_news(self):
        today = state(price_board=dict(state()["price_board"], changes=[{"id": "reuters_usd", "kind": "汇率", "delta": -900, "text": "路透订单价 -900 元"}]))
        old = baseline(fx={"status": "ok", "label": "人民币汇率中间价", "date": "2026-10-28", "rates": {"USD": 6.8}})
        result = daily_digest(today, old)
        fx = next(i for i in result["items"] if i["tag"] == "汇率")
        self.assertIn("6.8→6.7147", fx["text"])
        self.assertIn("-900", fx["text"])
        self.assertTrue(result["quiet"])

    def test_small_rate_move_stays_out_of_the_digest(self):
        today = state(price_board=dict(state()["price_board"], changes=[{"id": "reuters_usd", "kind": "汇率", "delta": -20, "text": "路透订单价 -20 元"}]))
        self.assertFalse([i for i in daily_digest(today, baseline())["items"] if i["tag"] == "汇率"])

    def test_backfilled_quote_listed_but_not_counted_as_news(self):
        today = state(price_board=dict(state()["price_board"], changes=[{"id": "old", "kind": "补录", "text": "补录 某报价 ¥85,000（原始日期 2026-10-09）"}]))
        result = daily_digest(today, baseline())
        self.assertEqual([i["tag"] for i in result["items"]][0], "补录")
        self.assertTrue(result["quiet"])

    def test_stock_change_counts_as_news(self):
        today = state(price_board=dict(state()["price_board"], changes=[{"id": "x", "kind": "货况", "text": "法国零售 货况：A → B"}]))
        result = daily_digest(today, baseline())
        self.assertFalse(result["quiet"])
        self.assertEqual(result["items"][0]["tag"], "货况")

    def test_related_news_is_listed_but_a_quiet_day_stays_quiet(self):
        item = {"id": "c", "title": "出口新规", "publisher": "FT", "grade": "B", "grade_label": "单一可信来源", "url": "https://x/c", "age_days": 0,
                "published_at": "2026-10-30", "scope": "context"}
        result = daily_digest(state(feed={"items": [item], "leads": []}), baseline())
        self.assertEqual(next(i for i in result["items"] if i["tag"] == "相关")["url"], "https://x/c")
        self.assertTrue(result["quiet"])
        self.assertIn("相关动态 1 条", result["headline"])

    def test_new_price_talk_and_channel_claims_are_flagged_unverified(self):
        mention = {"publisher": "算力圈", "low": 80000, "high": 95000, "url": "https://x/m", "date": "2026-10-30"}
        claim = {"publisher": "广州丽泰", "title": "将到 2000 片", "url": "https://x/c", "date": "2026-10-30"}
        result = daily_digest(state(feed={"items": [], "leads": [], "mentions": [mention], "channel": [claim]}), baseline())
        self.assertIn("算力圈称 8万-9.5万元", next(i for i in result["items"] if i["tag"] == "说法")["text"])
        self.assertIn("未核实", next(i for i in result["items"] if i["tag"] == "渠道")["text"])
        self.assertTrue(result["quiet"])
        self.assertFalse([i for i in daily_digest(state(feed={"items": [], "leads": [], "mentions": [mention], "channel": [claim]}),
                                                  baseline(feed={"items": [], "leads": [], "mentions": [mention], "channel": [claim]}))["items"] if i["tag"] in ("说法", "渠道")])

    def test_quiet_day_recalls_the_week(self):
        item = {"id": "a", "title": "彭博：只到约1%", "publisher": "彭博", "grade": "B", "grade_label": "x", "url": "https://x/a", "age_days": 3, "published_at": "2026-10-27"}
        old = {"id": "z", "title": "太旧", "publisher": "x", "grade": "B", "grade_label": "x", "url": "https://x/z", "age_days": 20, "published_at": "2026-10-10"}
        feed = {"items": [item, old], "leads": []}
        result = daily_digest(state(feed=feed), baseline(feed=feed))
        recent = [i for i in result["items"] if i["tag"] == "近7天"]
        self.assertEqual([i["text"] for i in recent], ["10-27 彭博：只到约1%"])
        self.assertTrue(result["quiet"])

    def test_quiet_day_says_what_was_searched(self):
        today = state(feed={"items": [], "leads": [], "sweep": {"candidates": 5, "read": 3, "added": []}})
        self.assertIn("读正文 3 篇", next(i for i in daily_digest(today, baseline())["items"] if i["tag"] == "检索")["text"])
        today = state(feed={"items": [], "leads": [], "sweep": {"candidates": 0, "read": 0, "added": []}})
        self.assertIn("没有发现", next(i for i in daily_digest(today, baseline())["items"] if i["tag"] == "检索")["text"])

    def test_other_cards_stay_out_of_the_digest(self):
        today = state(channel={"watchlist": [{"model": "RTX PRO 6000 D 84G", "min_ask": 67000, "quote_date": "2026-10-30", "condition": "正常供应"}]})
        result = daily_digest(today, baseline())
        self.assertFalse([i for i in result["items"] if "6000" in i["text"]])
        self.assertTrue(result["quiet"])

    def test_new_feed_items_and_leads_listed_once(self):
        feed = {"items": [{"id": "a", "title": "渠道报价约9.2万元", "publisher": "雷峰网", "grade": "B", "grade_label": "单一可信来源",
                           "url": "https://www.leiphone.com/a", "age_days": 0}],
                "leads": [{"title": "闲鱼挂价截图", "url": "https://www.goofish.com/x", "publisher": "闲鱼"}]}
        result = daily_digest(state(feed=feed), baseline())
        self.assertEqual([i["tag"] for i in result["items"] if i["tag"] in ("情报", "线索")], ["情报", "线索"])
        again = daily_digest(state(feed=feed), baseline(feed=feed))
        self.assertFalse([i for i in again["items"] if i["tag"] in ("情报", "线索")])

    def test_new_quote_resets_counter(self):
        board = {"rows": [{"id": "quote:1", "label": "团队询价 · 供应商报价", "kind": "团队询价", "since": "2026-10-30", "converted": False, "repriced": False}],
                 "changes": [{"id": "quote:1", "kind": "新报价", "text": "新增 团队询价 · 供应商报价 ¥92,000"}]}
        result = daily_digest(state(price_board=board), baseline())
        self.assertEqual(result["days_since_quote"], 0)
        self.assertFalse(result["quiet"])
        self.assertEqual(result["items"][0]["tag"], "新报价")

    def test_without_baseline_nothing_is_called_new(self):
        result = daily_digest(state(), {})
        self.assertFalse([i for i in result["items"] if i["tag"] in ("情报", "线索", "新闻")])


if __name__ == "__main__":
    unittest.main()
