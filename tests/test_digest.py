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

    def test_rate_move_listed_but_not_counted_as_news(self):
        today = state(price_board=dict(state()["price_board"], changes=[{"id": "reuters_usd", "kind": "汇率", "delta": -20, "text": "路透订单价 -20 元"}]))
        result = daily_digest(today, baseline())
        fx = next(i for i in result["items"] if i["tag"] == "汇率")
        self.assertIn("6.7165→6.7147", fx["text"])
        self.assertIn("-20", fx["text"])
        self.assertTrue(result["quiet"])

    def test_sister_card_repricing_is_news(self):
        today = state(channel={"watchlist": [{"model": "RTX PRO 6000 D 84G", "min_ask": 67000, "quote_date": "2026-10-30", "condition": "正常供应"}]})
        result = daily_digest(today, baseline())
        item = next(i for i in result["items"] if i["tag"] == "相关型号")
        self.assertIn("68,500→67,000", item["text"])
        self.assertFalse(result["quiet"])

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
        self.assertFalse([i for i in result["items"] if i["tag"] in ("情报", "线索", "新闻", "相关型号")])


if __name__ == "__main__":
    unittest.main()
