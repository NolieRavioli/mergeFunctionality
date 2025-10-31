# db/models.py

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    JSON,
    BigInteger,
    PrimaryKeyConstraint,
)
from sqlalchemy.orm import declarative_base
import datetime

# ──────── Base Declarative Classes ───────────────────────────────────────────────
PublicBase = declarative_base()
PrivateBase = declarative_base()

# ──────── Public Database Models ──────────────────────────────────────────────────

class User(PublicBase):
    __tablename__   = "users"
    owner_id        = Column(Integer, index=True)
    character_id    = Column(Integer, primary_key=True)

class SolarSystem(PublicBase):
    __tablename__       = "systems"
    system_id           = Column(Integer, primary_key=True)
    constellation_id    = Column(Integer)
    region_id           = Column(Integer, index=True)
    security            = Column(Float)
    owner_id            = Column(Integer, index=True, nullable=True)    #corporation_id or alliance_id
    faction_id          = Column(Integer, nullable=True)
    system_name         = Column(String)
    region_name         = Column(String)
    planets             = Column(JSON, nullable=True)   # List of planet IDs
    moons               = Column(JSON, nullable=True)   # List of moon IDs
    stargates           = Column(JSON, nullable=True)   # List of stargate IDs
    neighbors           = Column(JSON, nullable=True)   # List of connected system IDs
    
class Stargate(PublicBase):
    __tablename__           = "stargates"
    stargate_id             = Column(Integer, primary_key=True)
    owner_id                = Column(Integer, nullable=True)
    type_id                 = Column(Integer)
    system_id               = Column(Integer)
    destination_gate_id     = Column(Integer)
    destination_system_id   = Column(Integer)
    position                = Column(JSON)      # [x, y, z]

class Alliances(PublicBase):
    __tablename__           = "Alliances"
    alliance_id             = Column(Integer, primary_key=True)
    name                    = Column(String)
    creator_corporation_id  = Column(Integer)
    creator_id              = Column(Integer)
    date_founded            = Column(DateTime)
    executor_corporation_id = Column(Integer)
    ticker                  = Column(String)
    corporations            = Column(JSON)

class Structure(PublicBase):
    __tablename__   = "structures"
    structure_id    = Column(Integer, primary_key=True)
    name            = Column(String, nullable=True)
    solar_system_id = Column(Integer, index=True)
    region_id       = Column(Integer, index=True)
    owner_id        = Column(Integer, nullable=True)
    type_id         = Column(Integer, nullable=True)
    position        = Column(JSON, nullable=True)
    last_seen       = Column(DateTime, default=datetime.datetime.utcnow)

class MarketStructure(PublicBase):
    __tablename__   = "market_structures"
    structure_id    = Column(Integer, primary_key=True)
    solar_system_id = Column(Integer)
    region_id       = Column(Integer)
    owner_id        = Column(Integer, nullable=True)
    name            = Column(String, nullable=True)
    type_id         = Column(Integer, nullable=True)
    position        = Column(JSON, nullable=True)
    last_seen       = Column(DateTime, default=datetime.datetime.utcnow)

class MarketOrder(PublicBase):
    __tablename__   = "market_orders"
    order_id        = Column(Integer, primary_key=True)
    type_id         = Column(Integer)
    location_id     = Column(Integer)
    region_id       = Column(Integer)
    is_buy_order    = Column(Boolean)
    issued          = Column(DateTime)
    duration        = Column(Integer)
    price           = Column(Float)
    order_range     = Column(String)
    volume_remain   = Column(Integer)
    volume_total    = Column(Integer)
    min_volume      = Column(Integer)
    last_seen       = Column(DateTime, default=datetime.datetime.utcnow)

class PublicContract(PublicBase):
    __tablename__           = "public_contracts"
    contract_id             = Column(Integer, primary_key=True)
    region_id               = Column(Integer, index=True)
    issuer_id               = Column(Integer)
    issuer_corporation_id   = Column(Integer)
    contract_type           = Column(String)
    date_issued             = Column(DateTime)
    date_expired            = Column(DateTime)
    title                   = Column(String, nullable=True)
    volume                  = Column(Float, nullable=True)
    price                   = Column(Float, nullable=True)
    buyout                  = Column(Float, nullable=True)
    collateral              = Column(Float, nullable=True)
    reward                  = Column(Float, nullable=True)
    days_to_complete        = Column(Integer, nullable=True)
    start_location_id       = Column(Integer, nullable=True)
    end_location_id         = Column(Integer, nullable=True)
    for_corporation         = Column(Boolean, nullable=True)
    last_seen               = Column(DateTime, default=datetime.datetime.utcnow)

# ──────── Private Database Models ────────────────────────────────────────────────

class Character(PrivateBase):
    __tablename__            = "characters"
    character_id             = Column(Integer, primary_key=True)
    name                     = Column(String)
    security_status          = Column(Float, nullable=True)
    jump_fatigue_expire_date = Column(DateTime, nullable=True)
    last_jump_date           = Column(DateTime, nullable=True)
    last_update_date         = Column(DateTime, nullable=True)
    corporation_id           = Column(Integer)
    alliance_id              = Column(Integer, nullable=True)
    current_system_id        = Column(Integer, nullable=True)
    current_location_id      = Column(BigInteger, nullable=True)
    birthday                 = Column(String)
    access_token             = Column(String)
    refresh_token            = Column(String)
    expires_at               = Column(Float)
    scopes                   = Column(String)

class Asset(PrivateBase):
    __tablename__       = "assets"
    item_id             = Column(BigInteger, primary_key=True)
    character_id        = Column(Integer, index=True)
    type_id             = Column(Integer)
    is_blueprint_copy   = Column(Boolean, nullable=True)
    location_id         = Column(Integer)
    quantity            = Column(Integer)
    location_type       = Column(String)
    location_flag       = Column(Integer)

