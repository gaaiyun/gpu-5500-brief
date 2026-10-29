"""Daily web sweep in CI: find new RTX PRO 5500 reports, read the articles, let Workers AI draft feed items, keep the checked ones.

The Claude cloud routine checks more deeply when it can reach the web; this sweep keeps data/feed.json moving every day
without it. Nothing here is fatal: a failed source, fetch or model call leaves the existing feed untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import warnings
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup, MarkupResemblesLocatorWarning

from feed import CLAIM_STATUS, MAX_AGE_DAYS, QUICK_TYPES, clean_item, is_card_price, load_leads
from intelligence import SOURCE_LABELS, numeric_values
from update import MAJOR_MEDIA, fetch, now_iso, read_json

warnings.filterwarnings("ignore", category=MarkupResemblesLocatorWarning)

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))
PRODUCT = re.compile(r"RTX\s*PRO\s*5500", re.I)
TOPIC = re.compile(r"价|报价|交付|到货|配额|订单|订购|采购|审批|批准|工信部|供应|缺货|price|order|supply|ship|quota|approv|deliver", re.I)
KEY_PARAGRAPH = re.compile(r"5500|英伟达|NVIDIA|万元|美元|\$|订单|采购|配额|交付|到货|供应|工信部|审批|样卡|报价|价格", re.I)
RECENT_DAYS = 4      # discovery window; links in data/inbox.txt are exempt
MAX_READ = 8         # article fetches per run
BATCH = 3            # articles per model call, well under the Worker's 50k input cap
LEAD_DAYS = 14
MAX_ITEMS_KEPT = 20
MAX_LEADS_KEPT = 15
EXCERPT_CHARS = 3500

# Publisher and source type by domain. A domain missing here can only ever become a link-only lead.
DOMAINS = {
    "reuters.com": ("路透社", "主流媒体"), "bloomberg.com": ("彭博", "主流媒体"), "bnnbloomberg.ca": ("BNN Bloomberg", "主流媒体"),
    "ft.com": ("金融时报", "主流媒体"), "wsj.com": ("华尔街日报", "主流媒体"), "cnbc.com": ("CNBC", "主流媒体"),
    "nikkei.com": ("日经", "主流媒体"), "scmp.com": ("南华早报", "主流媒体"), "theinformation.com": ("The Information", "主流媒体"),
    "thestandard.com.hk": ("英文虎报", "主流媒体"), "cls.cn": ("财联社", "主流媒体"), "yicai.com": ("第一财经", "主流媒体"),
    "stcn.com": ("证券时报", "主流媒体"), "cs.com.cn": ("中国证券报", "主流媒体"), "cnstock.com": ("上海证券报", "主流媒体"),
    "21jingji.com": ("21世纪经济报道", "主流媒体"), "eeo.com.cn": ("经济观察网", "主流媒体"), "caixin.com": ("财新", "主流媒体"),
    "jiemian.com": ("界面新闻", "主流媒体"), "thepaper.cn": ("澎湃新闻", "主流媒体"), "nbd.com.cn": ("每日经济新闻", "主流媒体"),
    "chinanews.com.cn": ("中国新闻网", "主流媒体"), "xinhuanet.com": ("新华网", "主流媒体"), "people.com.cn": ("人民网", "主流媒体"),
    "trendforce.com": ("TrendForce 集邦咨询", "研究机构"), "digitimes.com": ("DIGITIMES", "行业媒体"),
    "leiphone.com": ("雷峰网", "行业媒体"), "laoyaoba.com": ("集微网", "行业媒体"), "36kr.com": ("36氪", "行业媒体"),
    "eet-china.com": ("电子工程专辑", "行业媒体"), "ithome.com": ("IT之家", "行业媒体"), "mydrivers.com": ("快科技", "行业媒体"),
    "tmtpost.com": ("钛媒体", "行业媒体"), "technews.tw": ("科技新报", "行业媒体"), "inside.com.tw": ("INSIDE", "行业媒体"),
    "tomshardware.com": ("Tom's Hardware", "行业媒体"), "tweaktown.com": ("TweakTown", "行业媒体"),
    "videocardz.com": ("VideoCardz", "行业媒体"), "nvidia.com": ("NVIDIA", "官方"), "nvidia.cn": ("NVIDIA", "官方"),
    "cninfo.com.cn": ("巨潮资讯", "公告"),
    # Self-media platforms: fast and often second-hand, so they enter as grade C with every claim checked.
    "mp.weixin.qq.com": ("微信公众号", "公众号"), "sohu.com": ("搜狐号", "公众号"), "163.com": ("网易号", "公众号"),
    "baijiahao.baidu.com": ("百家号", "公众号"), "toutiao.com": ("今日头条", "公众号"), "qq.com": ("腾讯新闻", "公众号"),
}
TYPE_RANK = {"官方": 0, "公告": 0, "主流媒体": 1, "研究机构": 2, "行业媒体": 3, "公众号": 4}

OUTLET_FEEDS = {
    "IT之家": "https://www.ithome.com/rss/", "快科技": "https://rss.mydrivers.com/rss.aspx?Tid=1",
    "雷峰网": "https://www.leiphone.com/feed", "钛媒体": "https://www.tmtpost.com/rss.xml",
    "TrendForce": "https://www.trendforce.com/news/feed/", "DIGITIMES": "https://www.digitimes.com/rss/daily.xml",
    "Tom's Hardware": "https://www.tomshardware.com/feeds/all", "TweakTown": "https://www.tweaktown.com/news-feed/",
    "科技新报": "https://technews.tw/feed/", "INSIDE": "https://www.inside.com.tw/feed/rss",
    "南华早报科技": "https://www.scmp.com/rss/36/feed", "CNBC 科技": "https://www.cnbc.com/id/19854910/device/rss/rss.html",
}
GOOGLE_NEWS_QUERY = '"RTX PRO 5500" when:3d'
GOOGLE_NEWS_EDITIONS = [("zh-CN", "CN", "CN:zh-Hans"), ("en-US", "US", "US:en")]
SOGOU_QUERIES = ["RTX PRO 5500", "RTX PRO 5500 报价", "RTX PRO 5500 到货"]
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


def classify(url):
    host = (urlparse(url).hostname or "").lower()
    for domain in sorted(DOMAINS, key=len, reverse=True):
        if host == domain or host.endswith("." + domain):
            return DOMAINS[domain]
    return None


def to_date(raw):
    """Beijing calendar date of an RSS, page-meta or GDELT timestamp; None when unreadable."""
    raw = str(raw or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"\d{8}T\d{6}Z", raw):
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}T{raw[9:11]}:{raw[11:13]}:{raw[13:15]}+00:00"
    try:
        stamp = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", raw)
            try:
                return date(*map(int, match.groups())) if match else None
            except ValueError:
                return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=TZ)
    return stamp.astimezone(TZ).date()


def strip_html(text):
    return re.sub(r"\s+", " ", BeautifulSoup(text or "", "html.parser").get_text(" ", strip=True))


def xml_root(content):
    # expat cannot read GBK feeds (快科技), so decode in Python first.
    match = re.search(rb'encoding=["\']([\w-]+)', content[:200])
    encoding = match.group(1).decode().lower() if match else "utf-8"
    encoding = "gb18030" if encoding in ("gb2312", "gbk") else encoding
    return ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", content.decode(encoding, errors="replace")))


def parse_rss(content, found_via):
    rows = []
    for node in xml_root(content).iter("item"):
        title = strip_html(node.findtext("title", ""))
        snippet = strip_html(node.findtext("description", ""))
        body = strip_html(node.findtext(CONTENT, ""))
        if not PRODUCT.search(f"{title} {snippet} {body}"):
            continue
        rows.append({"url": node.findtext("link", "").strip(), "title": title, "published_at": to_date(node.findtext("pubDate")),
                     "snippet": snippet[:160], "body": body, "found_via": found_via})
    return rows


def gdelt():
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=" + quote('"RTX PRO 5500"')
           + f"&mode=artlist&format=json&timespan={RECENT_DAYS}d&maxrecords=75&sort=datedesc")
    try:
        body, _, _ = fetch(url)
    except requests.HTTPError as error:
        # GDELT allows one request per 5 seconds per IP, and CI runners share IPs; one spaced retry.
        if error.response is None or error.response.status_code != 429:
            raise
        time.sleep(8)
        body, _, _ = fetch(url)
    return [{"url": row.get("url", ""), "title": row.get("title", ""), "published_at": to_date(row.get("seendate")),
             "snippet": "", "body": "", "found_via": "GDELT"} for row in json.loads(body).get("articles", [])]


def google_news():
    rows = []
    for hl, gl, ceid in GOOGLE_NEWS_EDITIONS:
        body, _, _ = fetch(f"https://news.google.com/rss/search?q={quote(GOOGLE_NEWS_QUERY)}&hl={hl}&gl={gl}&ceid={ceid}")
        for node in xml_root(body).iter("item"):
            source = node.find("source")
            publisher = (source.text or "").strip() if source is not None else ""
            title = node.findtext("title", "").strip()
            if publisher and title.endswith(" - " + publisher):
                title = title[:-len(publisher) - 3].strip()
            rows.append({"title": title, "url": node.findtext("link", "").strip(), "publisher": publisher or "未标明",
                         "published_at": to_date(node.findtext("pubDate")), "snippet": "", "found_via": "Google 新闻"})
    return rows


def sogou_page(html):
    """Result rows only. Its /link redirects turn into a captcha for programs, so they are never opened."""
    rows = []
    for li in BeautifulSoup(html, "html.parser").select("ul.news-list > li"):
        anchor = li.select_one("h3 a")
        if anchor is None:
            continue
        title = re.sub(r"\s+", " ", anchor.get_text("")).strip()
        summary = li.select_one("p.txt-info")
        snippet = re.sub(r"\s+", " ", summary.get_text("")).strip() if summary else ""
        if not PRODUCT.search(f"{title} {snippet}"):
            continue
        account = li.select_one(".all-time-y2")
        stamp = re.search(r"timeConvert\('(\d+)'\)", str(li))
        rows.append({"title": title, "publisher": account.get_text(strip=True) if account else "未标明", "source_type": "公众号",
                     "published_at": datetime.fromtimestamp(int(stamp.group(1)), TZ).date() if stamp else None,
                     "snippet": snippet[:160], "url": "https://weixin.sogou.com/weixin?type=2&query=" + quote(title),
                     "found_via": "搜狗微信"})
    return rows


def sogou_blocked(html, final_url):
    return "antispider" in final_url or "antispider" in html or "请输入验证码" in html


def sogou(notes):
    rows = []
    for index, query in enumerate(SOGOU_QUERIES):
        if index:
            time.sleep(3)
        body, final_url, _ = fetch("https://weixin.sogou.com/weixin?type=2&query=" + quote(query))
        html = body.decode("utf-8", errors="replace")
        if sogou_blocked(html, final_url):
            notes.append("搜狗微信出现验证码，本轮停止搜狗部分")
            break
        rows += sogou_page(html)
    return rows


def inbox():
    path = ROOT / "data/inbox.txt"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [{"url": line.strip(), "title": "", "published_at": None, "snippet": "", "body": "", "found_via": "人工转入", "inbox": True}
            for line in lines if line.strip().startswith("https://")]


def excerpt(paragraphs):
    paragraphs = list(dict.fromkeys(p for p in paragraphs if len(p) >= 12))
    return "\n".join(p for i, p in enumerate(paragraphs) if i < 2 or KEY_PARAGRAPH.search(p))[:EXCERPT_CHARS]


def page_meta(soup, *names):
    for name in names:
        for attr in ("property", "name", "itemprop"):
            node = soup.find("meta", attrs={attr: name})
            if node and node.get("content"):
                return node["content"].strip()
    return ""


def read_article(url):
    body, _, content_type = fetch(url)
    if "html" not in content_type.lower():
        raise ValueError("不是网页正文")
    soup = BeautifulSoup(body, "html.parser")
    title = page_meta(soup, "og:title") or (soup.title.get_text(strip=True) if soup.title else "")
    time_node = soup.find("time", attrs={"datetime": True})
    published = to_date(page_meta(soup, "article:published_time", "og:published_time", "datePublished", "pubdate",
                                  "publishdate", "publish_date") or (time_node["datetime"] if time_node else ""))
    for node in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        node.decompose()
    root = soup.find("article") or soup.body or soup
    paragraphs = [re.sub(r"\s+", " ", p.get_text(" ", strip=True)) for p in root.find_all(["p", "h2", "h3", "li"])]
    if sum(map(len, paragraphs)) < 200:
        paragraphs = [re.sub(r"\s+", " ", line).strip() for line in root.get_text("\n").splitlines()]
    text = excerpt(paragraphs)
    if not PRODUCT.search(text):
        raise ValueError("正文未提到 RTX PRO 5500")
    if len(text) < 150:
        raise ValueError("正文过短")
    return text, title, published


def known_events(feed, evidence):
    """What the site already reports; the model uses it for duplicates and claim checks."""
    events = {s["id"]: {"name": SOURCE_LABELS.get(s["id"], s["name"]), "date": s.get("published_at") or "", "text": s["summary"],
                        "url": s["url"]} for s in evidence.get("sources", [])}
    for item in feed.get("items", []):
        events[item["id"]] = {"name": item["publisher"], "date": item["published_at"], "text": item["summary"], "url": item["url"]}
    return events


def matching_event(text, events):
    """An already-verified event whose figures cover the claim's key figures (not the model number, memory size or years)."""
    key = {v for v in numeric_values(text) if v not in (5500, 84) and not 1900 <= v <= 2100}
    if not key or (max(key) < 1000 and len(key) < 2):
        return None
    return next((k for k, e in events.items() if key <= numeric_values(e["text"])), None)


