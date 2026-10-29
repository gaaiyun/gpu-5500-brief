import sys
import unittest
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
import sweep

TODAY=date(2026,10,27)
EVENTS={"reuters":{"name":"路透社","date":"2026-10-20","text":"中国客户总订单超过600万张，合作方或只获配5%-10%","url":"https://example.com/reuters"},
        "leiphone":{"name":"雷峰网","date":"2026-10-20","text":"大厂采购报价约8.5万元","url":"https://example.com/leiphone"}}
ARTICLE="据路透社报道，三家中国互联网大厂合计订购超过300万块英伟达RTX PRO 5500，客户总订单超过600万张。渠道报价约8.7万元。"


def candidate(**kw):
    base={"url":"https://www.ithome.com/0/900/001.htm","title":"RTX PRO 5500 渠道报价8.7万元","text":ARTICLE,"published_at":"2026-10-26",
          "publisher":"IT之家","source_type":"行业媒体","found_via":"IT之家"}
    base.update(kw);return base


def draft(**kw):
    base={"source_id":"s1","relevant":True,"duplicate_of":"","title":"渠道报价约8.7万元","summary":"IT之家称渠道报价约8.7万元。",
          "impact":"高于8.5万元的大厂采购价。","watch":"核实交期","claims":[]}
    base.update(kw);return base


class DiscoveryTests(unittest.TestCase):
    def test_classify_by_domain(self):
        self.assertEqual(sweep.classify("https://www.reuters.com/x")[1],"主流媒体")
        self.assertEqual(sweep.classify("https://mp.weixin.qq.com/s/x")[1],"公众号")
        self.assertEqual(sweep.classify("https://news.qq.com/rain/a/x")[1],"公众号")
        self.assertIsNone(sweep.classify("https://unknown-blog.example/x"))

    def test_dates_in_beijing_time(self):
        self.assertEqual(sweep.to_date("Mon, 26 Oct 2026 17:00:00 GMT"),date(2026,10,27))
        self.assertEqual(sweep.to_date("2026-10-27 15:42:34"),date(2026,10,27))
        self.assertEqual(sweep.to_date("20261026T170000Z"),date(2026,10,27))
        self.assertIsNone(sweep.to_date("yesterday"))

    def test_rss_keeps_only_the_product_and_reads_gbk(self):
        xml=('<?xml version="1.0" encoding="gb2312"?><rss><channel>'
             '<item><title>英伟达RTX PRO 5500报价曝光</title><link>http://news.mydrivers.com/1/1.htm</link><pubDate>2026-10-27 09:00:00</pubDate></item>'
             '<item><title>锐龙5 5500F实测</title><link>http://news.mydrivers.com/1/2.htm</link><pubDate>2026-10-27 09:00:00</pubDate></item>'
             '</channel></rss>').encode("gb2312")
        rows=sweep.parse_rss(xml,"快科技")
        self.assertEqual([r["title"] for r in rows],["英伟达RTX PRO 5500报价曝光"])
        self.assertEqual(rows[0]["published_at"],date(2026,10,27))

    def test_sogou_rows_become_title_searches(self):
        html=('<ul class="news-list"><li><div class="txt-box"><h3><a href="/link?url=x">喊出300万张订单,英伟达<em><!--red_beg-->RTX<!--red_end--></em> '
              '<em>PRO</em> <em>5500</em>为何遭到提前订购</a></h3><p class="txt-info">渠道报价</p><div class="s-p"><span class="all-time-y2">某科技</span>'
              '<span class="s2"><script>document.write(timeConvert(\'1792488868\'))</script></span></div></div></li></ul>')
        row=sweep.sogou_page(html)[0]
        self.assertEqual(row["title"],"喊出300万张订单,英伟达RTX PRO 5500为何遭到提前订购")
        self.assertTrue(row["url"].startswith("https://weixin.sogou.com/weixin?type=2&query="))
        self.assertNotIn("/link",row["url"])
        self.assertEqual(row["publisher"],"某科技")
        self.assertTrue(sweep.sogou_blocked("<html>antispider</html>","https://weixin.sogou.com/antispider/?from=x"))


