"""Push the published daily image to a DingTalk group robot (custom robot, signed)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SITE = "https://gaaiyun.github.io/gpu-5500-brief/"


def signed_url(webhook, secret, now_ms=None):
    if not secret:
        return webhook
    timestamp = str(now_ms or int(time.time() * 1000))
    digest = hmac.new(secret.encode(), f"{timestamp}\n{secret}".encode(), hashlib.sha256).digest()
    return f"{webhook}&timestamp={timestamp}&sign={quote(base64.b64encode(digest))}"


def message(state):
    from daily_card import pick_items
    from share_page import MIRROR, page_url
    from share_page import price_lines
    day = state["date"]
    image = f"{SITE}daily/{day}.png"
    lines = [f"#### RTX PRO 5500 大陆行情日报 {day}",
             f"转发微信用这一条链接（图、情报和来源都在里面）：{page_url(day)}  \n国内打不开时用镜像：{page_url(day, MIRROR)}"]
    digest = state.get("digest")
    if digest:
        lines.append(f"**今日新增：{digest['headline']}**  \n"
                     + "  \n".join(f"[{i['tag']}] {i['text']}" + (f" {i['url']}" if i.get("url") else "") for i in digest["items"]))
    if state.get("price_board"):
        lines += ([] if digest else [f"**今日变化** {state['price_board']['summary']}"]) + [
                  "**价格证据（按原始日期）**  \n" + "  \n".join(price_lines(state))]
    else:
        market = state["channel"]
        p, stats = market["latest"], market["stats"]
        lines.append(f"**渠道（{p['date']}）** 卖均 ¥{p['ask']:,}，买均 ¥{p['bid']:,}，中间值日变动 {stats['day_pct']:+.2f}%；"
                     f"最低挂价 ¥{market['min_ask']:,}（{market.get('delivery') or '交期未标明'}，原报价 {market.get('quote_date') or '未标明'}）。"
                     f"来源：宽泛采销公开接口 {market['source_url']}")
    lines += [f"![日报]({image})", "**市场情报**"]
    for n, item in enumerate(pick_items(state), 1):
        lines.append(f"{n}. **{item['title']}**（{item['date']}）  \n"
                     f"事实：{item['summary']}  \n"
                     f"影响：{item['impact']}  \n"
                     f"跟进：{item['watch']}  \n"
                     f"来源：{item['source']} {item['url']}")
    feed = [x for x in (state.get("feed") or {}).get("items", []) if x.get("age_days", 99) <= 14]
    if feed:
        lines.append("**全网追踪（AI 读原文核对）**")
        for item in feed[:6]:
            checks = "".join(f"  \n【{c['status']}】{c['text']}" + (f" {c['ref']}" if c["ref"] else "") for c in item.get("claims", []))
            lines.append(f"- **[{item.get('tier', '核实')}·{item['grade_label']}] {item['title']}**（{item['published_at']}，{item['publisher']}）  \n"
                         f"{item['summary']}  \n影响：{item['impact']}{checks}  \n来源：{item['url']}")
    leads = (state.get("feed") or {}).get("leads", [])
    if leads:
        lines.append("**未核实线索（只给链接，点开自行判断）**")
        lines.append("\n".join(f"- {x['title']}（{x['publisher']}）{x['url']}" for x in leads[:10]))
    # Bare URLs, not [text](url): markdown links lose their address when copied out of DingTalk.
    lines.append(f"日报图原图：{image}")
    lines.append("看到闲鱼、微信群或供应商的报价，在这里登记（可贴链接和截图），几分钟后上网站，白天会以快讯推到群里，22 点后登记的进明早晨报：https://github.com/gaaiyun/gpu-5500-brief/issues/new?template=quote.yml")
    lines.append(f"网站（完整曲线、报价对照与研究报告）：{SITE}  \n国内镜像：{MIRROR}")
    # The title and text both carry "5500" so a keyword-secured robot also accepts it.
    return {"msgtype": "markdown", "markdown": {"title": f"5500 日报 {day}", "text": "\n\n".join(lines)}}


def wait_for_image(url, attempts=10):
    for _ in range(attempts):
        try:
            r = requests.get(url, timeout=20)
            if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/"):
                return True
        except requests.RequestException:
            pass
        time.sleep(15)
    return False


def main():
    webhook = os.getenv("DINGTALK_WEBHOOK", "").strip()
    if not webhook:
        print("未配置 DINGTALK_WEBHOOK，跳过钉钉推送")
        return 0
    state = json.loads((ROOT / "data/state.json").read_text(encoding="utf-8"))
    if not state.get("channel"):
        print("没有渠道快照，不推送日报", file=sys.stderr)
        return 1
    payload = message(state)
    image = f"{SITE}daily/{state['date']}.png"
    if not wait_for_image(image):
        print(f"线上日报图不可访问：{image}", file=sys.stderr)
        return 1
    response = requests.post(signed_url(webhook, os.getenv("DINGTALK_SECRET", "").strip()), json=payload, timeout=20)
    body = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
    if response.status_code != 200 or body.get("errcode") != 0:
        # Never print the webhook itself; it carries the access token.
        print(f"钉钉推送失败：HTTP {response.status_code} errcode={body.get('errcode')} {body.get('errmsg', '')}", file=sys.stderr)
        return 1
    print(f"钉钉推送成功：{image}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