def readable(text, events):
    """The model sometimes cites events by their internal ID; readers need the source name."""
    text = re.sub(r"已收录事件\s*", "", text)
    for key, event in events.items():
        text = re.sub(rf"(?<![A-Za-z0-9-]){re.escape(key)}(?![A-Za-z0-9-])", event["name"], text)
    return re.sub(r"(?<=[一-鿿])\s+(?=[一-鿿])", "", text)


def ask_model(batch, events, endpoint, token):
    prompt = (ROOT / "prompts/sweep.md").read_text(encoding="utf-8") + "\n\n已收录事件：\n" + "\n".join(
        f"- [{key}] {e['name']}（{e['date'] or '日期不详'}）：{e['text']}" for key, e in events.items())
    sources = [{k: c[k] for k in ("source_id", "url", "publisher", "source_type", "published_at", "title", "text")} for c in batch]
    # Unescaped UTF-8 keeps Chinese text inside the Worker's 50k-character input cap.
    raw = json.dumps({"prompt": prompt, "sources": sources}, ensure_ascii=False).encode("utf-8")
    response = requests.post(endpoint, data=raw, timeout=(10, 60),
                             headers={"Authorization": "Bearer " + token, "Content-Type": "application/json; charset=utf-8"})
    response.raise_for_status()
    body = response.json()
    text = body["text"].strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    rows = json.loads(text).get("items")
    if not isinstance(rows, list):
        raise ValueError("模型输出缺少 items")
    return rows, body.get("model")


