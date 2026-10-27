import json
import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from feed import load_feed

TODAY=date(2026,10,27)


def item(**kw):
    base={"id":"x","title":"标题","published_at":"2026-10-20","publisher":"雷峰网","source_type":"行业媒体",
          "url":"https://example.com/a","grade":"B","summary":"事实","impact":"影响","watch":"跟进"}
    base.update(kw);return base


class FeedTests(unittest.TestCase):
    def test_committed_feed_is_valid(self):
        # The daily sweep keeps adding dated items: judge them by today's Beijing date, and never by how many are fresh.
        from feed import load_leads
        today=datetime.now(timezone(timedelta(hours=8))).date()
        payload=json.loads((ROOT/"data/feed.json").read_text(encoding="utf-8"))
        self.assertEqual(load_feed(payload,today)[1],[])
        self.assertEqual(load_leads(payload,today)[1],[])

    def test_bad_items_dropped_not_fatal(self):
        items,rejected=load_feed({"items":[item(),item(id="y",url="http://plain"),item(id="z",published_at="2026-11-30"),
                                           item(id="w",grade="A"),item(id="v",summary="<script>x</script>")]},TODAY)
        self.assertEqual([x["id"] for x in items],["x"])
        self.assertEqual(len(rejected),4)

    def test_grade_a_needs_corroboration(self):
        items,_=load_feed({"items":[item(grade="A",corroboration=["https://example.com/b"])]},TODAY)
        self.assertEqual(items[0]["grade_label"],"多方印证")

    def test_stale_and_duplicate_urls_skipped(self):
        items,_=load_feed({"items":[item(),item(id="dup"),item(id="old",url="https://example.com/o",published_at="2026-08-01")]},TODAY)
        self.assertEqual(len(items),1)

    def test_quick_posts_must_be_checked(self):
        post=dict(item(id="p",url="https://mp.weixin.qq.com/s/x",source_type="公众号",grade="C"))
        _,rejected=load_feed({"items":[post]},TODAY)
        self.assertEqual(len(rejected),1)
        _,rejected=load_feed({"items":[dict(post,grade="B",claims=[{"text":"a","status":"推算"}])]},TODAY)
        self.assertEqual(len(rejected),1)
        claims=[{"text":"路透称订单超300万张","status":"有出处","ref":"https://example.com/r"},
                {"text":"客户只拿到15万到30万张","status":"推算"},
                {"text":"路透坐实了此事","status":"与出处不符","ref":"https://example.com/r"}]
        items,rejected=load_feed({"items":[dict(post,claims=claims)]},TODAY)
        self.assertEqual(rejected,[])
        self.assertEqual(items[0]["tier"],"快讯")
        from feed import claim_tally
        self.assertEqual(claim_tally(items[0]),"有出处 1 · 推算 1 · 与出处不符 1")

    def test_sourced_claim_needs_link(self):
        post=item(id="p",source_type="社媒",grade="C",claims=[{"text":"a","status":"有出处"}])
        self.assertEqual(len(load_feed({"items":[post]},TODAY)[1]),1)

    def test_leads_are_links_only(self):
        from feed import load_leads
        lead={"title":"2万张RTX PRO 5500合同披露","publisher":"GPU算力-聪哥","source_type":"公众号",
              "url":"https://weixin.sogou.com/weixin?type=2&query=x","found_via":"搜狗微信","snippet":"合同条款"}
        leads,bad=load_leads({"leads":[lead,dict(lead),dict(lead,title="b",url="http://x"),dict(lead,title="c",published_at="2027-01-01")]},TODAY)
        self.assertEqual(len(leads),1)
        self.assertEqual(len(bad),2)
        self.assertNotIn("grade",leads[0])

    def test_garbage_payload(self):
        self.assertEqual(load_feed(None,TODAY),([],[]))
        self.assertEqual(load_feed({"items":"nope"},TODAY)[0],[])


if __name__=="__main__":unittest.main()
