"""
database.py — PostgreSQL connection setup
-----------------------------------------
SQLAlchemy is the "translator" between Python and Postgres.
It lets us define tables as Python classes and query them with Python
instead of writing raw SQL.

How it works:
  1. We create an "engine" using our DATABASE_URL from .env
  2. We create a "SessionLocal" — each API request gets its own DB session
  3. We define a "Base" class that our table models will inherit from
  4. The get_db() function is a FastAPI "dependency" — it automatically
     opens a DB session for each request and closes it when done
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()  # reads your .env file

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL not set in .env file")

# The engine is the actual connection to Postgres.
# pool_pre_ping checks each connection before use so dead connections (idle
# timeouts on Railway/Supabase) get recycled instead of failing the request.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Each request gets its own session (like a temporary workspace with the DB)
# autocommit=False means we manually commit changes (safer)
# autoflush=False means changes aren't written until we say so
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# All our table models will inherit from this Base
Base = declarative_base()


def get_db():
    """
    FastAPI dependency --> provides db session per req:
    
    Usage in a route:
        @app.get("/coaches")
        def get_coaches(db: Session = Depends(get_db)):
            ...
    
    The 'finally' block ensures the session always closes, even if there's an error.
    """
    db = SessionLocal()
    try:
        yield db  # 'yield' makes this a generator — FastAPI handles the lifecycle
    finally:
        db.close()