def item_id(candidate):
    host = (urlparse(candidate["url"]).hostname or "web").removeprefix("www.").split(".")[0]
    return f"{host}-{candidate['published_at'].replace('-', '')}-{hashlib.sha1(candidate['url'].encode()).hexdigest()[:6]}"


def build_item(draft, candidate, events, today):
    """A draft becomes a feed item only if every number traces back to its article and the site's validator accepts it."""
    article = numeric_values(" ".join([candidate["title"], candidate["text"], candidate["published_at"]]))
    context = article | numeric_values(" ".join(e["text"] for e in events.values()))
    title, summary, impact, watch = (str(draft.get(k) or "").strip() for k in ("title", "summary", "impact", "watch"))
    if not numeric_values(f"{title} {summary}") <= article:
        raise ValueError("摘要出现原文没有的数字")
    if not numeric_values(f"{impact} {watch}") <= context:
        raise ValueError("影响判断出现资料中没有的数字")
    title, summary, impact, watch = (readable(x, events) for x in (title, summary, impact, watch))
    quick = candidate["source_type"] in QUICK_TYPES
    claims = []
    for claim in (draft.get("claims") or [])[:5] if quick else []:
        if not isinstance(claim, dict):
            continue
        text, status, ref_id = str(claim.get("text") or "").strip(), claim.get("status"), str(claim.get("ref") or "")
        if not text or status not in CLAIM_STATUS or not numeric_values(text) <= article:
            continue
        text = readable(text, events)
        ref = events.get(ref_id, {}).get("url", "")
        # "Sourced" must match the cited event's own numbers; anything unprovable is recorded as unsourced.
        if status in ("有出处", "与出处不符") and not ref:
            status = "无出处"
        if status == "有出处" and not numeric_values(text) <= numeric_values(f"{events[ref_id]['text']} {events[ref_id]['date']}"):
            status = "无出处"
        # The cheap model overlooks sources it was shown; key figures matching a verified event make the claim sourced.
        if status in ("无出处", "推算") and (match := matching_event(text, events)):
            status, ref = "有出处", events[match]["url"]
        claims.append({"text": text[:80], "status": status, "ref": ref if status in ("有出处", "与出处不符") else ""})
    item = {"id": item_id(candidate), "title": title, "published_at": candidate["published_at"], "publisher": candidate["publisher"],
            "source_type": candidate["source_type"], "url": candidate["url"], "grade": "C" if quick else "B",
            "summary": summary, "impact": impact, "watch": watch, "corroboration": [], "claims": claims,
            "checked_at": today.isoformat(), "found_via": candidate["found_via"]}
    # The price board takes this number, so it must be printed in the article itself, not converted or recalled.
    price = draft.get("price_cny")
    values = price if isinstance(price, list) else [price]
    if price is not None and 1 <= len(values) <= 2 and all(is_card_price(v) and round(float(v), 4) in article for v in values):
        item["price_cny"] = [min(values), max(values)]
    clean_item(item, today)
    return item


