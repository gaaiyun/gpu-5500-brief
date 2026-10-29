import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import prices
from market import parse_channel, channel_template, daily_brief

CHINAMONEY = {"data": {"lastDate": "2026-10-29 9:15"}, "records": [
    {"vrtEName": "USD/CNY", "price": "6.7147"}, {"vrtEName": "EUR/CNY", "price": "7.4570"},
    {"vrtEName": "100JPY/CNY", "price": "4.2453"}, {"vrtEName": "GBP/CNY", "price": "8.9101"}]}
FRANKFURTER = {"amount": 1.0, "base": "USD", "date": "2026-10-28", "rates": {"CNY": 6.6664, "EUR": 0.89823, "GBP": 0.75258}}


def evidence():
    return {
        "sources": [{"id": "smm", "url": "https://news.smm.cn/news/104154895"},
                    {"id": "reuters", "url": "https://www.bnnbloomberg.ca/x"},
                    {"id": "trendforce", "url": "https://www.trendforce.com/x"}],
        "prices": [
            {"id": "smm_presale", "source_id": "smm", "observed_at": "2026-10-13", "value_cny": 95000, "board": "SMM 供应商预售"},
            {"id": "smm_estimate", "source_id": "smm", "observed_at": "2026-10-13", "low_cny": 90000, "high_cny": 95000},
            {"id": "theinformation_price", "source_id": "trendforce", "observed_at": "2026-10-21", "low_cny": 85000, "high_cny": 90000, "board": "The Information 售价"},
            {"id": "reuters_usd", "source_id": "reuters", "observed_at": "2026-10-20", "value_usd": 11400, "board": "路透订单价"}],
        "listings": [{"id": "fr_materiel", "label": "法国零售 PNY", "url": "https://www.comparateur-gamer.fr/prix/x",
                      "currency": "EUR", "vat_rate": 0.2, "price": 16469.95, "price_seen_at": "2026-09-30", "note": "比价站"}],
        "forecast": {"anchor_cny": 95000}}


def fx(usd=6.7147, day="2026-10-29"):
    return {"status": "ok", "provider": "chinamoney", "label": "人民币汇率中间价", "date": day,
            "rates": {"USD": usd, "EUR": 7.4570, "GBP": 8.9101}}


def listing(price=16469.95, since="2026-09-30"):
    return [{"id": "fr_materiel", "status": "ok", "price": price, "price_since": since}]


class FxTests(unittest.TestCase):
    def test_central_parity_parsed(self):
        rates, day = prices.parse_fx("chinamoney", CHINAMONEY)
        self.assertEqual(day, "2026-10-29")
        self.assertEqual(rates, {"USD": 6.7147, "EUR": 7.4570, "GBP": 8.9101})

    def test_usd_base_converted_to_cny_per_unit(self):
        rates, day = prices.parse_fx("frankfurter", FRANKFURTER)
        self.assertEqual(day, "2026-10-28")
        self.assertAlmostEqual(rates["EUR"], 6.6664 / 0.89823, places=4)
        self.assertAlmostEqual(rates["GBP"], 6.6664 / 0.75258, places=4)

    def test_absurd_rate_rejected(self):
        bad = {**CHINAMONEY, "records": [dict(r, price="67.147") if r["vrtEName"] == "USD/CNY" else r for r in CHINAMONEY["records"]]}
        with self.assertRaises(ValueError):
            prices.parse_fx("chinamoney", bad)

    def test_falls_back_to_next_provider(self):
        def get_json(url):
            if "chinamoney" in url:
                raise RuntimeError("blocked")
            return FRANKFURTER
        result = prices.fetch_fx(get_json, None, "2026-10-29T00:35:00+08:00")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider"], "frankfurter")
        self.assertIn("chinamoney", result["error"])

    def test_total_outage_keeps_last_rates(self):
        def get_json(url):
            raise RuntimeError("offline")
        result = prices.fetch_fx(get_json, fx(), "2026-10-30T00:35:00+08:00")
        self.assertEqual(result["status"], "carried")
        self.assertEqual(result["rates"]["USD"], 6.7147)
        self.assertEqual(result["date"], "2026-10-29")


class ListingTests(unittest.TestCase):
    def page(self, block):
        return f'<html><head><script type="application/ld+json">{block}</script></head><body>£7.95</body></html>'

    def test_aggregate_offer_low_price(self):
        html = self.page('{"@type":"Product","offers":{"@type":"AggregateOffer","lowPrice":"16469.95","priceCurrency":"EUR"}}')
        self.assertEqual(prices.parse_listing(html, "EUR"), 16469.95)

    def test_offer_inside_graph(self):
        html = self.page('{"@graph":[{"@type":"Product","offers":[{"@type":"Offer","price":"12810","priceCurrency":"GBP"}]}]}')
        self.assertEqual(prices.parse_listing(html, "GBP"), 12810)

    def test_other_currency_rejected(self):
        html = self.page('{"@type":"Product","offers":{"@type":"Offer","price":"12810","priceCurrency":"USD"}}')
        with self.assertRaises(ValueError):
            prices.parse_listing(html, "GBP")

    def test_unchanged_price_keeps_its_date(self):
        html = self.page('{"@type":"Product","offers":{"@type":"AggregateOffer","lowPrice":"16469.95","priceCurrency":"EUR"}}')
        seed = evidence()["listings"][0]
        result = prices.check_listing(seed, listing()[0], lambda _: html, "2026-10-30T00:35:00+08:00")
        self.assertEqual(result["price_since"], "2026-09-30")

    def test_new_price_dated_today(self):
        html = self.page('{"@type":"Product","offers":{"@type":"AggregateOffer","lowPrice":"15999.00","priceCurrency":"EUR"}}')
        seed = evidence()["listings"][0]
        result = prices.check_listing(seed, listing()[0], lambda _: html, "2026-10-30T00:35:00+08:00")
        self.assertEqual((result["price"], result["price_since"], result["previous_price"]), (15999.0, "2026-10-30", 16469.95))

    def test_implausible_price_keeps_previous(self):
        html = self.page('{"@type":"Product","offers":{"@type":"Offer","price":"129.99","priceCurrency":"EUR"}}')
        seed = evidence()["listings"][0]
        result = prices.check_listing(seed, listing()[0], lambda _: html, "2026-10-30T00:35:00+08:00")
        self.assertEqual((result["status"], result["price"]), ("failed", 16469.95))


