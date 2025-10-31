# db/database.py

import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from db.models import (
    User, SolarSystem, Stargate, MarketOrder,
    PublicContract, Structure, MarketStructure,
    Character, Asset, Blueprint, IndustryJob,
    PersonalBookmark, Skill,SkillQueue,
    WalletBalance, WalletJournal,
    WalletTransaction, PublicBase, PrivateBase
)

# ──────── Globals ─────────────────────────────────────────────────────────────
logger = logging.getLogger(__name__)

PRIVATE_DATA_FOLDER = os.getenv("EVE_PRIVATE_DATABASE_FOLDER", "_privateData/")
PUBLIC_DATABASE_FILE = os.getenv("EVE_PUBLIC_DATABASE_FILE", "_publicData/public.db")

# Engines and session factories
_public_engine = None
_PublicSession = None
_private_engines = {}
_PrivateSessions = {}

# ──────── Initialization ──────────────────────────────────────────────────────
def initialize_public_database():
    """
    Initialize engine and tables for public DB.
    """
    global _public_engine, _PublicSession
    if _public_engine is None:
        abs_path = os.path.abspath(PUBLIC_DATABASE_FILE).replace("\\", "/")
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        _public_engine = create_engine(
            f"sqlite:///{abs_path}",
            future=True,
            connect_args={"timeout": 30, "check_same_thread": False},
            pool_pre_ping=True,
        )
        PublicBase.metadata.create_all(_public_engine)
        logger.info(f"Initialized public database at {abs_path}")
        _PublicSession = sessionmaker(bind=_public_engine)
    return _public_engine


def initialize_private_database(owner_id: int):
    """
    Initialize engine and tables for a private DB for given owner.
    """
    global _private_engines, _PrivateSessions
    toon_folder = os.path.join(PRIVATE_DATA_FOLDER, str(owner_id))
    os.makedirs(toon_folder, exist_ok=True)
    db_path = os.path.join(toon_folder, f"{owner_id}.db")
    abs_path = os.path.abspath(db_path).replace("\\", "/")
    db_url = f"sqlite:///{abs_path}"
    if owner_id not in _private_engines:
        engine = create_engine(
            db_url,
            echo=False,
            future=True,
            connect_args={"timeout": 30, "check_same_thread": False},
            pool_pre_ping=True,
        )
        PrivateBase.metadata.create_all(engine)
        logger.info(f"Initialized private database for owner {owner_id} at {abs_path}")
        _private_engines[owner_id] = engine
        _PrivateSessions[owner_id] = sessionmaker(bind=engine)
    return _private_engines[owner_id]

# ──────── Sessions ─────────────────────────────────────────────────────────────
def get_public_session():
    """Return a new session for public DB."""
    global _PublicSession
    if _PublicSession is None:
        initialize_public_database()
    return _PublicSession()


def get_private_session(owner_id: int):
    """Return a new session for private DB of owner_id."""
    if owner_id not in _PrivateSessions:
        initialize_private_database(owner_id)
    return _PrivateSessions[owner_id]()
