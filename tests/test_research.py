import copy
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from research import report_markdown
from intelligence import fact_briefs


def load():
    evidence=json.loads((ROOT/"data/evidence.json").read_text(encoding="utf-8"))
    state=json.loads((ROOT/"data/state.json").read_text(encoding="utf-8"))
    return evidence,state


def with_board(evidence,state,usd=6.7147):
    """The committed state may predate the price board; rebuild one so both layouts stay tested."""
    from datetime import date
    from market import channel_template,daily_brief
    from prices import build_board
    state=copy.deepcopy(state)
    fx={"status":"ok","provider":"chinamoney","label":"人民币汇率中间价","date":state["date"],"rates":{"USD":usd,"EUR":7.457,"GBP":8.9101}}
    state["channel"]["template"]=channel_template(state["channel"],None)
    state["price_board"]=build_board(evidence,state["channel"],fx,[],[],date.fromisoformat(state["date"]),None)
    state["daily_brief"]=daily_brief(evidence,state["channel"],None,state["price_board"])
    from digest import daily_digest
    from prices import build_series
    history={state["date"]:fx["rates"],"2026-10-20":dict(fx["rates"],USD=6.678)}
    state["price_series"]=build_series(evidence,state["channel"],history,[],[],date.fromisoformat(state["date"]))
    state["digest"]=daily_digest(state,{})
    return state


class ResearchTests(unittest.TestCase):
    def test_low_quote_terms_follow_channel_data(self):
        evidence,state=load()
        state=copy.deepcopy(state);c=state["channel"]
        c.update(min_ask=87500,quote_date="2026-10-20",delivery="2个月（约60天）",condition="2个月期货 / 预订")
        c["stats"]["fixed_offset_points"]=9
        text=report_markdown(evidence,state)
        self.assertIn("87,500",text)
        self.assertIn("2026-10-20",text)
        self.assertIn("约60天",text)
        self.assertIn("9/14",text)
        self.assertNotIn("86,000",text)
        self.assertNotIn("9 月 22 日",text)
        self.assertNotIn("约90天",text)

    def test_distribution_section_removed(self):
        evidence,state=load()
        text=report_markdown(evidence,state)
        for word in ("分销","贡献率","采购价"):
            self.assertNotIn(word,text)

    def test_daily_card_renders(self):
        import tempfile
        from PIL import Image
        from daily_card import render
        evidence,state=load()
        for day_state in (state,with_board(evidence,state)):
            with tempfile.TemporaryDirectory() as folder:
                path=render(evidence,day_state,Path(folder)/"card.png")
                with Image.open(path) as image:
                    self.assertEqual(image.width,1080)
                    self.assertGreater(image.height,900)

    def test_board_texts_drop_platform_daily_move(self):
        import notify_dingtalk
        from share_page import page_html
        evidence,state=load()
        state=with_board(evidence,state)
        message=notify_dingtalk.message(state)["markdown"]["text"]
        report=report_markdown(evidence,state)
        for text in (message,page_html(state),report):
            self.assertNotIn("日变动",text)
            self.assertIn("今日无新报价",text)
        self.assertIn("$11,400",message)
        self.assertIn("86,499",message)

    def test_share_page_carries_every_source(self):
        from share_page import page_html
        from daily_card import pick_items
        _,state=load()
        page=page_html(state)
        self.assertIn(f"daily/{state['date']}.png",page)
        for item in pick_items(state):
            self.assertIn(f'href="{item["url"]}"',page.replace("&amp;","&"))
        self.assertNotIn("<script",page)

    def test_pushplus_payload(self):
        import notify_pushplus
        _,state=load()
        body=notify_pushplus.payload(state,"t","")
        self.assertEqual(body["template"],"html")
        self.assertNotIn("topic",body)
        self.assertIn(f"daily/{state['date']}.html",body["content"])
        self.assertEqual(notify_pushplus.payload(state,"t","team")["topic"],"team")

    def test_dingtalk_sign_and_message(self):
        import notify_dingtalk
        url=notify_dingtalk.signed_url("https://oapi.dingtalk.com/robot/send?access_token=x","SECtest",1700000000000)
        self.assertIn("&timestamp=1700000000000&sign=",url)
        self.assertEqual(notify_dingtalk.signed_url("https://example.com/?a=1",""),"https://example.com/?a=1")
        _,state=load()
        body=notify_dingtalk.message(state)
        self.assertEqual(body["msgtype"],"markdown")
        self.assertIn(f"daily/{state['date']}.png",body["markdown"]["text"])
        self.assertIn("5500",body["markdown"]["title"])

    def test_channel_brief_uses_reported_delivery(self):
        evidence,state=load()
        state=copy.deepcopy(state);state["channel"]["delivery"]="现货"
        row=next(x for x in fact_briefs(evidence,state) if x["source_id"]=="qudao")
        self.assertIn("现货",row["summary"])
        self.assertNotIn("90天",row["summary"]+row["title"])


if __name__=="__main__":unittest.main()
