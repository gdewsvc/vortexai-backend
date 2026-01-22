import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime

# --------------------
# DATABASE
# --------------------

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL environment variable is not set")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# --------------------
# MODELS
# --------------------

class Buyer(Base):
    __tablename__ = "buyers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String)
    phone = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

class Seller(Base):
    __tablename__ = "sellers"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String)
    phone = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables automatically
Base.metadata.create_all(bind=engine)

# --------------------
# APP
# --------------------

app = FastAPI()

# --------------------
# CORS
# --------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://vortexai-2026.netlify.app",
        "http://localhost:3000",
        "*"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------
# ROUTES
# --------------------

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/buyer")
def create_buyer(data: dict):
    db = SessionLocal()
    buyer = Buyer(
        name=data.get("name"),
        email=data.get("email"),
        phone=data.get("phone"),
    )
    db.add(buyer)
    db.commit()
    db.close()
    return {"success": True}

@app.post("/seller")
def create_seller(data: dict):
    db = SessionLocal()
    seller = Seller(
        name=data.get("name"),
        email=data.get("email"),
        phone=data.get("phone"),
    )
    db.add(seller)
    db.commit()
    db.close()
    return {"success": True}
