"""Flash alerts: a new mainland quote or an overseas retail repricing reaches the group within the run that finds it.

Daytime patrols, quote-form filings and data pushes run this after the site is published. Changes are counted from the
report the group last received, so the next morning report still lists everything; an alert only gets news out sooner.
At most two alerts a day, none at night, none before the morning report, and no change is sent twice."""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import push_log  # noqa: E402
from notify_dingtalk import SITE, signed_url  # noqa: E402
from notify_pushplus import API_URL as PUSHPLUS_URL  # noqa: E402
from prices import _changes  # noqa: E402

TZ = timezone(timedelta(hours=8))
MAX_PER_DAY = 2
DAY_HOURS = (8, 22)      # Beijing time; a change found at night waits for the morning report or the next patrol
NEW_ROW_MAX_AGE = 7      # a report older than this found today is backfill, not news
KEEP_DAYS = 7
REVIEW_MOVE = .15        # a bigger one-day move on a shop page is more often a page change than a repricing


def events(state, report):
    """New or changed quotes since `report`; a rate move or a listing's first sighting is not news."""
    old = (report or {}).get("price_board")
    if not old:
        return []
    before = {r["id"]: r for r in old.get("rows", [])}
    rows = {r["id"]: r for r in (state.get("price_board") or {}).get("rows", [])}
    today = date.fromisoformat(state["date"])
    found = []
    for change in _changes(list(rows.values()), old):
        if change["kind"] != "新报价":
            continue
        r, prev = rows[change["id"]], before.get(change["id"])
        if r["kind"] == "海外零售":
            if prev is None:
                continue
            amount, _, tax = r["native"].partition("（")
            notes = [tax.rstrip("）")] if tax else []
            if r.get("price") and prev.get("price"):
                move = r["price"] / prev["price"] - 1
                notes.insert(0, f"{move:+.1%}")
            text = f"{r['label']} {prev['native'].split('（')[0]} → {amount}" + (f"（{'，'.join(notes)}）" if notes else "")
            if r.get("price") and prev.get("price") and abs(move) > REVIEW_MOVE:
                text += "，单日变动超过 15%，待人工核对页面"
            if r.get("cny_vat"):
                text += f"，{r['text']}"
            tag = "海外零售"
        elif prev is None:
            if (today - date.fromisoformat(r["date"])).days > NEW_ROW_MAX_AGE:
                continue
            value = f"{r['native']}，{r['text']}" if r["converted"] else r["native"]
            text = f"{r['label']} {value}（{r['date']}" + (f"；{r['note']}" if r.get("note") else "") + "）"
            tag = r["kind"] if r["kind"] in ("团队询价", "网上挂价") else "新报价"
        else:
            text = f"{r['label']} {prev['native']} → {r['native']}（原报价日期 {r['date']}）"
            tag = "新报价"
        found.append({"key": f"{r['id']}|{r['quote_key']}", "tag": tag, "text": text, "url": r.get("url", "")})
    # Mainland quotes first; overseas retail is context.
    return sorted(found, key=lambda e: e["tag"] == "海外零售")


def blocked(log, now):
    """Why no alert may go out now, or None."""
    day = now.date().isoformat()
    if not DAY_HOURS[0] <= now.hour < DAY_HOURS[1]:
        return "夜间不发快讯，变化留给白天巡检或明早晨报"
    if day not in (log.get("dingtalk"), log.get("pushplus")):
        return "今天的晨报还没发出，变化留给晨报"
    if sum(p["at"][:10] == day for p in log.get("alerts", [])) >= MAX_PER_DAY:
        return f"今天已发 {MAX_PER_DAY} 次快讯，其余留给明早晨报"
    return None


def unsent(found, log):
    sent = {k for p in log.get("alerts", []) for k in p["keys"]}
    return [e for e in found if e["key"] not in sent]


def record(log, found, channels, now):
    cutoff = (now.date() - timedelta(days=KEEP_DAYS)).isoformat()
    kept = [p for p in log.get("alerts", []) if p["at"][:10] >= cutoff]
    return dict(log, alerts=kept + [{"at": now.isoformat(timespec="minutes"), "keys": [e["key"] for e in found],
                                     "channels": channels}])


def _line(e):
    # Team quote labels already start with their kind.
    return e["text"] if e["text"].startswith(e["tag"]) else f"[{e['tag']}] {e['text']}"


