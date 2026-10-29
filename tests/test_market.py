import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from market import parse_channel, daily_brief, channel_template


def payload():
    rows=[]
    for i in range(14):
        mid=90000+i*10
        rows.append({"dateStr":f"2026-10-{12+i}","avgPrice":mid,"avgSupplyPrice":round(mid*1.015),"avgDemandPrice":round(mid*.985),"high":93000,"low":85000,"volume":(5+i*32)%45+5})
    return {"success":True,"data":[{"name":"NVIDIA RTX PRO 5500 84GB","model":"RTX PRO 5500","unit":"张","currentMinSupply":"86000.00","currentMaxDemand":"88728.00","spec_attributes":{"最新报价日期":"2026-09-22","期货交期":"3个月（约90天）","货况说明":"3个月期货 / 预订"},"chartData":rows}]}


class MarketTests(unittest.TestCase):
    def test_exact_model_not_monitor(self):
        p=payload();p["data"].append({"name":"飞利浦 27E2N5500 显示器"})
        result=parse_channel(p,"2026-10-25T20:00:00+08:00")
        self.assertEqual(result["model"],"RTX PRO 5500")

    def test_independence_not_assumed(self):
        result=parse_channel(payload(),"2026-10-25T20:00:00+08:00")
        self.assertFalse(result["independent_market_samples"])
        self.assertEqual(result["stats"]["fixed_offset_points"],14)

    def test_original_quote_date_retained(self):
        result=parse_channel(payload(),"2026-10-25T20:00:00+08:00")
        self.assertEqual(result["quote_date"],"2026-09-22")
        self.assertEqual(result["latest"]["date"],"2026-10-25")

    def test_future_rejected(self):
        with self.assertRaises(ValueError):parse_channel(payload(),"2026-10-24T20:00:00+08:00")

    def test_nan_rejected(self):
        p=payload();p["data"][0]["chartData"][0]["avgPrice"]=float('nan')
        with self.assertRaises(ValueError):parse_channel(p,"2026-10-25T20:00:00+08:00")

    def test_duplicate_dates_rejected(self):
        p=payload();p["data"][0]["chartData"][1]["dateStr"]="2026-10-12"
        with self.assertRaises(ValueError):parse_channel(p,"2026-10-25T20:00:00+08:00")

    def test_daily_change_is_separate_from_verified_price(self):
        market=parse_channel(payload(),"2026-10-25T20:00:00+08:00")
        previous={"latest":dict(market["latest"],ask=90000)}
        result=daily_brief({"forecast":{"scenarios":[{"id":"base","low":85000,"high":90000}]}},market,previous)
        self.assertEqual(result["channel_changes"][0]["field"],"ask")
        self.assertNotIn("verified_price",result)

    def test_formula_curve_reports_only_real_quote_changes(self):
        market=parse_channel(payload(),"2026-10-25T20:00:00+08:00")
        market["template"]=channel_template(market,None)
        self.assertTrue(market["template"]["formula"])
        previous=dict(market,min_ask=88000,latest=dict(market["latest"],ask=90000))
        result=daily_brief({"forecast":{"scenarios":[{"id":"base","low":85000,"high":90000}]}},market,previous)
        self.assertEqual([c["field"] for c in result["channel_changes"]],["min_ask"])

    def test_failure_keeps_original_collection_time(self):
        import update
        old=update.fetch
        update.fetch=lambda _: (_ for _ in ()).throw(RuntimeError('offline'))
        try:
            market=parse_channel(payload(),"2026-10-25T20:00:00+08:00")
            result=update.check_source({"id":"qudao","url":"https://qudao.co/api/trends?timeframe=daily","published_at":None},{"market":market,"last_success_at":"2026-10-25T20:00:00+08:00"},"2026-10-26T00:35:00+08:00")
            self.assertEqual(result["status"],"failed")
            self.assertEqual(result["market"]["collected_at"],"2026-10-25T20:00:00+08:00")
        finally:update.fetch=old


if __name__ == '__main__':unittest.main()
