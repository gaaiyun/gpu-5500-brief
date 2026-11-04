import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import signals

TODAY = date(2026, 11, 5)


class PriceMentionTests(unittest.TestCase):
    def test_range_and_single_price(self):
        self.assertEqual(signals.find_prices("RTX PRO 5500 国内直单报价约8万—9.5万元人民币"), [(80000, 95000)])
        self.assertEqual(signals.find_prices("RTX PRO 5500 现货价已到 9.2 万元"), [(92000, 92000)])
        self.assertEqual(signals.find_prices("RTX PRO 5500 单卡 92,000 元"), [(92000, 92000)])

    def test_quantities_dollars_and_orders_are_not_prices(self):
        for text in ("RTX PRO 5500 三家订购 8万张", "RTX PRO 5500 单价 1.14万美元", "RTX PRO 5500 超过 300万张订单", "RTX PRO 5500 总额 350亿美元"):
            self.assertEqual(signals.find_prices(text), [], text)

    def test_price_attached_to_another_card_does_not_count(self):
        self.assertEqual(signals.find_prices("RTX PRO 5500 对比 RTX 5090 现货 7.8万元"), [])

    def test_mentions_merge_by_publisher_and_expire(self):
        rows = [{"title": "RTX PRO 5500 报价约8万—9.5万元", "publisher": "算力圈视界", "published_at": "2026-11-03", "url": "https://x/1", "found_via": "搜狗微信"},
                {"title": "RTX PRO 5500 报价约8万—9.5万元", "publisher": "算力圈视界", "published_at": "2026-11-04", "url": "https://x/2", "found_via": "搜狗微信"},
                {"title": "RTX PRO 5500 报价约9万元", "publisher": "无日期", "published_at": "", "url": "https://x/3"}]
        old = [{"date": "2026-09-01", "publisher": "旧", "low": 90000, "high": 90000, "url": "", "found_via": ""}]
        found = signals.collect_mentions(rows, old, TODAY)
        self.assertEqual([(m["publisher"], m["date"]) for m in found], [("算力圈视界", "2026-11-03")])
        self.assertEqual(signals.mention_price(found[0]), "8万-9.5万元")


class ChannelTests(unittest.TestCase):
    def test_distributor_posts_are_channel_claims_but_media_are_not(self):
        leads = [{"title": "广州丽泰 2027 年 Q1 将到 2000 片 RTX PRO 5500", "publisher": "广州丽泰", "source_type": "公众号", "url": "https://x/1", "published_at": "2026-10-31"},
                 {"title": "RTX Pro5500 开放预定，显卡/整机均可接单交付", "publisher": "广州三欣", "source_type": "公众号", "url": "https://x/2", "published_at": "2026-10-27"},
                 {"title": "深度拆解 RTX PRO 5500", "publisher": "苏哥随笔", "source_type": "公众号", "url": "https://x/3", "published_at": "2026-10-29"},
                 {"title": "英伟达交付受限", "publisher": "路透", "source_type": "主流媒体", "url": "https://x/4", "published_at": "2026-10-29"}]
        self.assertEqual([r["publisher"] for r in signals.channel_signals(leads)], ["广州丽泰", "广州三欣"])


class HeatTests(unittest.TestCase):
    def test_counts_unique_titles_by_kind_and_never_shrinks(self):
        rows = [{"title": "甲", "published_at": date(2026, 11, 4), "source_type": "公众号"},
                {"title": "甲 ", "published_at": "2026-11-04", "source_type": "公众号"},
                {"title": "乙", "published_at": "2026-11-04"}, {"title": "旧", "published_at": "2026-10-01"}]
        heat = signals.update_heat({"2026-11-04": {"media": 5, "wechat": 0}}, rows, TODAY)
        self.assertEqual(heat["2026-11-04"], {"media": 5, "wechat": 1})
        self.assertNotIn("2026-10-01", heat)

    def test_text_compares_yesterday_with_the_week_before(self):
        heat = {f"2026-10-{d}": {"media": 1, "wechat": 0} for d in range(28, 32)}
        heat.update({"2026-11-01": {"media": 1}, "2026-11-02": {"media": 1}, "2026-11-03": {"media": 1}, "2026-11-04": {"media": 6, "wechat": 2}})
        text = signals.heat_text(heat, TODAY)
        self.assertIn("昨日检索到 8 篇", text)
        self.assertIn("日均 1.0 篇", text)
        self.assertIn("明显升温", text)
        self.assertIsNone(signals.heat_text({}, TODAY))


class CalendarTests(unittest.TestCase):
    def test_next_events_count_down_and_past_ones_drop(self):
        calendar = [{"date": "2026-11-18", "label": "NVIDIA 财报", "why": "看中国口径"}, {"date": "2026-11-01", "label": "过去的", "why": "x"},
                    {"date": "2026-11-05", "label": "今天的", "why": "y"}]
        text = signals.calendar_text(calendar, TODAY)
        self.assertIn("11-05 今天的（今天，y）", text)
        self.assertIn("11-18 NVIDIA 财报（还有 13 天，看中国口径）", text)
        self.assertNotIn("过去的", text)
        self.assertIsNone(signals.calendar_text([], TODAY))


class TakeTests(unittest.TestCase):
    def test_note_needs_to_be_fresh_short_and_use_known_numbers(self):
        ok = {"date": "2026-11-05", "text": "基准仍在8.5万元附近。"}
        allowed = {85000.0}
        self.assertEqual(signals.clean_take(ok, TODAY, allowed)["text"], ok["text"])
        self.assertIsNone(signals.clean_take(dict(ok, date="2026-11-01"), TODAY, allowed))
        self.assertIsNone(signals.clean_take(dict(ok, text="涨到12万元"), TODAY, allowed))
        self.assertIsNone(signals.clean_take(dict(ok, text="长" * 200), TODAY, allowed))
        self.assertIsNone(signals.clean_take(None, TODAY, allowed))

    def test_dates_and_countdowns_are_not_market_claims(self):
        take = {"date": "2026-11-05", "text": "距11月18日财报还有13天，2027年2月第二批到货前别指望降价，二季度再看，11-30前盯样品。"}
        self.assertEqual(signals.clean_take(take, TODAY, set())["text"], take["text"])


class BriefTests(unittest.TestCase):
    def test_note_leads_and_events_follow_supply(self):
        state = {"daily_brief": {"items": [{"title": "大陆报价", "text": "a"}, {"title": "供应与交付", "text": "b"}, {"title": "今日变化", "text": "c"}]},
                 "feed": {"take": {"date": "2026-11-05", "text": "今天没有新报价。"}, "items": [],
                          "heat": {"2026-11-04": {"media": 2, "wechat": 1}}}}
        evidence = {"calendar": [{"date": "2026-11-18", "label": "NVIDIA 财报", "why": "看中国口径"}]}
        signals.extend_brief(state, evidence, TODAY)
        self.assertEqual([b["title"] for b in state["daily_brief"]["items"]], ["今日点评", "大陆报价", "供应与交付", "接下来", "讨论热度", "今日变化"])


if __name__ == "__main__":
    unittest.main()
