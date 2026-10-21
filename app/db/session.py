"""SQLAlchemy database connection for the Smart Farm runtime application."""

import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

load_dotenv(".env")

DATABASE_URL = os.environ.get("SMARTFARM_DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("SMARTFARM_DATABASE_URL is not configured")

engine: Engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=1800,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


def get_db():
    """Yield a database session and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