class Blueprint(PrivateBase):
    __tablename__           = "blueprints"
    item_id                 = Column(BigInteger, primary_key=True)
    character_id            = Column(Integer, index=True)
    type_id                 = Column(Integer)
    material_efficiency     = Column(Integer)
    time_efficiency         = Column(Integer)
    runs                    = Column(Integer)
    quantity                = Column(Integer)
    location_id             = Column(Integer)
    location_flag           = Column(String)

class IndustryJob(PrivateBase):
    __tablename__           = "industry_jobs"
    job_id                  = Column(BigInteger, primary_key=True)
    character_id            = Column(Integer, index=True)
    activity_id             = Column(Integer)
    blueprint_id            = Column(BigInteger)
    blueprint_location_id   = Column(BigInteger)
    blueprint_type_id       = Column(Integer)
    cost                    = Column(Float)
    duration                = Column(Integer)
    facility_id             = Column(BigInteger)
    installer_id            = Column(BigInteger)
    licensed_runs           = Column(Integer)
    output_location_id      = Column(BigInteger)
    runs                    = Column(Integer)
    status                  = Column(String)
    start_date              = Column(DateTime)
    end_date                = Column(DateTime)

class LoyaltyPoints(PrivateBase):
    __tablename__ = "loyalty_points"
    __table_args__ = (PrimaryKeyConstraint("character_id", "corporation_id"),)

    character_id = Column(Integer, index=True)
    corporation_id = Column(Integer, index=True)
    loyalty_points = Column(Integer)

class PersonalOrder(PrivateBase):
    __tablename__         = "market_orders"
    order_id        = Column(Integer, primary_key=True)
    character_id    = Column(Integer, index=True)
    type_id         = Column(Integer)
    location_id     = Column(Integer)
    region_id       = Column(Integer)
    is_buy_order    = Column(Boolean)
    issued          = Column(DateTime)
    duration        = Column(Integer)
    price           = Column(Float)
    order_range     = Column(String)
    volume_remain   = Column(Integer)
    volume_total    = Column(Integer)
    min_volume      = Column(Integer)
    last_seen       = Column(DateTime, default=datetime.datetime.utcnow)

class MoonExtraction(PrivateBase):
    __tablename__ = "moon_extractions"
    __table_args__ = (PrimaryKeyConstraint("structure_id", "chunk_arrival_time"),)

    chunk_arrival_time = Column(DateTime)
    extraction_start_time = Column(DateTime)
    natural_decay_time = Column(DateTime)
    moon_id = Column(Integer)
    structure_id = Column(BigInteger, index=True)

class PersonalBookmark(PrivateBase):
    __tablename__   = "personal_bookmarks"
    bookmark_id     = Column(BigInteger, primary_key=True)
    character_id    = Column(Integer, index=True)
    folder_id       = Column(BigInteger)
    location_id     = Column(BigInteger)
    item_id         = Column(BigInteger)
    label           = Column(String)
    created         = Column(DateTime)
    coordinates     = Column(JSON)
    notes           = Column(String)

class Project(PrivateBase):
    __tablename__    = "corp_projects"
    project_id       = Column(String, primary_key=True)
    character_id    = Column(Integer, index=True)
    last_modified    = Column(DateTime)
    name             = Column(String)
    progress_current = Column(Integer)
    progress_desired = Column(Integer)
    reward_initial   = Column(Float)
    reward_remaining = Column(Float)
    state            = Column(String)
    participation_limit = Column(Integer, nullable=True)
    reward_per_contribution = Column(Float, nullable=True)
    submission_limit = Column(Integer, nullable=True)
    submission_multiplier = Column(Float, nullable=True)

class Skill(PrivateBase):
    __tablename__           = "skills"
    character_id            = Column(Integer, primary_key=True)
    skill_id                = Column(Integer, primary_key=True)
    active_level            = Column(Integer)
    skillpoints_in_skill    = Column(Integer)
    trained_skill_level     = Column(Integer)
    skill_active            = Column(Boolean)

class SkillQueue(PrivateBase):
    __tablename__   = "skill_queues"
    character_id    = Column(Integer, primary_key=True)
    queue_position  = Column(Integer, primary_key=True)
    skill_id        = Column(Integer)
    finish_level    = Column(Integer)
    finish_date     = Column(DateTime)

class WalletBalance(PrivateBase):
    __tablename__   = "wallet_balances"
    character_id    = Column(Integer, primary_key=True)
    balance         = Column(Float)

class WalletJournal(PrivateBase):
    __tablename__   = "wallet_journals"
    journal_id      = Column(BigInteger, primary_key=True)
    character_id    = Column(Integer, index=True)
    date            = Column(String)
    description     = Column(String)
    ref_type        = Column(String)
    amount          = Column(Float, nullable=True)
    balance         = Column(Float, nullable=True)
    context_id      = Column(BigInteger, nullable=True)
    context_id_type = Column(String, nullable=True)
    first_party_id  = Column(Integer, nullable=True)
    second_party_id = Column(Integer, nullable=True)
    reason          = Column(String, nullable=True)

class WalletTransaction(PrivateBase):
    __tablename__   = "wallet_transactions"
    transaction_id              = Column(BigInteger, primary_key=True)
    character_id    = Column(Integer, index=True)
    location_id     = Column(Integer)
    type_id         = Column(Float)
    quantity        = Column(Integer)
    amount          = Column(Float)
    unit_price      = Column(Float)
    date            = Column(DateTime)
    is_buy          = Column(Boolean)
    is_personal     = Column(Boolean)


