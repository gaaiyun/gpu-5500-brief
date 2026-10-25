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
    market = state["channel"]
    p, stats = market["latest"], market["stats"]
    day = state["date"]
    image = f"{SITE}daily/{day}.png"
    lines = [f"#### RTX PRO 5500 大陆行情日报 {day}",
             f"**渠道（{p['date']}）** 卖均 ¥{p['ask']:,}，买均 ¥{p['bid']:,}，中间值日变动 {stats['day_pct']:+.2f}%；"
             f"最低挂价 ¥{market['min_ask']:,}（{market.get('delivery') or '交期未标明'}，原报价 {market.get('quote_date') or '未标明'}）。"
             f"来源：[宽泛采销公开接口]({market['source_url']})",
             f"![日报]({image})",
             "**市场情报**"]
    for n, item in enumerate(pick_items(state), 1):
        lines.append(f"{n}. **{item['title']}**（{item['date']}）  \n"
                     f"事实：{item['summary']}  \n"
                     f"影响：{item['impact']}  \n"
                     f"跟进：{item['watch']}  \n"
                     f"来源：[{item.get('source') or item['source_id']}]({item['url']})")
    lines.append(f"[网站：完整曲线、报价对照与研究报告]({SITE})")
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
