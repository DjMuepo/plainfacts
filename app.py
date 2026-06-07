import hashlib
import html
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import feedparser
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

APP_VERSION = "1.1.0"
CACHE_TTL_SECONDS = 60 * 20

RSS_FEEDS = {
    "npr-news": "https://feeds.npr.org/1001/rss.xml",
    "npr-world": "https://feeds.npr.org/1004/rss.xml",
    "npr-politics": "https://feeds.npr.org/1014/rss.xml",
    "npr-business": "https://feeds.npr.org/1006/rss.xml",
    "npr-economy": "https://feeds.npr.org/1017/rss.xml",
    "bbc-world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "bbc-business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "federal-register": "https://www.federalregister.gov/documents/search.rss",
}

FEED_CACHE: List[Dict[str, Any]] = []
LAST_LOAD_EPOCH = 0.0

app = FastAPI(title="PlainFacts API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<script[\s\S]*?</script>", " ", value, flags=re.I)
    value = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.I)
    value = re.sub(r"<[^>]*>", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def make_id(title: str, link: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:70]
    digest = hashlib.sha1((title + link).encode("utf-8", "ignore")).hexdigest()[:8]
    return f"{slug}-{digest}" if slug else digest


def extract_image(entry: Any) -> str:
    try:
        media_fields = ["media_content", "media_thumbnail"]
        for field in media_fields:
            values = entry.get(field)
            if values:
                for media in values:
                    url = media.get("url", "")
                    if url:
                        return url

        for field in ["links", "enclosures"]:
            values = entry.get(field)
            if values:
                for link in values:
                    href = link.get("href", "") or link.get("url", "")
                    typ = str(link.get("type", ""))
                    rel = str(link.get("rel", ""))
                    if href and ("image" in typ or rel == "enclosure" or href.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
                        return href

        html_parts: List[str] = []
        if entry.get("summary"):
            html_parts.append(str(entry.get("summary")))
        if entry.get("description"):
            html_parts.append(str(entry.get("description")))
        if entry.get("content"):
            for c in entry.content:
                html_parts.append(str(c.get("value", "")))
        raw = " ".join(html_parts)
        match = re.search(r'<img[^>]+src=["\\\']([^"\\\']+)["\\\']', raw, re.I)
        if match:
            return html.unescape(match.group(1))
    except Exception:
        return ""
    return ""


def classify_article(title: str, summary: str, source: str = "") -> str:
    text = f"{title} {summary} {source}".lower()

    economy_keywords = [
        "business", "economy", "economic", "inflation", "market", "markets", "stock", "stocks",
        "bank", "finance", "financial", "federal reserve", "rate", "crypto", "bitcoin", "oil", "gas",
        "tariff", "trade", "jobs", "earnings", "money", "prices", "cost", "sales", "retail",
        "consumer", "company", "industry", "labor", "wages", "housing", "mortgage", "rent",
        "investment", "investor", "revenue", "profit", "debt", "budget", "electric", "utility",
        "walmart", "fuel", "tax", "supply chain", "currency", "wall street",
    ]
    domestic_keywords = [
        "u.s.", "us ", "united states", "america", "american", "white house", "congress", "senate",
        "supreme court", "federal", "california", "texas", "florida", "new york", "washington",
        "trump", "biden", "tsa", "fbi", "cdc", "immigration", "ice", "governor", "mayor",
        "republican", "democrat", "border", "lawmakers", "administration",
    ]
    global_keywords = [
        "world", "global", "international", "foreign", "china", "russia", "ukraine", "israel",
        "iran", "europe", "africa", "asia", "india", "nato", "britain", "france", "germany",
        "canada", "mexico", "cannes", "romania", "chile", "norway", "gaza", "taiwan",
        "korea", "japan", "australia", "united nations",
    ]

    scores = {
        "economy": sum(1 for k in economy_keywords if k in text),
        "domestic": sum(1 for k in domestic_keywords if k in text),
        "global": sum(1 for k in global_keywords if k in text),
    }
    source_lower = source.lower()
    if "business" in source_lower or "economy" in source_lower:
        scores["economy"] += 4
    if "politics" in source_lower or "federal" in source_lower:
        scores["domestic"] += 3
    if "world" in source_lower:
        scores["global"] += 4

    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "global"


def importance_score(item: Dict[str, Any]) -> float:
    text = f"{item.get('title','')} {item.get('summary','')} {item.get('source','')}".lower()
    score = 1.0
    for word in [
        "breaking", "war", "ceasefire", "president", "congress", "court", "supreme court", "inflation",
        "market", "election", "tariff", "trade", "oil", "bank", "immigration", "security", "federal",
        "climate", "economy", "business", "prices", "cost", "government", "lawsuit", "dead", "killed",
    ]:
        if word in text:
            score += 0.85
    if "npr" in item.get("source", "").lower():
        score *= 1.10
    if "bbc" in item.get("source", "").lower():
        score *= 1.08
    return round(score, 2)


def normalize_entry(source: str, entry: Any) -> Optional[Dict[str, Any]]:
    title = clean_text(entry.get("title", ""))
    summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
    link = entry.get("link", "") or ""
    if not title:
        return None
    item = {
        "id": make_id(title, link),
        "source": source,
        "title": title,
        "topic_title": title,
        "summary": summary,
        "what": summary or title,
        "link": link,
        "url": link,
        "image": extract_image(entry),
        "published": entry.get("published", "") or entry.get("updated", ""),
    }
    item["category"] = classify_article(title, summary, source)
    item["importance_score"] = importance_score(item)
    return item


def load_feeds(force: bool = False) -> None:
    global FEED_CACHE, LAST_LOAD_EPOCH
    if FEED_CACHE and not force and time.time() - LAST_LOAD_EPOCH < CACHE_TTL_SECONDS:
        return

    items: List[Dict[str, Any]] = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:80]:
                item = normalize_entry(source, entry)
                if item:
                    items.append(item)
        except Exception as exc:
            print(f"Feed failed: {source}: {exc}")

    seen_titles = set()
    unique: List[Dict[str, Any]] = []
    for item in items:
        key = clean_text(item.get("title", "")).lower()
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        unique.append(item)

    unique.sort(key=lambda x: x.get("importance_score", 0), reverse=True)
    FEED_CACHE = unique
    LAST_LOAD_EPOCH = time.time()
    print(f"Loaded {len(FEED_CACHE)} articles")


def articles() -> List[Dict[str, Any]]:
    load_feeds()
    return FEED_CACHE


def dedupe_and_sort(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique: List[Dict[str, Any]] = []
    for item in sorted(items, key=lambda x: x.get("importance_score", 0), reverse=True):
        key = item.get("id") or item.get("title", "").lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def search_items(query: str, pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    q = query.lower().strip()
    if not q:
        return []
    words = [w for w in re.split(r"\W+", q) if len(w) > 1]
    results = []
    for item in pool:
        text = f"{item.get('title','')} {item.get('summary','')} {item.get('source','')} {item.get('category','')}".lower()
        if q in text or any(word in text for word in words):
            results.append(item)
    return dedupe_and_sort(results)


@app.get("/health")
def health():
    data = articles()
    return {
        "ok": True,
        "version": APP_VERSION,
        "time_utc": now_utc(),
        "articles": len(data),
        "global": len([x for x in data if x.get("category") == "global"]),
        "domestic": len([x for x in data if x.get("category") == "domestic"]),
        "economy": len([x for x in data if x.get("category") == "economy"]),
    }


@app.get("/feed")
def feed():
    return articles()


@app.get("/briefs")
def briefs(q: str = Query("", max_length=200), max_clusters: int = Query(10, ge=1, le=100)):
    data = articles()
    if not q.strip():
        return data[:max_clusters]
    return search_items(q, data)[:max_clusters]


@app.get("/category/{category}")
def category(category: str):
    category = category.lower().strip()
    data = articles()
    if category not in {"global", "domestic", "economy"}:
        return []
    filtered = [x for x in data if x.get("category") == category]
    return dedupe_and_sort(filtered)[:50]


@app.get("/search")
def search(q: str = Query("", max_length=200)):
    return search_items(q, articles())[:50]


@app.get("/article/{article_id}")
def article(article_id: str):
    for item in articles():
        if item.get("id") == article_id:
            return item
    return {"error": "Article not found"}


@app.get("/markets")
def markets():
    econ = category("economy")[:10]
    return {
        "updated": now_utc(),
        "watchlist": [
            {"symbol": "S&P 500", "note": "Connect a market-data API for live price."},
            {"symbol": "Nasdaq", "note": "Connect a market-data API for live price."},
            {"symbol": "Dow", "note": "Connect a market-data API for live price."},
            {"symbol": "Bitcoin", "note": "Connect a crypto API for live price."},
            {"symbol": "Ethereum", "note": "Connect a crypto API for live price."},
        ],
        "news": econ,
    }


@app.get("/reload")
def reload_feeds():
    load_feeds(force=True)
    return {"ok": True, "articles": len(FEED_CACHE), "time_utc": now_utc()}

NEWSLETTER_SIGNUPS: List[Dict[str, Any]] = []
USER_REPORTS: List[Dict[str, Any]] = []


@app.post("/newsletter")
def newsletter_signup(payload: Dict[str, Any]):
    email = clean_text(payload.get("email", ""))
    topics = payload.get("topics", [])

    if "@" not in email:
        return {"ok": False, "error": "Valid email required"}

    signup = {
        "email": email,
        "topics": topics if isinstance(topics, list) else [],
        "created_at": now_utc(),
    }

    NEWSLETTER_SIGNUPS.append(signup)
    return {"ok": True, "message": "Newsletter signup saved"}


@app.post("/report")
def report_issue(payload: Dict[str, Any]):
    report = {
        "type": clean_text(payload.get("type", "general")),
        "message": clean_text(payload.get("message", "")),
        "article_id": clean_text(payload.get("article_id", "")),
        "url": clean_text(payload.get("url", "")),
        "created_at": now_utc(),
    }

    USER_REPORTS.append(report)
    return {"ok": True, "message": "Report received"}


@app.get("/admin/stats")
def admin_stats():
    data = articles()
    return {
        "ok": True,
        "articles": len(data),
        "global": len([x for x in data if x.get("category") == "global"]),
        "domestic": len([x for x in data if x.get("category") == "domestic"]),
        "economy": len([x for x in data if x.get("category") == "economy"]),
        "newsletter_signups": len(NEWSLETTER_SIGNUPS),
        "reports": len(USER_REPORTS),
        "latest_reports": USER_REPORTS[-10:],
        "latest_signups": NEWSLETTER_SIGNUPS[-10:],
    }

load_feeds(force=True)
