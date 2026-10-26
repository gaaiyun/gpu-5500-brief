"""Push the daily report to WeChat through PushPlus (personal, or a topic group when PUSHPLUS_TOPIC is set)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from share_page import body_html, page_url  # noqa: E402

API_URL = "https://www.pushplus.plus/send"


def payload(state, token, topic=""):
    body = {"token": token, "title": f"RTX PRO 5500 行情日报 {state['date']}",
            "content": body_html(state) + f"<p>转发用链接：<a href=\"{page_url(state['date'])}\">{page_url(state['date'])}</a></p>",
            "template": "html", "channel": "wechat"}
    if topic:
        body["topic"] = topic
    return body


def main():
    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    if not token:
        print("未配置 PUSHPLUS_TOKEN，跳过微信推送")
        return 0
    state = json.loads((ROOT / "data/state.json").read_text(encoding="utf-8"))
    if not state.get("channel"):
        print("没有渠道快照，不推送日报", file=sys.stderr)
        return 1
    response = requests.post(API_URL, json=payload(state, token, os.getenv("PUSHPLUS_TOPIC", "").strip()), timeout=20)
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code != 200 or body.get("code") != 200:
        # Never echo the token; PushPlus error text does not contain it.
        print(f"微信推送失败：HTTP {response.status_code} code={body.get('code')} {body.get('msg', '')}", file=sys.stderr)
        return 1
    print(f"微信推送成功：{page_url(state['date'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
