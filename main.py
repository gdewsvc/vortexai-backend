import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

import httpx

APP_NAME = "VortexAI API"


class Settings(BaseSettings):
    database_url: str = Field(..., alias="DATABASE_URL")
    openai_api_key: Optional[str] = Field(None, alias="OPENAI_API_KEY")
    admin_email: str = Field(..., alias="ADMIN_EMAIL")

    # Optional SMTP (if not set, system logs notifications into DB only)
    smtp_host: Optional[str] = Field(None, alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(None, alias="SMTP_USER")
    smtp_pass: Optional[str] = Field(None, alias="SMTP_PASS")
    smtp_from: Optional[str] = Field(None, alias="SMTP_FROM")

    # Matching threshold
    notify_threshold: float = Field(0.65, alias="NOTIFY_THRESHOLD")

    class Config:
        populate_by_name = True


settings = Settings()

# SQLAlchemy async engine (convert postgres:// to postgresql+asyncpg://)
_db_url = settings.database_url
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine: AsyncEngine = create_async_engine(_db_url, pool_pre_ping=True)

client_openai = OpenAI(api_key=settings.openai_api_key) if (OpenAI and settings.openai_api_key) else None

app = FastAPI(title=APP_NAME, version="1.0.0")


# -----------------------------
# Models (payload schemas)
# -----------------------------
class SellerSubmission(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    asset_type: str = Field(..., description="real_estate|car|wholesale|luxury|equipment")
    price: Optional[float] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None


class BuyerRegistration(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    countries: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    notes: Optional[str] = None


class DealIngest(BaseModel):
    category: str = Field(..., description="real_estate|car|wholesale|luxury|equipment")
    source: Optional[str] = None
    source_url: str
    source_uid: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    posted_at: Optional[datetime] = None
    images: List[str] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)


# -----------------------------
# Utility helpers
# -----------------------------
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


async def db_exec(query: str, params: Dict[str, Any]) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(query), params)


async def db_fetchone(query: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    async with engine.begin() as conn:
        res = await conn.execute(text(query), params)
        row = res.mappings().first()
        return dict(row) if row else None


async def db_fetchall(query: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    async with engine.begin() as conn:
        res = await conn.execute(text(query), params)
        return [dict(r) for r in res.mappings().all()]


def safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


def normalize_str(x: Optional[str]) -> str:
    return (x or "").strip().lower()


# -----------------------------
# Scoring (AI + fallback)
# -----------------------------
async def score_deal_ai(deal: DealIngest) -> Tuple[float, str]:
    """Return (score 0-1, reason). Uses OpenAI if configured, otherwise heuristic."""

    # Fallback heuristic (always available)
    def heuristic() -> Tuple[float, str]:
        score = 0.30
        reasons = []
        title = normalize_str(deal.title)
        desc = normalize_str(deal.description)
        text_blob = f"{title} {desc}"

        # Deal urgency keywords
        for kw in ["urgent", "must sell", "motivated", "discount", "below market", "wholesale", "liquidation"]:
            if kw in text_blob:
                score += 0.08
                reasons.append(f"keyword:{kw}")

        # Price present
        if deal.price and deal.price > 0:
            score += 0.10
            reasons.append("price_present")

        # Recency
        if deal.posted_at:
            age_hours = max(0.0, (now_utc() - deal.posted_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600)
            if age_hours <= 24:
                score += 0.10
                reasons.append("fresh_<=24h")
            elif age_hours <= 72:
                score += 0.06
                reasons.append("fresh_<=72h")

        score = max(0.0, min(1.0, score))
        return score, ", ".join(reasons) if reasons else "heuristic"

    if not client_openai:
        return heuristic()

    try:
        payload = {
            "category": deal.category,
            "title": deal.title,
            "description": deal.description,
            "price": deal.price,
            "country": deal.country,
            "region": deal.region,
            "city": deal.city,
            "source_url": deal.source_url,
        }

        prompt = (
            "You are a deal-quality scoring assistant for an investment marketplace. "
            "Score how attractive this listing is as a potential DEAL for buyers. "
            "Output strict JSON with keys: score (number 0..1), reason (short string). "
            "Higher score for urgency, discount/wholesale/liquidation, strong resale margin hints, and very recent posts. "
            "Be conservative if uncertain.\n\nListing JSON:\n" + json.dumps(payload, ensure_ascii=False)
        )

        resp = client_openai.responses.create(
            model="gpt-4o-mini",
            input=prompt,
            response_format={"type": "json_object"},
        )
        txt = resp.output_text
        data = json.loads(txt)
        score = float(data.get("score", 0.0))
        reason = str(data.get("reason", "ai"))
        score = max(0.0, min(1.0, score))
        return score, reason
    except Exception:
        return heuristic()


# -----------------------------
# Matching algorithm
# -----------------------------
def compute_match(deal_row: Dict[str, Any], buyer_row: Dict[str, Any]) -> Tuple[float, Dict[str, Any]]:
    """Algorithm: budget (40%) + location (30%) + category (20%) + recency (10%)."""

    weights = {"budget": 0.40, "location": 0.30, "category": 0.20, "recency": 0.10}

    # Category
    buyer_cats = set((buyer_row.get("categories") or []))
    deal_cat = deal_row.get("category")
    cat_score = 1.0 if deal_cat in buyer_cats else 0.0

    # Location
    buyer_countries = set((buyer_row.get("countries") or []))
    buyer_regions = set((buyer_row.get("regions") or []))
    deal_country = deal_row.get("country")
    deal_region = deal_row.get("region")
    loc = 0.0
    if deal_country and deal_country in buyer_countries:
        loc += 0.6
    if deal_region and deal_region in buyer_regions:
        loc += 0.4
    location_score = min(1.0, loc)

    # Budget
    price = safe_float(deal_row.get("price"))
    bmin = safe_float(buyer_row.get("budget_min"))
    bmax = safe_float(buyer_row.get("budget_max"))
    budget_score = 0.3
    if price and bmin is not None and bmax is not None and bmin <= price <= bmax:
        budget_score = 1.0
    elif price and bmax is not None and price <= bmax:
        budget_score = 0.6

    # Recency
    recency_score = 0.5
    posted_at = deal_row.get("posted_at")
    if posted_at:
        if isinstance(posted_at, str):
            try:
                posted_at = datetime.fromisoformat(posted_at.replace("Z", "+00:00"))
            except Exception:
                posted_at = None
    if posted_at:
        age_hours = max(0.0, (now_utc() - posted_at).total_seconds() / 3600)
        if age_hours <= 24:
            recency_score = 1.0
        elif age_hours <= 72:
            recency_score = 0.8
        elif age_hours <= 168:
            recency_score = 0.6
        else:
            recency_score = 0.4

    final = (
        weights["budget"] * budget_score
        + weights["location"] * location_score
        + weights["category"] * cat_score
        + weights["recency"] * recency_score
    )

    breakdown = {
        "budget": budget_score,
        "location": location_score,
        "category": cat_score,
        "recency": recency_score,
        "weights": weights,
    }

    return float(max(0.0, min(1.0, final))), breakdown


# -----------------------------
# Notifications
# -----------------------------
async def enqueue_notification(kind: str, to_email: str, subject: str, body: str,
                               deal_id: Optional[str] = None, buyer_id: Optional[str] = None) -> None:
    await db_exec(
        """
        insert into notifications(kind, to_email, subject, body, status, related_deal_id, related_buyer_id, created_at)
        values (:kind, :to_email, :subject, :body, 'queued', :deal_id, :buyer_id, now())
        """,
        {
            "kind": kind,
            "to_email": to_email,
            "subject": subject,
            "body": body,
            "deal_id": deal_id,
            "buyer_id": buyer_id,
        },
    )


async def send_queued_notifications(limit: int = 25) -> int:
    """If SMTP is configured, send queued emails and mark as sent."""
    if not (settings.smtp_host and settings.smtp_user and settings.smtp_pass and settings.smtp_from):
        return 0

    # Minimal SMTP sender to avoid extra deps
    import smtplib
    from email.message import EmailMessage

    rows = await db_fetchall(
        """
        select notification_id, to_email, subject, body
        from notifications
        where status = 'queued'
        order by created_at asc
        limit :limit
        """,
        {"limit": limit},
    )
    if not rows:
        return 0

    sent = 0
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as s:
        s.starttls()
        s.login(settings.smtp_user, settings.smtp_pass)
        for r in rows:
            msg = EmailMessage()
            msg["From"] = settings.smtp_from
            msg["To"] = r["to_email"]
            msg["Subject"] = r["subject"]
            msg.set_content(r["body"])
            s.send_message(msg)
            await db_exec(
                """
                update notifications set status='sent', sent_at=now(), provider='smtp'
                where notification_id = :id
                """,
                {"id": r["notification_id"]},
            )
            sent += 1
    return sent


# -----------------------------
# Routes
# -----------------------------
@app.get("/health")
async def health():
    return {"ok": True, "app": APP_NAME, "time": now_utc().isoformat()}


@app.post("/webhooks/seller")
async def seller_webhook(payload: SellerSubmission):
    if payload.asset_type not in {"real_estate", "car", "wholesale", "luxury", "equipment"}:
        raise HTTPException(400, "asset_type must be real_estate|car|wholesale|luxury|equipment")

    await db_exec(
        """
        insert into sellers(name, email, phone, country, region, city, asset_type, ask_price, currency, description, images, source_url)
        values(:name,:email,:phone,:country,:region,:city,:asset_type,:ask_price,:currency,:description,:images::jsonb,:source_url)
        """,
        {
            "name": payload.name,
            "email": str(payload.email),
            "phone": payload.phone,
            "country": payload.country,
            "region": payload.region,
            "city": payload.city,
            "asset_type": payload.asset_type,
            "ask_price": payload.price,
            "currency": payload.currency,
            "description": payload.description,
            "images": _json(payload.images),
            "source_url": payload.source_url,
        },
    )

    await db_exec(
        "insert into audit_events(event_type, entity_type, payload) values('seller_intake','seller',:p::jsonb)",
        {"p": _json(payload.model_dump())},
    )

    return {"ok": True}


@app.post("/webhooks/buyer")
async def buyer_webhook(payload: BuyerRegistration):
    await db_exec(
        """
        insert into buyers(name, email, phone, countries, regions, categories, budget_min, budget_max, notes)
        values(:name,:email,:phone,:countries::jsonb,:regions::jsonb,:categories::jsonb,:budget_min,:budget_max,:notes)
        """,
        {
            "name": payload.name,
            "email": str(payload.email),
            "phone": payload.phone,
            "countries": _json(payload.countries),
            "regions": _json(payload.regions),
            "categories": _json(payload.categories),
            "budget_min": payload.budget_min,
            "budget_max": payload.budget_max,
            "notes": payload.notes,
        },
    )

    await db_exec(
        "insert into audit_events(event_type, entity_type, payload) values('buyer_intake','buyer',:p::jsonb)",
        {"p": _json(payload.model_dump())},
    )

    return {"ok": True}


@app.post("/webhooks/deal-ingest")
async def deal_ingest_webhook(payload: DealIngest):
    if payload.category not in {"real_estate", "car", "wholesale", "luxury", "equipment"}:
        raise HTTPException(400, "category must be real_estate|car|wholesale|luxury|equipment")

    if not payload.source_uid:
        payload.source_uid = str(abs(hash(payload.source_url)))

    score, reason = await score_deal_ai(payload)

    # Upsert deal (unique on (source, source_uid))
    await db_exec(
        """
        insert into deals(category, source, source_url, source_uid, title, description, price, currency, country, region, city,
                          postal_code, posted_at, images, raw, ai_score, ai_reason)
        values(:category,:source,:source_url,:source_uid,:title,:description,:price,:currency,:country,:region,:city,
               :postal_code,:posted_at,:images::jsonb,:raw::jsonb,:ai_score,:ai_reason)
        on conflict (source, source_uid) do update set
          title=excluded.title,
          description=excluded.description,
          price=excluded.price,
          currency=excluded.currency,
          country=excluded.country,
          region=excluded.region,
          city=excluded.city,
          postal_code=excluded.postal_code,
          posted_at=excluded.posted_at,
          images=excluded.images,
          raw=excluded.raw,
          ai_score=excluded.ai_score,
          ai_reason=excluded.ai_reason
        """,
        {
            "category": payload.category,
            "source": payload.source or "unknown",
            "source_url": payload.source_url,
            "source_uid": payload.source_uid,
            "title": payload.title,
            "description": payload.description,
            "price": payload.price,
            "currency": payload.currency,
            "country": payload.country,
            "region": payload.region,
            "city": payload.city,
            "postal_code": payload.postal_code,
            "posted_at": payload.posted_at,
            "images": _json(payload.images),
            "raw": _json(payload.raw),
            "ai_score": score,
            "ai_reason": reason,
        },
    )

    # Fetch deal_id
    deal_row = await db_fetchone(
        "select * from deals where source = :source and source_uid = :uid",
        {"source": payload.source or "unknown", "uid": payload.source_uid},
    )
    if not deal_row:
        raise HTTPException(500, "Deal upsert failed")

    deal_id = str(deal_row["deal_id"])

    # Admin notification
    subject = f"New Deal: {payload.title or 'Listing'}"
    body = (
        f"Title: {payload.title}\n"
        f"Category: {payload.category}\n"
        f"Price: {payload.price} {payload.currency or ''}\n"
        f"Location: {payload.city or ''}, {payload.region or ''}, {payload.country or ''}\n"
        f"AI Score: {score:.2f}\n"
        f"Reason: {reason}\n"
        f"URL: {payload.source_url}\n"
    )
    await enqueue_notification("admin", settings.admin_email, subject, body, deal_id=deal_id)

    # Match buyers
    buyers = await db_fetchall(
        "select buyer_id, email, countries, regions, categories, budget_min, budget_max from buyers where status='active'",
        {},
    )

    matched: List[Dict[str, Any]] = []
    for b in buyers:
        # jsonb comes back as python objects in asyncpg
        ms, breakdown = compute_match(deal_row, b)
        if ms <= 0:
            continue
        try:
            await db_exec(
                """
                insert into matches(deal_id, buyer_id, match_score, match_breakdown)
                values(:deal_id,:buyer_id,:score,:breakdown::jsonb)
                on conflict (deal_id, buyer_id) do update set
                  match_score=excluded.match_score,
                  match_breakdown=excluded.match_breakdown
                """,
                {
                    "deal_id": deal_id,
                    "buyer_id": str(b["buyer_id"]),
                    "score": ms,
                    "breakdown": _json(breakdown),
                },
            )
        except Exception:
            pass

        if score >= settings.notify_threshold and ms >= settings.notify_threshold:
            buyer_subject = f"Deal Match ({ms:.2f}): {payload.title or 'Listing'}"
            buyer_body = body + f"\nMatch Score: {ms:.2f}\n"
            await enqueue_notification("buyer", str(b["email"]), buyer_subject, buyer_body, deal_id=deal_id, buyer_id=str(b["buyer_id"]))
            matched.append({"buyer_id": str(b["buyer_id"]), "email": str(b["email"]), "match_score": ms})

    await db_exec(
        "insert into audit_events(event_type, entity_type, entity_id, payload) values('deal_ingest','deal',:id,:p::jsonb)",
        {"id": deal_id, "p": _json({"ai_score": score, "ai_reason": reason, "matched": matched[:50]})},
    )

    # Optionally send emails immediately (if SMTP configured)
    sent = await send_queued_notifications(limit=50)

    return {"ok": True, "deal_id": deal_id, "ai_score": score, "matched_notified": len(matched), "emails_sent_now": sent}


@app.post("/admin/send-queued")
async def admin_send_queued(limit: int = 25):
    sent = await send_queued_notifications(limit=limit)
    return {"ok": True, "sent": sent}
