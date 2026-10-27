"""Validate the agent-maintained web intelligence feed before it reaches the site or the daily push."""
from __future__ import annotations

import re
from datetime import date, timedelta

SOURCE_TYPES = {"官方", "公告", "主流媒体", "行业媒体", "研究机构", "公众号", "社媒", "电商/渠道"}
GRADES = {"A": "多方印证", "B": "单一可信来源", "C": "待核实线索"}
QUICK_TYPES = {"公众号", "社媒"}
CLAIM_STATUS = ("有出处", "推算", "无出处", "与出处不符")
MAX_AGE_DAYS = 45
MAX_ITEMS = 12
TEXT_LIMITS = {"title": 60, "summary": 260, "impact": 140, "watch": 60, "publisher": 60}


def clean_item(item, today):
    if not isinstance(item, dict):
        raise ValueError("条目不是对象")
    for field in ("id", "title", "published_at", "publisher", "source_type", "url", "grade", "summary", "impact", "watch"):
        if not isinstance(item.get(field), str) or not item[field].strip():
            raise ValueError(f"缺少字段 {field}")
    for field, limit in TEXT_LIMITS.items():
        if len(item[field]) > limit:
            raise ValueError(f"{field} 超过 {limit} 字")
    if not item["url"].startswith("https://"):
        raise ValueError("来源链接必须是 https")
    if item["source_type"] not in SOURCE_TYPES:
        raise ValueError("来源类型不在白名单")
    if item["grade"] not in GRADES:
        raise ValueError("可信度等级只能是 A/B/C")
    published = date.fromisoformat(item["published_at"])
    if published > today:
        raise ValueError("发布日期在未来")
    corroboration = [u for u in item.get("corroboration") or [] if isinstance(u, str) and u.startswith("https://")]
    # "A" means several independent sources agree; without a second link it cannot be A.
    if item["grade"] == "A" and not corroboration:
        raise ValueError("A 级必须附交叉印证链接")
    claims = []
    for claim in (item.get("claims") or [])[:6]:
        if not isinstance(claim, dict) or claim.get("status") not in CLAIM_STATUS or not str(claim.get("text", "")).strip():
            raise ValueError("说法核对格式错误")
        ref = claim.get("ref") if str(claim.get("ref", "")).startswith("https://") else ""
        if claim["status"] in ("有出处", "与出处不符") and not ref:
            raise ValueError("有出处/与出处不符的说法必须附原始出处链接")
        claims.append({"text": str(claim["text"]).strip()[:80], "status": claim["status"], "ref": ref})
    # Fast but second-hand posts are welcome, as long as they arrive pre-checked and never above grade C.
    quick = item["source_type"] in QUICK_TYPES
    if quick and (item["grade"] != "C" or not claims):
        raise ValueError("公众号/社媒只能是 C 级且必须逐条核对说法")
    text = " ".join([item[f] for f in ("title", "summary", "impact", "watch")] + [c["text"] for c in claims])
    if re.search(r"<|>|javascript:", text):
        raise ValueError("文本含标记或脚本")
    return {**{k: item[k].strip() for k in ("id", "title", "published_at", "publisher", "source_type", "url", "grade", "summary", "impact", "watch")},
            "grade_label": GRADES[item["grade"]], "corroboration": corroboration[:5], "claims": claims,
            "tier": "快讯" if quick else "核实",
            "checked_at": str(item.get("checked_at") or "")[:10], "age_days": (today - published).days}


def claim_tally(item):
    counts = {s: 0 for s in CLAIM_STATUS}
    for claim in item.get("claims", []):
        counts[claim["status"]] += 1
    return " · ".join(f"{s} {n}" for s, n in counts.items() if n)


def load_feed(payload, today):
    """Return (items, rejected). A bad item is dropped with a reason; it never blocks the daily run."""
    items, rejected, seen = [], [], set()
    for raw in (payload or {}).get("items", []) if isinstance(payload, dict) else []:
        try:
            item = clean_item(raw, today)
        except (ValueError, TypeError) as error:
            rejected.append({"id": str(raw.get("id") if isinstance(raw, dict) else "?")[:80], "reason": str(error)})
            continue
        if item["url"] in seen or item["age_days"] > MAX_AGE_DAYS:
            continue
        seen.add(item["url"])
        items.append(item)
    items.sort(key=lambda x: (x["published_at"], x["grade"] == "A"), reverse=True)
    return items[:MAX_ITEMS], rejected


def fresh(items, days=7):
    return [x for x in items if x["age_days"] <= days]
