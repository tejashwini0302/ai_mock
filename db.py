"""
Database layer: user accounts + analysis history.

DATABASE_URL (recommended: free Postgres from neon.tech or supabase.com) gives
real, permanent storage. Without it, falls back to a local SQLite file, which
works for local testing but resets on Render restarts.
"""

import os
import bcrypt
from datetime import datetime, timezone

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./career_agent.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Analysis(Base):
    __tablename__ = "analyses"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, index=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    role = Column(String, index=True)
    github_username = Column(String, index=True)
    ats_score = Column(Integer)
    ats_score_method = Column(String)
    github_score = Column(Integer)
    placement_readiness = Column(Integer)
    result_json = Column(Text)  # full JSON payload, so the result page can be reloaded/downloaded anytime


def init_db():
    Base.metadata.create_all(bind=engine)


# ---------- Users ----------

def create_user(username: str, password: str):
    """Returns the new user's id, or None if the username is already taken."""
    session = SessionLocal()
    try:
        if session.query(User).filter(User.username == username).first():
            return None
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = User(username=username, password_hash=password_hash)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id
    finally:
        session.close()


def verify_login(username: str, password: str):
    """Returns the user's id if the password is correct, else None."""
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.username == username).first()
        if not user:
            return None
        if bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            return user.id
        return None
    finally:
        session.close()


def get_username(user_id: int):
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.id == user_id).first()
        return user.username if user else None
    finally:
        session.close()


# ---------- Analyses ----------

def save_analysis(user_id, role, github_username, ats_score, ats_score_method,
                   github_score, placement_readiness, result_json) -> int:
    """Saves an analysis and returns its new id (used to build the /result/<id> link)."""
    session = SessionLocal()
    try:
        row = Analysis(
            user_id=user_id, role=role, github_username=github_username,
            ats_score=ats_score, ats_score_method=ats_score_method,
            github_score=github_score, placement_readiness=placement_readiness,
            result_json=result_json
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id
    finally:
        session.close()


def get_analysis(analysis_id: int):
    session = SessionLocal()
    try:
        row = session.query(Analysis).filter(Analysis.id == analysis_id).first()
        if not row:
            return None
        return {"id": row.id, "user_id": row.user_id, "result_json": row.result_json,
                "created_at": row.created_at.isoformat(), "role": row.role}
    finally:
        session.close()


def get_history(user_id: int, limit: int = 10):
    session = SessionLocal()
    try:
        rows = (
            session.query(Analysis)
            .filter(Analysis.user_id == user_id)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            {"id": r.id, "created_at": r.created_at.isoformat(), "role": r.role,
             "ats_score": r.ats_score, "github_score": r.github_score,
             "placement_readiness": r.placement_readiness}
            for r in rows
        ]
    finally:
        session.close()