class BoardTests(unittest.TestCase):
    def board(self, previous=None, rates=None, rows=None, feed=None):
        return prices.build_board(evidence(), None, rates or fx(), rows or listing(), feed or [], date(2026, 10, 29), previous)

    def test_dollar_order_price_converted_with_and_without_vat(self):
        row = next(r for r in self.board()["rows"] if r["id"] == "reuters_usd")
        self.assertEqual((row["cny"], row["cny_vat"]), (76548, 86499))
        self.assertTrue(row["converted"])

    def test_eu_retail_drops_local_vat_before_conversion(self):
        row = next(r for r in self.board()["rows"] if r["id"] == "fr_materiel")
        self.assertEqual(row["cny"], round(16469.95 / 1.2 * 7.4570))

    def test_domestic_range_ignores_converted_prices(self):
        domestic = self.board()["domestic"]
        self.assertEqual((domestic["low"], domestic["high"], domestic["count"]), (85000, 95000, 2))
        self.assertEqual(domestic["latest_date"], "2026-10-21")

    def test_rate_move_is_not_a_new_quote(self):
        board = self.board(previous=self.board(rates=fx(6.7165, "2026-10-28")))
        kinds = {c["id"]: c["kind"] for c in board["changes"]}
        self.assertEqual(kinds["reuters_usd"], "汇率")
        self.assertTrue(board["summary"].startswith("今日无新报价"))
        self.assertIn("2026-10-21", board["summary"])

    def test_new_listing_price_is_reported(self):
        board = self.board(previous=self.board(), rows=listing(15999.0, "2026-10-29"))
        change = next(c for c in board["changes"] if c["id"] == "fr_materiel")
        self.assertEqual(change["kind"], "新报价")
        self.assertIn("新报价", board["summary"])

    def test_only_checked_feed_prices_enter(self):
        feed = [{"id": "a", "grade": "B", "price_cny": [92000, 92000], "published_at": "2026-10-28", "publisher": "雷峰网",
                 "url": "https://www.leiphone.com/a", "title": "渠道报价", "age_days": 1},
                {"id": "b", "grade": "C", "price_cny": [70000, 70000], "published_at": "2026-10-28", "publisher": "某公众号",
                 "url": "https://mp.weixin.qq.com/s/b", "title": "传闻", "age_days": 1}]
        ids = [r["id"] for r in self.board(feed=feed)["rows"]]
        self.assertIn("feed:a", ids)
        self.assertNotIn("feed:b", ids)

    def test_no_rates_leaves_foreign_prices_unconverted(self):
        board = self.board(rates={"status": "failed", "rates": None, "error": "offline"})
        row = next(r for r in board["rows"] if r["id"] == "reuters_usd")
        self.assertIsNone(row["cny"])
        self.assertIn("汇率", board["summary"])


def channel_payload(start_day):
    rows = []
    for i in range(14):
        mid = 90000 + (i * 37) % 300
        rows.append({"dateStr": date(2026, 10, start_day + i).isoformat(), "avgPrice": mid, "avgSupplyPrice": round(mid * 1.015),
                     "avgDemandPrice": round(mid * .985), "high": 93000, "low": 85000, "volume": (5 + i * 32) % 45 + 5})
    return {"success": True, "data": [{"name": "NVIDIA RTX PRO 5500 84GB", "model": "RTX PRO 5500", "currentMinSupply": "86000.00",
                                       "currentMaxDemand": "88728.00", "spec_attributes": {"最新报价日期": "2026-09-22", "期货交期": "3个月（约90天）", "货况说明": "3个月期货 / 预订"},
                                       "chartData": rows}]}


class TemplateTests(unittest.TestCase):
    def test_redated_series_detected(self):
        yesterday = parse_channel(channel_payload(12), "2026-10-25T20:00:00+08:00")
        today = parse_channel(channel_payload(13), "2026-10-26T20:00:00+08:00")
        self.assertTrue(channel_template(today, yesterday)["redated"])

    def test_changed_series_not_redated(self):
        yesterday = parse_channel(channel_payload(12), "2026-10-25T20:00:00+08:00")
        moved = channel_payload(13)
        moved["data"][0]["chartData"][-1]["avgPrice"] = 91000
        today = parse_channel(moved, "2026-10-26T20:00:00+08:00")
        self.assertFalse(channel_template(today, yesterday)["redated"])

    def test_brief_drops_fake_daily_change(self):
        yesterday = parse_channel(channel_payload(12), "2026-10-25T20:00:00+08:00")
        today = parse_channel(channel_payload(13), "2026-10-26T20:00:00+08:00")
        today["template"] = channel_template(today, yesterday)
        board = prices.build_board(evidence(), today, fx(), listing(), [], date(2026, 10, 26), None)
        brief = daily_brief(evidence(), today, yesterday, board)
        text = " ".join(x["text"] for x in brief["items"])
        self.assertNotIn("较上日", text)
        self.assertIn("不计入涨跌", text)
        self.assertEqual([c["field"] for c in brief["channel_changes"]], [])


if __name__ == "__main__":
    unittest.main()
