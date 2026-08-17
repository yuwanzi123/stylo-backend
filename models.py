import uuid
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./stylo.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class ClosetItem(Base):
    __tablename__ = "closet_items"

    id            = Column(Integer, primary_key=True, index=True, autoincrement=True)
    filename      = Column(String, nullable=False)
    image_url     = Column(String, nullable=False)
    description   = Column(String, nullable=True)
    category      = Column(String, nullable=True)  # "top" | "bottom" | "outerwear" | "shoes"
    attributes    = Column(String, nullable=True)   # JSON string, e.g. {"color": "...", "style": "...", "season": "..."}
    embedding     = Column(String, nullable=True)   # JSON string, float array from text-embedding-3-small (1536-dim)
    source_task_id = Column(String, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)


class Outfit(Base):
    __tablename__ = "outfits"

    id                    = Column(String, primary_key=True, index=True, default=lambda: uuid.uuid4().hex)
    user_id               = Column(String, nullable=False, index=True)
    item_ids              = Column(String, nullable=False)  # JSON string array of ClosetItem ids
    composite_image_path  = Column(String, nullable=False)
    caption               = Column(String, nullable=True)
    created_at             = Column(DateTime, default=datetime.utcnow, nullable=False)
    parent_outfit_id       = Column(String, nullable=True)  # set when this outfit is a tweak of a previous one


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id            = Column(String, primary_key=True, index=True, default=lambda: uuid.uuid4().hex)
    user_id       = Column(String, nullable=False, index=True)
    role          = Column(String, nullable=False)          # "user" | "assistant"
    message_type  = Column(String, nullable=False, default="text")  # "text" | "outfit_card"
    content       = Column(String, nullable=True)
    outfit_id     = Column(String, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)


class DailyConstraint(Base):
    """Scene-specific constraint extracted from a single user message (e.g. "today
    I'm playing golf, only want short sleeves"). Scoped to the day it was said —
    callers filter by created_at to enforce same-day-only relevance; rows are never
    deleted, old ones just stop being queried."""
    __tablename__ = "daily_constraints"

    id              = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id         = Column(String, nullable=False, index=True)
    constraint_text = Column(String, nullable=False)
    created_at      = Column(DateTime, default=datetime.utcnow, nullable=False)


class StandingPreference(Base):
    """Durable preference extracted from a user message (e.g. "I don't wear high
    heels"), independent of any date. Accumulates until explicitly removed via the
    natural-language removal flow (stage 4)."""
    __tablename__ = "standing_preferences"

    id               = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id          = Column(String, nullable=False, index=True)
    preference_text  = Column(String, nullable=False)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)


def init_db():
    Base.metadata.create_all(bind=engine)
