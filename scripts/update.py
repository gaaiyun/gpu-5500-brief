"""Collect public evidence without turning unverified headlines into prices."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup
from market import parse_channel, daily_brief, channel_template
from intelligence import enrich
from feed import load_feed, load_leads
from prices import FX_HISTORY_DAYS, FX_HISTORY_URL, build_board, build_series, check_listing, fetch_fx, load_quotes, merge_fx_history, parse_fx_history
from digest import daily_digest

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
HEADERS = {"User-Agent": "GPU5500Brief/1.0 (public-source-monitor; https://github.com/gaaiyun/gpu-5500-brief)"}
MAX_BYTES = 4_000_000


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def read_json(path, fallback=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else fallback


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fetch(url):
    response = requests.get(url, headers=HEADERS, timeout=(12, 28), stream=True)
    response.raise_for_status()
    body = bytearray()
    for chunk in response.iter_content(65536):
        body.extend(chunk)
        if len(body) > MAX_BYTES:
            raise ValueError("响应超过采集上限")
    return bytes(body), response.url, response.headers.get("Content-Type", "")


def get_json(url):
    return json.loads(fetch(url)[0])


def get_text(url):
    return fetch(url)[0].decode("utf-8", errors="replace")


def html_text(content):
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    for node in soup(["script", "style", "nav", "header", "footer"]):
        node.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def extract_signals(source_id, text):
    upper = text.upper()
    product_present = bool(re.search(r"RTX\s*PRO\s*5500", upper))
    if source_id == "nvidia":
        if not product_present or not re.search(r"84\s*GB", upper):
            raise ValueError("未识别到目标型号及显存，可能为挑战页或错误页面")
        coming = "COMING SOON" in upper
        price_mentions = sorted(set(re.findall(r"(?:US\$|USD\s*|\$|¥|￥)\s*\d[\d,.]*", text)))[:8]
        return {"coming_soon": coming, "preliminary": "PRELIMINARY" in upper,
                "needs_review": not coming or bool(price_mentions), "price_mentions": price_mentions,
                "note": "官方页仍显示 Coming Soon" if coming else "Coming Soon 标记变化，需核验；不自动认定上市"}
    if source_id == "smm":
        has_quote = product_present and "9.5万元/张" in text and "预售" in text
        if not has_quote:
            raise ValueError("未复现已核查的预售表述；保留旧记录并等待人工复核")
        return {"historical_quote_present": True, "note": "原报道中的历史预售价仍可复现；未复询卖方"}
    if source_id in ("cls", "reuters", "trendforce"):
        if not product_present:
            raise ValueError("未识别目标型号，可能为挑战页或解析失败")
        return {"note": "原报道可访问；原文发布日期保持不变"}
    if source_id == "qudao":
        return {"excluded": True, "entry_reproduced": product_present,
                "note": "聚合平台保持排除；页面可访问不代表挂牌或成交已验证"}
    return {"note": "资料可访问"}


def check_source(source, previous, checked_at):
    result = {"source_id": source["id"], "checked_at": checked_at, "url": source["url"],
              "published_at": source["published_at"]}
    try:
        body, final_url, content_type = fetch(source["url"])
        if source["id"] == "qudao":
            market = parse_channel(json.loads(body), checked_at)
            result["market"] = market
            signals = {"reference_only":True, "latest_date":market["latest"]["date"],
                       "ask":market["latest"]["ask"],"bid":market["latest"]["bid"],
                       "note":"公开行情 API 已接入；平台参考口径"}
            fingerprint = market["data_sha256"]
        elif source["id"] == "tansun":
            if not body.startswith(b"%PDF-"):
                raise ValueError("公告地址未返回 PDF")
            signals = {"note": "发行人公告 PDF 可访问；合同不等于到货"}
            fingerprint = hashlib.sha256(body).hexdigest()
        else:
            text = html_text(body)
            signals = extract_signals(source["id"], text)
            # Compare meaningful facts, not rotating advertisements/navigation.
            fingerprint = hashlib.sha256(json.dumps(signals, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        result.update(status="ok", signals=signals, sha256=fingerprint, final_url=final_url,
                      last_success_at=checked_at,
                      changed_since_last=bool(previous and previous.get("sha256") and previous["sha256"] != fingerprint))
    except Exception as exc:
        result.update(status="failed", error=str(exc)[:280], last_success_at=previous.get("last_success_at") if previous else None,
                      signals=previous.get("signals", {}) if previous else {},
                      sha256=previous.get("sha256") if previous else None, changed_since_last=False)
        if previous and previous.get("market"):
            result["market"] = previous["market"]
    return result


def parse_feed(content, feed_id, checked_at):
    root = ET.fromstring(content)
    results = []
    cutoff = datetime.fromisoformat(checked_at) - timedelta(days=21)
    from email.utils import parsedate_to_datetime
    for node in root.findall(".//item"):
        title = node.findtext("title", "").strip()
        if not re.search(r"5500", title) or not re.search(r"RTX|英伟达|NVIDIA", title, re.I):
            continue
        pub_raw = node.findtext("pubDate", "")
        try:
            published = parsedate_to_datetime(pub_raw)
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            if published < cutoff or published > datetime.fromisoformat(checked_at) + timedelta(hours=1):
                continue
        except (ValueError, TypeError):
            continue
        source = node.find("source")
        link = node.findtext("link", "").strip()
        if not link.startswith("https://"):
            continue
        publisher = source.text if source is not None and source.text else "未标明"
        # Google News appends " - publisher"; drop it so reprints share one title.
        if title.endswith(" - " + publisher):
            title = title[:-len(publisher) - 3].strip()
        results.append({"title": title[:250], "url": link, "published_at": published.isoformat(),
                        "publisher": publisher,
                        "source_url": source.get("url", "") if source is not None else "",
                        "verification": "headline_only", "feed_id": feed_id})
    return results


def collect_feed(item, checked_at):
    feed_id, query = item
    url = "https://news.google.com/rss/search?q=" + quote(query) + "&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        body, _, _ = fetch(url)
        entries = parse_feed(body, feed_id, checked_at)
        return {"id": feed_id, "status": "ok", "checked_at": checked_at, "url": url,
                "count": len(entries), "entries": entries}
    except Exception as exc:
        return {"id": feed_id, "status": "failed", "checked_at": checked_at, "url": url,
                "error": str(exc)[:280], "entries": []}


MAJOR_MEDIA = re.compile(
    r"Reuters|路透|Bloomberg|彭博|BNN|Financial Times|FT中文|Wall Street Journal|WSJ|华尔街日报|CNBC|Nikkei|日经|"
    r"South China Morning Post|SCMP|The Information|DIGITIMES|TrendForce|集邦|财联社|第一财经|证券时报|中国证券报|"
    r"上海证券报|证券日报|21世纪经济|经济观察|财新|界面|澎湃|新华|人民网|央视|中国新闻网|每日经济新闻|雷峰网|集微|36氪", re.I)


def merge_headlines(feeds):
    """Major-media headlines only, one row per headline; later reprints are listed under the earliest publisher."""
    merged = {}
    entries = sorted((e for f in feeds for e in f["entries"] if MAJOR_MEDIA.search(e["publisher"])),
                     key=lambda x: x["published_at"])
    for entry in entries:
        key = re.sub(r"[\s\-_|·:：，,。]+", "", entry["title"]).casefold()
        if key not in merged:
            merged[key] = dict(entry, reprints=[])
        elif entry["publisher"] not in [merged[key]["publisher"], *merged[key]["reprints"]]:
            merged[key]["reprints"].append(entry["publisher"])
    return sorted(merged.values(), key=lambda x: x["published_at"], reverse=True)[:24]


def forecast_status(evidence, checks, today):
    forecast = evidence["forecast"]
    by_id = {c["source_id"]: c for c in checks}
    anchor_age = (today - datetime.fromisoformat(forecast["anchor_observed_at"]).date()).days
    reasons = []
    if anchor_age > 14:
        reasons.append(f"价格锚点已距今 {anchor_age} 天，缺少直接卖方复询")
    if by_id.get("smm", {}).get("status") != "ok":
        reasons.append("预售锚点来源本轮未成功复现")
    if by_id.get("nvidia", {}).get("status") != "ok":
        reasons.append("官方页面本轮采集失败")
    if by_id.get("nvidia", {}).get("signals", {}).get("needs_review"):
        reasons.append("官方上市标记变化，需要人工复核")
    expired = today > datetime.fromisoformat(forecast["horizon_end"]).date() or anchor_age > 30
    if expired:
        reasons.append("预测期限届满或锚点超过 30 天；停止展示有效数值预测")
    return {"status": "expired" if expired else "review_required" if reasons else "low_confidence",
            "anchor_age_days": anchor_age, "reasons": reasons,
            "reviewed_at": today.isoformat(), "issued_at": forecast["issued_at"],
            "numeric_forecast_active": not expired,
            "note": "无新增已核验价格时，保持预测版本及发布日期；每天复核有效性，不生成伪新价。"}


def previous_day_state(today):
    """Last archived state before today: reruns within a day all report changes against the same baseline."""
    days = sorted(p for p in (ROOT / "data/history").glob("*.json") if p.stem < today.isoformat())
    return read_json(days[-1], {}) if days else {}


def fetch_fx_history(today):
    try:
        start = (today - timedelta(days=FX_HISTORY_DAYS)).isoformat()
        return parse_fx_history(get_json(FX_HISTORY_URL.format(start=start, end=today.isoformat()))), None
    except Exception as error:
        return {}, str(error)[:160]


def run(offline=False):
    evidence = read_json(ROOT / "data/evidence.json")
    previous = read_json(ROOT / "data/state.json", {})
    checked_at = now_iso()
    if offline:
        if not previous:
            raise ValueError("没有可用于离线构建的采集记录")
        return previous
    prev_checks = {c["source_id"]: c for c in previous.get("checks", [])}
    prev_listings = {x["id"]: x for x in previous.get("listings", [])}
    with ThreadPoolExecutor(max_workers=4) as pool:
        fx_job = pool.submit(fetch_fx, get_json, previous.get("fx"), checked_at)
        fx_history_job = pool.submit(fetch_fx_history, datetime.fromisoformat(checked_at).date())
        listings = list(pool.map(lambda x: check_listing(x, prev_listings.get(x["id"]), get_text, checked_at), evidence.get("listings", [])))
        checks = list(pool.map(lambda s: check_source(s, prev_checks.get(s["id"]), checked_at), evidence["sources"]))
        feeds = list(pool.map(lambda item: collect_feed(item, checked_at), [
            ("cn", '"RTX PRO 5500" when:21d'),
            ("price", '"RTX PRO 5500" (价格 OR 报价 OR 交付 OR price OR delivery) when:21d'),
            ("global", '"RTX PRO 5500" (Reuters OR NVIDIA OR supply) when:21d'),
            ("major", '"RTX PRO 5500" (site:reuters.com OR site:bloomberg.com OR site:cls.cn OR site:yicai.com OR site:stcn.com OR site:jiemian.com OR site:21jingji.com OR site:trendforce.com OR site:digitimes.com) when:21d')]))
    # A failed feed never erases the last successful headline collection.
    headlines = merge_headlines(feeds)
    carried = not any(f["status"] == "ok" for f in feeds)
    if carried:
        headlines = previous.get("headlines", [])
    fx = fx_job.result()
    today = datetime.fromisoformat(checked_at).date()
    channel_check = next((c for c in checks if c["source_id"] == "qudao"), {})
    market = channel_check.get("market")
    baseline = previous_day_state(today)
    if market:
        market["template"] = channel_template(market, baseline.get("channel"))
    # Agent-verified web intelligence (cloud routine writes data/feed.json); invalid items are dropped, not fatal.
    feed_payload = read_json(ROOT / "data/feed.json", {})
    feed_items, feed_rejected = load_feed(feed_payload, today)
    feed_leads, leads_rejected = load_leads(feed_payload, today)
    # Team quotes live in a public file: data/quotes.csv carries no supplier names or contacts.
    quotes, quotes_rejected = load_quotes((ROOT / "data/quotes.csv").read_text(encoding="utf-8") if (ROOT / "data/quotes.csv").exists() else "", today)
    board = build_board(evidence, market, fx, listings, feed_items, today, baseline.get("price_board"), quotes)
    # The trend uses the central parity only; a fallback rate would put a jump in the line that the market never made.
    fetched_history, history_error = fx_history_job.result()
    if fx["status"] == "ok" and fx["provider"] == "chinamoney":
        fetched_history[fx["date"]] = fx["rates"]
    fx_history = merge_fx_history(previous.get("fx_history"), fetched_history, today)
    state = {"schema_version": 1, "checked_at": checked_at, "date": today.isoformat(),
             "checks": checks, "feeds": [{k:v for k,v in f.items() if k != "entries"} for f in feeds],
             "headlines": headlines, "headlines_carried_forward": carried,
             "headline_collection_at": previous.get("headline_collection_at") if carried else checked_at,
             "forecast_review": forecast_status(evidence, checks, today),
             "channel":market,"channel_status":channel_check.get("status", "failed"),
             "fx":fx,"fx_history":fx_history,"listings":listings,"price_board":board,"quotes_rejected":quotes_rejected,
             "price_series":build_series(evidence,market,fx_history,quotes,feed_items,today),
             "daily_brief":daily_brief(evidence,market,baseline.get("channel"),board),
             "new_verified_price_count": 0,
             "summary": "本轮自动采集不把新闻标题或聚合挂牌升级为已核验价格；已核验价格更新需要证据复核。"}
    state["intelligence"] = enrich(evidence,state)
    state["feed"] = {"items": feed_items, "leads": feed_leads, "rejected": feed_rejected + leads_rejected,
                     "updated_at": (feed_payload or {}).get("updated_at"), "agent": (feed_payload or {}).get("agent")}
    state["digest"] = daily_digest(state, baseline)
    save_json(ROOT / "data/state.json", state)
    save_json(ROOT / "data/history" / f"{today.isoformat()}.json", state)
    healthy = sum(c["status"] == "ok" for c in checks)
    print(f"Sources: {healthy}/{len(checks)} accessible; feeds: {sum(f['status']=='ok' for f in feeds)}/{len(feeds)}; headlines: {len(headlines)}")
    for check in checks + listings:
        print(f"  {check.get('source_id') or check['id']}: {check['status']}" + (f" ({check['error']})" if check.get("error") else ""))
    print(f"  fx: {fx['status']} {fx.get('provider', '')} {fx.get('date', '')}" + (f" ({fx['error']})" if fx.get("error") else ""))
    print(f"  fx history: {len(fx_history)} days" + (f" ({history_error})" if history_error else ""))
    print(f"  quotes: {len(quotes)} kept, {len(quotes_rejected)} rejected")
    print(f"  today: {state['digest']['headline']}")
    for item in state["digest"]["items"]:
        print(f"    [{item['tag']}] {item['text']}")
    # Partial source failure is visible, while a complete outage fails CI.
    if healthy == 0:
        raise RuntimeError("所有核心来源采集失败；已保留失败记录，禁止宣称刷新成功")
    return state


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        run(args.offline)
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