def lead(candidate, today):
    host = urlparse(candidate["url"]).hostname or ""
    published = candidate.get("published_at") or ""
    return {"title": (candidate.get("title") or candidate["url"])[:80], "publisher": candidate.get("publisher") or host,
            "source_type": candidate.get("source_type") or "其他", "url": candidate["url"],
            "published_at": published.isoformat() if isinstance(published, date) else published,
            "found_via": candidate["found_via"], "snippet": (candidate.get("snippet") or "")[:160], "seen_at": today.isoformat()}


def sweep(feed, evidence, today, endpoint=None, token=None):
    notes, searched = [], []

    def attempt(name, func):
        searched.append(name)
        try:
            return func()
        except Exception as error:
            notes.append(f"{name} 失败：{str(error)[:120]}")
            return []

    candidates = attempt('GDELT "RTX PRO 5500"', gdelt)
    with ThreadPoolExecutor(max_workers=6) as pool:
        for rows in pool.map(lambda pair: attempt(f"{pair[0]} RSS", lambda: parse_rss(fetch(pair[1])[0], pair[0])), OUTLET_FEEDS.items()):
            candidates += rows
    candidates += inbox()
    news = attempt(f"Google 新闻 {GOOGLE_NEWS_QUERY}", google_news)
    posts = attempt("搜狗微信 " + " / ".join(SOGOU_QUERIES), lambda: sogou(notes))

    known = ({i["url"] for i in feed["items"]} | {u for i in feed["items"] for u in i.get("corroboration") or []}
             | {s["url"] for s in evidence.get("sources", [])} | {x["url"] for x in feed["leads"]})
    known_titles = {x["title"] for x in feed["leads"]} | {i["title"] for i in feed["items"]}
    oldest = today - timedelta(days=RECENT_DAYS)
    queue, leads = [], []
    for candidate in candidates:
        candidate["url"] = re.sub(r"^http://", "https://", candidate["url"].strip())
        published = candidate.get("published_at")
        if not candidate["url"].startswith("https://") or candidate["url"] in known:
            continue
        if not candidate.get("inbox") and (published is None or not oldest <= published <= today):
            continue
        known.add(candidate["url"])
        kind = classify(candidate["url"])
        candidate.update(publisher=kind[0] if kind else (urlparse(candidate["url"]).hostname or ""),
                         source_type=kind[1] if kind else None)
        if kind:
            queue.append(candidate)
        elif TOPIC.search(candidate["title"]) or candidate.get("inbox"):
            leads.append(lead(candidate, today))
    for row in news:
        if (PRODUCT.search(row["title"]) and TOPIC.search(row["title"]) and not MAJOR_MEDIA.search(row["publisher"])
                and row["published_at"] and row["url"] not in known):
            leads.append(lead(dict(row, source_type="其他"), today))
    for row in posts:
        if row["published_at"] and (today - row["published_at"]).days <= LEAD_DAYS and row["title"] not in known_titles:
            leads.append(lead(row, today))

    queue.sort(key=lambda c: (not c.get("inbox"), TYPE_RANK.get(c["source_type"], 9), -(c["published_at"] or today).toordinal()))
    leads += [lead(c, today) for c in queue[MAX_READ:]]

    def read(candidate):
        try:
            text, title, published = read_article(candidate["url"])
        except Exception as error:
            if len(candidate.get("body") or "") < 300:
                return dict(candidate, error=str(error)[:120])
            text, title, published = excerpt(re.split(r"(?<=[。！？!?])\s*", candidate["body"])), "", None
        published = published or candidate.get("published_at")
        return dict(candidate, text=text, title=candidate.get("title") or title, published_at=published.isoformat() if published else None)

    with ThreadPoolExecutor(max_workers=4) as pool:
        read_rows = list(pool.map(read, queue[:MAX_READ]))
    readable = []
    for row in read_rows:
        if row.get("error") or not row.get("published_at"):
            notes.append(f"读取失败 {row['url']}：{row.get('error') or '无发布日期'}")
            leads.append(lead(row, today))
        elif row.get("inbox") and (today - date.fromisoformat(row["published_at"])).days > MAX_AGE_DAYS:
            notes.append(f"inbox 链接已超过 {MAX_AGE_DAYS} 天，可从 inbox.txt 删除：{row['url']}")
        elif row.get("inbox") or date.fromisoformat(row["published_at"]) >= oldest:
            readable.append(row)

    events = known_events(feed, evidence)
    items, corroborated, model = [], {}, None
    batches = [readable[i:i + BATCH] for i in range(0, len(readable), BATCH)]
    for batch in batches:
        for index, candidate in enumerate(batch, 1):
            candidate["source_id"] = f"s{index}"
        drafts = {}
        if endpoint and token:
            try:
                rows, model = ask_model(batch, events, endpoint, token)
                drafts = {str(r.get("source_id")): r for r in rows if isinstance(r, dict)}
            except Exception as error:
                notes.append(f"模型调用失败：{str(error)[:120]}")
        for candidate in batch:
            draft = drafts.get(candidate["source_id"])
            if draft is None:
                leads.append(lead(candidate, today))
            elif str(draft.get("relevant")).lower() != "true":
                notes.append(f"无关：{candidate['url']}")
            elif str(draft.get("duplicate_of") or "") in events:
                target = str(draft["duplicate_of"])
                if candidate["source_type"] not in QUICK_TYPES and any(i["id"] == target for i in feed["items"]):
                    corroborated.setdefault(target, []).append(candidate["url"])
                notes.append(f"重复报道 {target}：{candidate['url']}")
            else:
                try:
                    items.append(build_item(draft, candidate, events, today))
                except (ValueError, TypeError) as error:
                    notes.append(f"未通过核对 {candidate['url']}：{error}")
                    leads.append(lead(candidate, today))
    return {"items": items, "corroborated": corroborated, "leads": leads, "notes": notes, "searched": searched,
            "candidates": len(queue), "read": len(readable), "model": model}