class DraftCheckTests(unittest.TestCase):
    def test_checked_draft_becomes_grade_b(self):
        item=sweep.build_item(draft(),candidate(),EVENTS,TODAY)
        self.assertEqual(item["grade"],"B")
        self.assertTrue(item["id"].startswith("ithome-20261026-"))

    def test_card_price_kept_only_when_printed_in_article(self):
        self.assertEqual(sweep.build_item(draft(price_cny=87000),candidate(),EVENTS,TODAY)["price_cny"],[87000,87000])
        self.assertNotIn("price_cny",sweep.build_item(draft(price_cny=92000),candidate(),EVENTS,TODAY))
        self.assertNotIn("price_cny",sweep.build_item(draft(price_cny=3000000),candidate(),EVENTS,TODAY))

    def test_number_missing_from_article_rejected(self):
        with self.assertRaises(ValueError):sweep.build_item(draft(summary="渠道报价约9.2万元。"),candidate(),EVENTS,TODAY)
        with self.assertRaises(ValueError):sweep.build_item(draft(impact="可能涨到12万元。"),candidate(),EVENTS,TODAY)

    def test_self_media_needs_checked_claims(self):
        post=candidate(url="https://news.qq.com/rain/a/1",source_type="公众号",publisher="腾讯新闻")
        with self.assertRaises(ValueError):sweep.build_item(draft(),post,EVENTS,TODAY)
        claims=[{"text":"客户总订单超过600万张","status":"有出处","ref":"reuters"},
                {"text":"大厂订购超过300万块","status":"有出处","ref":"reuters"},
                {"text":"渠道报价约8.7万元","status":"有出处","ref":"made-up"}]
        item=sweep.build_item(draft(claims=claims),post,EVENTS,TODAY)
        self.assertEqual(item["grade"],"C")
        self.assertEqual([c["status"] for c in item["claims"]],["有出处","无出处","无出处"])
        self.assertEqual(item["claims"][0]["ref"],"https://example.com/reuters")

    def test_claims_matching_a_verified_event_are_sourced(self):
        post=candidate(url="https://news.qq.com/rain/a/1",source_type="公众号",publisher="腾讯新闻",
                       text=ARTICLE+"最终可能只能满足5%至10%。大厂采购报价约8.5万元。")
        claims=[{"text":"最终可能只能满足5%至10%","status":"无出处","ref":""},
                {"text":"大厂采购报价约8.5万元","status":"推算","ref":""},
                {"text":"路透坐实600万张订单","status":"与出处不符","ref":"reuters"}]
        item=sweep.build_item(draft(claims=claims),post,EVENTS,TODAY)
        self.assertEqual([(c["status"],c["ref"]) for c in item["claims"]],
                         [("有出处","https://example.com/reuters"),("有出处","https://example.com/leiphone"),
                          ("与出处不符","https://example.com/reuters")])
        # A lone small figure is too weak to tie a claim to an event.
        self.assertIsNone(sweep.matching_event("9月底上报",EVENTS))

    def test_internal_ids_become_source_names(self):
        item=sweep.build_item(draft(impact="与已收录事件 leiphone 的8.5万元一致"),candidate(),EVENTS,TODAY)
        self.assertEqual(item["impact"],"与雷峰网的8.5万元一致")