def _context(state, base):
    dom = (state.get("price_board") or {}).get("domestic")
    parts = [f"大陆报价区间 {dom['low']:,}-{dom['high']:,} 元（{dom['count']} 条来源）"] if dom else []
    if base:
        parts.append(f"预测基准 {base['low']:,}-{base['high']:,} 元")
    return "；".join(parts)


def dingtalk_message(found, state, base, now):
    title = f"5500 价格快讯 {now:%m-%d %H:%M}"
    # Bare URLs, not [text](url): markdown links lose their address when copied out of DingTalk.
    items = "\n".join(f"- {_line(e)}" + (f" {e['url']}" if e["url"] else "") for e in found)
    lines = [f"#### RTX PRO 5500 价格快讯 {now:%m-%d %H:%M}", items, _context(state, base),
             f"完整证据表：{SITE}", "明早晨报照常汇总。"]
    return {"msgtype": "markdown", "markdown": {"title": title, "text": "\n\n".join(x for x in lines if x)}}


def pushplus_payload(found, state, base, now, token, topic=""):
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    items = "".join(f"<li>{esc(_line(e))}" + (f" <a href=\"{esc(e['url'])}\">来源</a>" if e["url"] else "") + "</li>"
                    for e in found)
    body = {"token": token, "title": f"RTX PRO 5500 价格快讯 {now:%m-%d %H:%M}", "template": "html", "channel": "wechat",
            "content": f"<ul>{items}</ul><p>{esc(_context(state, base))}</p><p>完整证据表：<a href=\"{SITE}\">{SITE}</a></p>"
                       "<p>明早晨报照常汇总。</p>"}
    if topic:
        body["topic"] = topic
    return body


def send(found, state, base, now):
    """Channels that took the alert; credentials come from the environment and are never printed."""
    delivered = []
    webhook = os.getenv("DINGTALK_WEBHOOK", "").strip()
    if webhook:
        try:
            r = requests.post(signed_url(webhook, os.getenv("DINGTALK_SECRET", "").strip()),
                              json=dingtalk_message(found, state, base, now), timeout=20)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 200 and body.get("errcode") == 0:
                delivered.append("dingtalk")
            else:
                print(f"钉钉快讯失败：HTTP {r.status_code} errcode={body.get('errcode')} {body.get('errmsg', '')}", file=sys.stderr)
        except requests.RequestException as error:
            print(f"钉钉快讯失败：{type(error).__name__}", file=sys.stderr)
    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    if token:
        try:
            r = requests.post(PUSHPLUS_URL, json=pushplus_payload(found, state, base, now, token, os.getenv("PUSHPLUS_TOPIC", "").strip()),
                              timeout=20)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 200 and body.get("code") == 200:
                delivered.append("pushplus")
            else:
                print(f"微信快讯失败：HTTP {r.status_code} code={body.get('code')} {body.get('msg', '')}", file=sys.stderr)
        except requests.RequestException as error:
            print(f"微信快讯失败：{type(error).__name__}", file=sys.stderr)
    return delivered


def main(now=None):
    now = now or datetime.now(TZ)
    log = push_log.load()
    reason = blocked(log, now)
    if reason:
        print(f"不发快讯：{reason}")
        return 0
    state = json.loads(push_log.STATE.read_text(encoding="utf-8"))
    report = push_log.last_report(now.date().isoformat())
    if report is None:
        # First run after this feature shipped: what the group saw this morning was not kept, so start counting now.
        push_log.snapshot()
        print("尚无晨报基线：以当前状态为基线，本轮不发快讯")
        return 0
    found = unsent(events(state, report), log)
    if not found:
        print("自晨报以来没有新的报价或零售改价")
        return 0
    for e in found:
        print(f"  {_line(e)}")
    if not (os.getenv("DINGTALK_WEBHOOK", "").strip() or os.getenv("PUSHPLUS_TOKEN", "").strip()):
        print("未配置推送渠道，跳过")
        return 0
    evidence = json.loads((ROOT / "data/evidence.json").read_text(encoding="utf-8"))
    base = next((s for s in evidence["forecast"]["scenarios"] if s["id"] == "base"), None)
    delivered = send(found, state, base, now)
    if not delivered:
        print("快讯没有送达任何渠道，变化会进明早晨报", file=sys.stderr)
        return 1
    push_log.save(record(log, found, delivered, now))
    print(f"快讯已送达：{'、'.join(delivered)}（{len(found)} 条）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
