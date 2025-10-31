import os
import yaml
import logging

from db.database import get_public_session
from db.models import SolarSystem, Stargate

logger = logging.getLogger(__name__)

# ──────── Paths ────────────────────────────────────────────────────────────────
BASE_SDE_PATH        = os.getenv("SDE_PATH", "_sde")
TYPES_YAML_PATH      = os.path.join(BASE_SDE_PATH, "fsd", "types.yaml")
MARKET_GROUPS_PATH   = os.path.join(BASE_SDE_PATH, "fsd", "marketGroups.yaml")
UNIVERSE_PATH        = os.path.join(BASE_SDE_PATH, "fsd", "universe")

# ──────── Caches ───────────────────────────────────────────────────────────────
_type_id_to_name       = None
_name_to_type_id       = None
_system_id_to_region   = None
_market_flat           = {}
_market_tree           = None


def clear_caches() -> None:
    """Reset all cached SDE structures so a fresh load can occur."""

    global _type_id_to_name, _name_to_type_id, _system_id_to_region, _market_flat, _market_tree

    _type_id_to_name = None
    _name_to_type_id = None
    _system_id_to_region = None
    _market_flat = {}
    _market_tree = None

    logger.info("SDE caches cleared.")


def refresh_all_caches() -> None:
    """Force all SDE helpers to reload from disk after an update."""

    clear_caches()
    load_types_data()
    load_market_tree()
    _load_system_to_region_map()
    logger.info("SDE caches repopulated from the latest files.")