def merge_feeds(base, cloud):
    """Union of main's feed and the cloud routine's branch feed; the more recently checked copy of an item wins."""
    items, leads = {}, {}
    for source in (base, cloud):
        source = source if isinstance(source, dict) else {}
        for item in source.get("items") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            old = items.get(item["url"])
            if old is None or str(item.get("checked_at", "")) >= str(old.get("checked_at", "")):
                items[item["url"]] = item
        for row in source.get("leads") or []:
            if isinstance(row, dict) and row.get("title") and row["title"] not in leads:
                leads[row["title"]] = row
    return {"items": list(items.values()), "leads": list(leads.values())}


def finalize(items, leads, today):
    kept = []
    for item in items:
        try:
            if clean_item(item, today)["age_days"] <= MAX_AGE_DAYS:
                kept.append(item)
        except (ValueError, TypeError):
            continue
    kept = sorted(kept, key=lambda x: x["published_at"], reverse=True)[:MAX_ITEMS_KEPT]
    urls, titles = {i["url"] for i in kept}, [i["title"] for i in kept]
    fresh = []
    # New leads come first, so a dated copy of a post replaces the undated one carried from earlier days.
    for row in leads:
        row.setdefault("seen_at", today.isoformat())
        try:
            age = (today - date.fromisoformat(row.get("published_at") or row["seen_at"])).days
        except (TypeError, ValueError):
            continue
        if (age > LEAD_DAYS or row.get("url") in urls or any(same_post(row.get("title", ""), t) for t in titles)
                or load_leads({"leads": [row]}, today)[1]):
            continue
        titles.append(row["title"])
        fresh.append(row)
    fresh.sort(key=lambda x: (bool(x.get("published_at")), x.get("published_at") or x["seen_at"]), reverse=True)
    return kept, fresh[:MAX_LEADS_KEPT]


