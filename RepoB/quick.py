from db.database import get_public_session
from db.models import MarketOrder, Structure, MarketStructure
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate_structures_to_market_structures():
    with get_public_session() as db:
        # Get all location_ids from MarketOrder that match a Structure
        location_ids = (
            db.query(MarketOrder.location_id)
            .distinct()
            .filter(MarketOrder.location_id.isnot(None))
            .all()
        )
        location_ids = [loc[0] for loc in location_ids]

        existing = {
            ms.structure_id for ms in db.query(MarketStructure.structure_id).all()
        }

        count = 0
        for loc_id in location_ids:
            if loc_id in existing:
                continue

            structure = db.query(Structure).filter_by(structure_id=loc_id).first()
            if structure:
                db.merge(MarketStructure(
                    structure_id=structure.structure_id,
                    name=structure.name,
                    solar_system_id=structure.solar_system_id,
                    region_id=structure.region_id,
                    owner_id=structure.owner_id,
                    type_id=structure.type_id,
                    position=structure.position,
                    last_seen=datetime.utcnow()
                ))
                count += 1

        db.commit()
        logger.info(f"[Migration] Created {count} MarketStructure entries from Structure.")

if __name__ == "__main__":
    migrate_structures_to_market_structures()
