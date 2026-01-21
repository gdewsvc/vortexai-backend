from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

APP_NAME = "VortexAI API"
APP_VERSION = "1.0.0"


# =====================
# Settings
# =====================

class Settings(BaseSettings):
    database_url: str = Field(..., alias="DATABASE_URL")
    admin_email: EmailStr = Field(..., alias="ADMIN_EMAIL")
    frontend_origins: Optional[str] = Field("", alias="FRONTEND_URL")

    class Config:
        populate_by_name = True
        env_file = None


settings = Settings()


# =====================
# Database
# =====================

_db_url = settings.database_url
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine: AsyncEngine = create_async_engine(_db_url, pool_pre_ping=True)


# =====================
# App
# =====================

app = FastAPI(title=APP_NAME, version=APP_VERSION)

raw_origins = settings.frontend_origins or "*"
allow_origins = ["*"] if raw_origins.strip() in ("", "*") else [o.strip() for o in raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================
# Models
# =====================

class BuyerSubmission(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    countries: List[str] = []
    regions: List[str] = []
    categories: List[str] = []
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    notes: Optional[str] = None


class SellerSubmission(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    country: str
    region: Optional[str] = None
    city: Optional[str] = None
    asset_type: str
    price: Optional[float] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = []
    source_url: Optional[str] = None


# =====================
# Helpers
# =====================

def now_utc_iso():
    return datetime.now(timezone.utc).isoformat()


async def db_exec(query: str, params: Dict[str, Any]):
    async with engine.begin() as conn:
        await conn.execute(text(query), params)


async def db_fetchall(query: str, params: Dict[str, Any]):
    async with engine.begin() as conn:
        res = await conn.execute(text(query), params)
        return [dict(r) for r in res.mappings().all()]


def _check_admin(x_admin_email: Optional[str]):
    if not x_admin_email or x_admin_email.lower() != settings.admin_email.lower():
        raise HTTPException(status_code=401, detail="unauthorized")


# =====================
# Routes
# =====================

@app.get("/health")
async def health():
    return {"ok": True, "time": now_utc_iso()}


@app.post("/webhooks/buyer")
async def buyer_webhook(payload: BuyerSubmission):
    await db_exec("""
        INSERT INTO buyers (name,email,phone,countries,regions,categories,budget_min,budget_max,notes,created_at)
        VALUES (:name,:email,:phone,:countries,:regions,:categories,:budget_min,:budget_max,:notes,now())
    """, payload.model_dump())
    return {"ok": True}


@app.post("/webhooks/seller")
async def seller_webhook(payload: SellerSubmission):
    await db_exec("""
        INSERT INTO sellers (name,email,phone,country,region,city,asset_type,price,currency,description,images,source_url,created_at)
        VALUES (:name,:email,:phone,:country,:region,:city,:asset_type,:price,:currency,:description,:images,:source_url,now())
    """, payload.model_dump())
    return {"ok": True}


@app.get("/admin/stats")
async def admin_stats(x_admin_email: Optional[str] = Header(None, alias="X-Admin-Email")):
    _check_admin(x_admin_email)
    rows = await db_fetchall("SELECT count(*) as buyers_count FROM buyers", {})
    return rows[0] if rows else {}


# =====================
# Twilio SMS Webhook
# =====================

@app.post("/webhooks/sms")
async def sms_webhook(request: Request):
    form = await request.form()

    from_number = form.get("From")
    to_number = form.get("To")
    body = form.get("Body")

    print("📩 SMS received:", from_number, "→", body)

    return {"ok": True}