def same_post(a, b):
    """Reposts tweak spacing, punctuation and image captions, so compare titles loosely."""
    a, b = (re.sub(r"[\W_]+", "", str(x)).casefold() for x in (a, b))
    return bool(a) and SequenceMatcher(None, a, b).ratio() >= 0.8


def run(cloud_path=None, dry_run=False):
    today = datetime.now(TZ).date()
    path = ROOT / "data/feed.json"
    base = read_json(path, {}) or {}
    cloud = read_json(Path(cloud_path), None) if cloud_path and Path(cloud_path).exists() else None
    feed = merge_feeds(base, cloud)
    try:
        result = sweep(feed, read_json(ROOT / "data/evidence.json"), today, os.getenv("GPU_AI_ENDPOINT"), os.getenv("GPU_AI_TOKEN"))
    except Exception as error:
        # A broken sweep still publishes the merged feed, so the cloud routine's work is never lost.
        result = {"items": [], "corroborated": {}, "leads": [], "notes": [f"本轮检索中断：{str(error)[:160]}"], "searched": [],
                  "candidates": 0, "read": 0, "model": None}
    for item in feed["items"]:
        extra = [u for u in result["corroborated"].get(item["id"], []) if u not in (item.get("corroboration") or [])]
        if extra:
            item["corroboration"] = [*(item.get("corroboration") or []), *extra][:5]
    items, leads = finalize(result["items"] + feed["items"], result["leads"] + feed["leads"], today)
    payload = {"schema_version": 1, "updated_at": now_iso(), "agent": "actions-sweep" + ("+cloud-routine" if cloud else ""),
               "searched": result["searched"][:30], "items": items, "leads": leads,
               "sweep": {"date": today.isoformat(), "candidates": result["candidates"], "read": result["read"],
                         "added": [i["id"] for i in result["items"] if i in items],
                         "corroborated": sum(map(len, result["corroborated"].values())), "model": result["model"],
                         "notes": result["notes"][:20]}}
    print(f"Sweep: {result['candidates']} candidates, {result['read']} read, {len(payload['sweep']['added'])} added, "
          f"{payload['sweep']['corroborated']} corroborations, {len(leads)} leads kept")
    for note in result["notes"][:20]:
        print("  " + note)
    if not dry_run:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cloud", help="data/feed.json from the cloud routine's branch, merged before the sweep")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        run(args.cloud, args.dry_run)
    except Exception as error:
        print(f"Sweep failed, feed left unchanged: {error}", file=sys.stderr)
        sys.exit(1)