# ──────── Type ↔ Name Maps ──────────────────────────────────────────────────────
def load_types_data() -> None:
    """Load types.yaml into memory."""
    global _type_id_to_name, _name_to_type_id
    if _type_id_to_name is not None:
        return

    _type_id_to_name = {}
    _name_to_type_id = {}

    if not os.path.exists(TYPES_YAML_PATH):
        logger.error(f"types.yaml not found at {TYPES_YAML_PATH}")
        return

    with open(TYPES_YAML_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    for tid_str, props in data.items():
        try:
            tid = int(tid_str)
        except ValueError:
            continue
        name = props.get("name", {}).get("en")
        if name:
            _type_id_to_name[tid] = name
            _name_to_type_id[name.lower()] = tid

def name_from_type_id(type_id: int) -> str:
    """Return the human-readable name for a given typeID."""
    if _type_id_to_name is None:
        load_types_data()
    return _type_id_to_name.get(type_id, f"Unknown TypeID {type_id}")

# ──────── Region Mapping ────────────────────────────────────────────────────────
def _load_system_to_region_map():
    """Build map from solarSystemID → regionID by scanning the SDE universe folder."""
    global _system_id_to_region
    if _system_id_to_region is not None:
        return

    _system_id_to_region = {}
    for root, _, files in os.walk(UNIVERSE_PATH):
        if "solarsystem.staticdata.yaml" in files:
            path = os.path.join(root, "solarsystem.staticdata.yaml")
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            sid = int(data.get("solarSystemID", 0))
            rid = data.get("regionID")
            if rid is not None:
                _system_id_to_region[sid] = int(rid)

    logger.info(f"Loaded {_system_id_to_region and len(_system_id_to_region)} system→region mappings")

def region_id_from_system_id(system_id: int) -> int | None:
    """Given a solarSystemID, return its regionID (or None)."""
    if _system_id_to_region is None:
        _load_system_to_region_map()
    return _system_id_to_region.get(system_id)

# ──────── Market‐Group Tree ────────────────────────────────────────────────────
def load_market_tree():
    """
    Load marketGroups.yaml into a hierarchy, and for each group
    populate its 'types' list from types.yaml via marketGroupID.
    """
    global _market_flat, _market_tree
    if _market_tree is not None:
        return _market_tree

    # 1) Load group definitions
    if not os.path.exists(MARKET_GROUPS_PATH):
        logger.error(f"marketGroups.yaml not found at {MARKET_GROUPS_PATH}")
        _market_tree = []
        return _market_tree

    with open(MARKET_GROUPS_PATH, "r", encoding="utf-8") as f:
        groups = yaml.safe_load(f) or {}

    # 2) Initialize flat map
    _market_flat = {}
    for gid_str, info in groups.items():
        try:
            gid = int(gid_str)
        except ValueError:
            continue
        _market_flat[gid] = {
            "id":          gid,
            "name":        info.get("nameID", {}).get("en", f"Unknown {gid}"),
            "description": info.get("descriptionID", {}).get("en", ""),
            "parent":      info.get("parentGroupID"),
            "children":    [],
            "types":       [],
        }

    # 3) Scan types.yaml for marketGroupID
    if os.path.exists(TYPES_YAML_PATH):
        with open(TYPES_YAML_PATH, "r", encoding="utf-8") as f:
            all_types = yaml.safe_load(f) or {}
        for tid_str, props in all_types.items():
            try:
                tid = int(tid_str)
            except ValueError:
                continue
            mgid = props.get("marketGroupID")
            if mgid and mgid in _market_flat:
                _market_flat[mgid]["types"].append(tid)

    # 4) Build parent→children links
    for grp in _market_flat.values():
        parent = grp["parent"]
        if parent is not None and parent in _market_flat:
            _market_flat[parent]["children"].append(grp)

    # 5) Extract top‐level tree
    _market_tree = [g for g in _market_flat.values() if g["parent"] is None]
    return _market_tree

def get_flat_market_map() -> dict[int, str]:
    """Return a simple map of { groupID: groupName }."""
    if not _market_flat:
        load_market_tree()
    return {gid: grp["name"] for gid, grp in _market_flat.items()}

# ──────── NEW Helpers ──────────────────────────────────────────────────────────
def get_types_in_group(group_id: int) -> list[int]:
    """
    Return all typeIDs in the given market‐group (including sub‐groups).
    """
    load_market_tree()
    result: list[int] = []
    def _recurse(gid: int):
        grp = _market_flat.get(gid)
        if not grp:
            return
        result.extend(grp["types"])
        for child in grp["children"]:
            _recurse(child["id"])
    _recurse(group_id)
    return result

def resolve_type_ids(raw_query: str) -> set[int]:
    """
    Given a comma‐separated string of names or IDs, return the matching set of typeIDs.
    """
    load_types_data()
    ids: set[int] = set()
    for token in raw_query.split(","):
        tok = token.strip()
        if not tok:
            continue
        if tok.isdigit():
            ids.add(int(tok))
        else:
            tid = _name_to_type_id.get(tok.lower())
            if tid:
                ids.add(tid)
    return ids

# ──────── Universe Table Builder ──────────────────────────────────────────────
def build_universe_table():
    """
    Walk the SDE 'universe' folder and insert SolarSystem + Stargate records.
    """
    session = get_public_session()
    logger.info("Starting build_universe_table()")

    stargate_map = {}
    for root, _, files in os.walk(UNIVERSE_PATH):
        if "solarsystem.staticdata.yaml" not in files:
            continue
        path = os.path.join(root, "solarsystem.staticdata.yaml")
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        sid  = int(data.get("solarSystemID", 0))
        name = data.get("solarSystemName", f"Unknown {sid}")
        cid  = data.get("constellationID")
        rid  = data.get("regionID")
        planets = len(data.get("planets", []))
        moons   = sum(len(p.get("moons", [])) for p in data.get("planets", []))
        gates   = data.get("stargates", {})
        security = data.get("security", 0.0)

        session.merge(SolarSystem(
            system_id        = sid,
            system_name      = name,
            constellation_id = cid,
            region_id        = rid,
            planets          = planets,
            moons            = moons,
            stargates        = len(gates),
            security         = security,
        ))

        for gstr, ginfo in gates.items():
            gid = int(gstr)
            dest = int(ginfo.get("destination", 0))
            pos = ginfo.get("position", [0.0,0.0,0.0])
            typ = ginfo.get("typeID")
            gate = Stargate(
                stargate_id           = gid,
                system_id             = sid,
                destination_gate_id   = dest,
                destination_system_id = None,
                type_id               = typ,
                position              = pos,
            )
            session.merge(gate)
            stargate_map[gid] = (sid, dest)

            # link reverse if seen
            if dest in stargate_map:
                other_sid, _ = stargate_map[dest]
                existing = session.get(Stargate, dest)
                if existing:
                    existing.destination_system_id = sid
                    session.merge(existing)
                gate.destination_system_id = other_sid
                session.merge(gate)

    session.commit()
    session.close()
    logger.info("build_universe_table() complete")
