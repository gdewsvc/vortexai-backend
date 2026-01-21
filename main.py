import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from pydantic_settings import BaseSettings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

APP_NAME = "VortexAI API"


# ======================
# Settings
# ======================
class Settings(BaseSettings):
    database_url: str = Field(..., alias="DATABASE_URL")
    openai_api_key: Optional[str] = Field(None, alias="OPENAI_API_KEY")
    admin_email: str = Field(..., alias="ADMIN_EMAIL")

    class Config:
        populate_by_name = True


settings = Settings()

_db_url = settings.database_url
if _db_url.startswith("postgres://"):
    _db_url = _db_url.replace("postgres://", "postgresql+asyncpg://", 1)
elif _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine: AsyncEngine = create_async_engine(_db_url, pool_pre_ping=True)

client_openai = OpenAI(api_key=settings.openai_api_key) if (OpenAI and settings.openai_api_key) else None

app = FastAPI(title=APP_NAME, version="1.0.0")

# ======================
# CORS FIX (IMPORTANT)
# ======================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================
# Models
# ======================
class SellerSubmission(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    city: Optional[str] = None
    asset_type: str
    price: Optional[float] = None
    currency: Optional[str] = None
    description: Optional[str] = None
    images: List[str] = []
    source_url: Optional[str] = None


class BuyerRegistration(BaseModel):
    name: str
    email: EmailStr
    phone: Optional[str] = None
    countries: List[str] = []
    regions: List[str] = []
    categories: List[str] = []
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    notes: Optional[str] = None


# ======================
# Helpers
# ======================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _json(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False)


async def db_exec(query: str, params: Dict[str, Any]) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(query), params)


# ======================
# Routes
# ======================
@app.get("/health")
async def health():
    return {"ok": True, "app": APP_NAME, "time": now_utc().isoformat()}


@app.post("/webhooks/seller")
async def seller_webhook(payload: SellerSubmission):

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

    return {"ok": True}