class SweepTests(unittest.TestCase):
    def setUp(self):
        self.saved={k:getattr(sweep,k) for k in ("gdelt","google_news","sogou","inbox","fetch","read_article","ask_model")}
        sweep.gdelt=lambda:[{"url":"https://www.ithome.com/0/900/001.htm","title":"RTX PRO 5500 渠道报价","published_at":date(2026,10,26),
                             "snippet":"","body":"","found_via":"GDELT"},
                            {"url":"https://www.ithome.com/0/900/002.htm","title":"RTX PRO 5500 转述路透","published_at":date(2026,10,26),
                             "snippet":"","body":"","found_via":"GDELT"},
                            {"url":"https://blog.example/a","title":"RTX PRO 5500 price leak","published_at":date(2026,10,26),
                             "snippet":"","body":"","found_via":"GDELT"},
                            {"url":"https://www.ithome.com/0/800/000.htm","title":"旧闻","published_at":date(2026,10,1),
                             "snippet":"","body":"","found_via":"GDELT"}]
        sweep.google_news=lambda:[];sweep.inbox=lambda:[]
        sweep.sogou=lambda notes:[{"title":"RTX Pro5500 开放预定","publisher":"某公司","source_type":"公众号","published_at":date(2026,10,27),
                                   "snippet":"","url":"https://weixin.sogou.com/weixin?type=2&query=x","found_via":"搜狗微信"}]
        sweep.fetch=lambda url:(_ for _ in ()).throw(RuntimeError("offline"))
        sweep.read_article=lambda url:(ARTICLE,"",date(2026,10,26))
        sweep.ask_model=lambda batch,events,endpoint,token:([draft(source_id="s1"),draft(source_id="s2",duplicate_of="old")],"test-model")

    def tearDown(self):
        for k,v in self.saved.items():setattr(sweep,k,v)

    def test_sweep_adds_items_corroborates_and_keeps_leads(self):
        old={"id":"old","title":"旧条目","published_at":"2026-10-20","publisher":"雷峰网","source_type":"行业媒体","url":"https://example.com/old",
             "grade":"B","summary":"大厂采购报价约8.5万元","impact":"影响","watch":"跟进"}
        result=sweep.sweep({"items":[old],"leads":[]},{"sources":[]},TODAY,"https://ai.example","t")
        self.assertEqual(len(result["items"]),1)
        self.assertEqual(result["corroborated"],{"old":["https://www.ithome.com/0/900/002.htm"]})
        self.assertEqual(sorted(x["found_via"] for x in result["leads"]),["GDELT","搜狗微信"])
        self.assertEqual(result["candidates"],2)

    def test_model_outage_turns_articles_into_leads(self):
        sweep.ask_model=lambda *a:(_ for _ in ()).throw(RuntimeError("502"))
        result=sweep.sweep({"items":[],"leads":[]},{"sources":[]},TODAY,"https://ai.example","t")
        self.assertEqual(result["items"],[])
        self.assertIn("https://www.ithome.com/0/900/001.htm",[x["url"] for x in result["leads"]])
        self.assertTrue(any("模型调用失败" in n for n in result["notes"]))


class MergeTests(unittest.TestCase):
    def item(self,**kw):
        base={"id":"a","title":"标题","published_at":"2026-10-20","publisher":"雷峰网","source_type":"行业媒体","url":"https://example.com/a",
              "grade":"B","summary":"事实","impact":"影响","watch":"跟进","checked_at":"2026-10-25"}
        base.update(kw);return base

    def test_newer_cloud_copy_wins_and_invalid_items_drop(self):
        merged=sweep.merge_feeds({"items":[self.item()]},{"items":[self.item(summary="云端更新",checked_at="2026-10-27"),self.item(id="bad",url="http://x")]})
        items,_=sweep.finalize(merged["items"],[],TODAY)
        self.assertEqual([i["summary"] for i in items],["云端更新"])

    def test_leads_expire_and_dated_repost_replaces_undated(self):
        lead=lambda title,pub,seen="2026-10-27":{"title":title,"publisher":"号","source_type":"公众号","url":"https://weixin.sogou.com/weixin?q="+title,
                                                 "published_at":pub,"found_via":"搜狗微信","snippet":"","seen_at":seen}
        rows=[lead("RTX PRO 5500单卡售价1.14万美元 图一 ,是英伟达新卡","2026-10-21"),lead("RTX PRO 5500单卡售价1.14万美元,是英伟达新卡",""),
              lead("过期线索","2026-10-01"),lead("没有日期的老线索","","2026-10-01")]
        _,leads=sweep.finalize([],rows,TODAY)
        self.assertEqual([x["published_at"] for x in leads],["2026-10-21"])


if __name__=="__main__":unittest.main()
