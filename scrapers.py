"""VortexAI scrapers runner (SAFE starter).

IMPORTANT:
- Many marketplaces block scraping and/or forbid automated collection in their Terms.
- This starter intentionally supports *allowed* sources (RSS feeds, your own CSV exports,
  public/official APIs, and user-provided URLs where you have permission).

How it works:
- Loads sources from DEAL_SOURCES_JSON (list of dicts) OR the Postgres deal_sources table.
- Fetches RSS/Atom feeds and converts items to the DEAL INGEST schema.
- POSTs each item to your running FastAPI endpoint /webhooks/deal-ingest.

You can later:
- Replace fetch_rss() with Apify actors, paid data providers, or official APIs.
"""

import asyncio
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from dateutil import parser as dateparser
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


@dataclass
class Source:
    source: str
    category: str
    url: str
    country: Optional[str] = None
    region: Optional[str] = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


async def load_sources_from_env() -> List[Source]:
    raw = os.getenv("DEAL_SOURCES_JSON", "[]")
    try:
        data = json.loads(raw)
    except Exception:
        data = []
    out: List[Source] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url:
            continue
        out.append(
            Source(
                source=item.get("source", "rss"),
                category=item.get("category", "wholesale"),
                url=url,
                country=item.get("country"),
                region=item.get("region"),
            )
        )
    return out


async def load_sources_from_db(database_url: str) -> List[Source]:
    # expects DATABASE_URL like postgresql://... (sync). Convert to asyncpg.
    async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(async_url, pool_pre_ping=True)
    try:
        async with engine.begin() as conn:
            rows = (
                await conn.execute(
                    text(
                        """
                        select source, category, url, country, region
                        from deal_sources
                        where is_enabled = true
                        """
                    )
                )
            ).mappings().all()
        return [Source(**dict(r)) for r in rows]
    finally:
        await engine.dispose()


async def fetch_rss(client: httpx.AsyncClient, url: str) -> List[Dict[str, Any]]:
    # We avoid adding a full RSS parser dependency; this is a tiny XML grab
    # and will work for simple feeds. For complex feeds, use feedparser.
    resp = await client.get(url, timeout=30)
    resp.raise_for_status()
    xml = resp.text

    # ultra-minimal: extract <item> blocks and pull title/link/description/pubDate
    items: List[Dict[str, Any]] = []
    parts = xml.split("<item")
    for p in parts[1:]:
        block = p.split("</item>")[0]
        def _tag(tag: str) -> Optional[str]:
            start = block.find(f"<{tag}")
            if start == -1:
                return None
            start = block.find(">", start)
            if start == -1:
                return None
            end = block.find(f"</{tag}>", start)
            if end == -1:
                return None
            return block[start+1:end].strip().lstrip(">")

        title = _tag("title")
        link = _tag("link")
        desc = _tag("description")
        pub = _tag("pubDate") or _tag("updated")
        posted_at = None
        if pub:
            try:
                posted_at = dateparser.parse(pub).astimezone(timezone.utc).isoformat()
            except Exception:
                posted_at = None

        if not (title or link):
            continue
        items.append(
            {
                "title": title,
                "source_url": link,
                "description": desc,
                "posted_at": posted_at,
            }
        )

    return items


async def post_deal(client: httpx.AsyncClient, ingest_url: str, payload: Dict[str, Any]) -> None:
    r = await client.post(ingest_url, json=payload, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Ingest failed {r.status_code}: {r.text[:200]}")


async def run_once() -> None:
    base_url = os.getenv("VORTEXAI_BASE_URL", "http://localhost:8000").rstrip("/")
    ingest_url = f"{base_url}/webhooks/deal-ingest"

    sources: List[Source] = await load_sources_from_env()

    db = os.getenv("DATABASE_URL")
    if db:
        try:
            sources_db = await load_sources_from_db(db)
            if sources_db:
                sources = sources_db
        except Exception:
            pass

    if not sources:
        print("No sources configured. Set DEAL_SOURCES_JSON or add rows to deal_sources.")
        return

    async with httpx.AsyncClient(headers={"User-Agent": "VortexAI-Scraper/1.0"}) as client:
        for s in sources:
            if s.source.lower() not in {"rss", "atom", "feed"}:
                print(f"Skipping source '{s.source}' (starter supports rss only): {s.url}")
                continue

            try:
                items = await fetch_rss(client, s.url)
            except Exception as e:
                print(f"Fetch failed: {s.url} -> {e}")
                continue

            for it in items:
                seed = (it.get("source_url") or "") + "|" + (it.get("title") or "")
                payload = {
                    "category": s.category,
                    "source": s.source,
                    "source_url": it.get("source_url"),
                    "source_uid": _uid(seed),
                    "title": it.get("title"),
                    "description": it.get("description"),
                    "price": None,
                    "currency": None,
                    "country": s.country,
                    "region": s.region,
                    "city": None,
                    "postal_code": None,
                    "posted_at": it.get("posted_at") or _now().isoformat(),
                    "images": [],
                    "raw": {"rss": True},
                }
                try:
                    await post_deal(client, ingest_url, payload)
                    print("Ingested:", payload.get("title"))
                except Exception as e:
                    print("Ingest error:", e)


async def main() -> None:
    interval_sec = int(os.getenv("SCRAPE_INTERVAL_SEC", "600"))
    while True:
        await run_once()
        await asyncio.sleep(interval_sec)


if __name__ == "__main__":
    asyncio.run(main())
