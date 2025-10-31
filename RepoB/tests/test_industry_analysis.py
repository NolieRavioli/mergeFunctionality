import os
import tempfile
import unittest

from sqlalchemy.orm import Session

from analysis.industry import clear_cache, generate_industry_report
from db import database
from db.models import Blueprint as BlueprintRow, Character, MarketOrder
from util import sde
from util.settings_store import ManufacturingSettings


class IndustryAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.sde_root = os.path.join(self.tempdir.name, "sde")
        os.makedirs(os.path.join(self.sde_root, "fsd"), exist_ok=True)

        blueprints_yaml = os.path.join(self.sde_root, "fsd", "blueprints.yaml")
        with open(blueprints_yaml, "w", encoding="utf-8") as handle:
            handle.write(
                """
                1001:
                  activities:
                    manufacturing:
                      time: 600
                      products:
                        - typeID: 2001
                          quantity: 1
                      materials:
                        - typeID: 3001
                          quantity: 10
                """
            )

        types_yaml = os.path.join(self.sde_root, "fsd", "types.yaml")
        with open(types_yaml, "w", encoding="utf-8") as handle:
            handle.write(
                """
                1001:
                  name:
                    en: Test Blueprint
                2001:
                  name:
                    en: Test Product
                3001:
                  name:
                    en: Test Material
                """
            )

        # Point environment to temporary databases
        self.public_db_path = os.path.join(self.tempdir.name, "public.db")
        self.private_dir = os.path.join(self.tempdir.name, "private")
        os.environ["EVE_PUBLIC_DATABASE_FILE"] = self.public_db_path
        os.environ["EVE_PRIVATE_DATABASE_FOLDER"] = self.private_dir
        os.environ["SDE_PATH"] = self.sde_root

        # Align module constants with the temporary paths
        database.PUBLIC_DATABASE_FILE = self.public_db_path
        database.PRIVATE_DATA_FOLDER = self.private_dir
        sde.BASE_SDE_PATH = self.sde_root
        sde.TYPES_YAML_PATH = os.path.join(self.sde_root, "fsd", "types.yaml")
        sde.MARKET_GROUPS_PATH = os.path.join(self.sde_root, "fsd", "marketGroups.yaml")
        sde.UNIVERSE_PATH = os.path.join(self.sde_root, "fsd", "universe")

        # Reset database state
        database._public_engine = None
        database._PublicSession = None
        database._private_engines = {}
        database._PrivateSessions = {}

        database.initialize_public_database()
        database.initialize_private_database(owner_id=777)

        # Clear caches so util.sde and analysis.industry reload new files
        sde.clear_caches()
        clear_cache()

        # Seed data
        self._seed_data()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _seed_data(self) -> None:
        public_session: Session = database.get_public_session()
        public_session.add_all(
            [
                MarketOrder(
                    order_id=1,
                    type_id=2001,
                    location_id=60003760,
                    region_id=10000002,
                    is_buy_order=False,
                    price=100000.0,
                    volume_remain=10,
                    volume_total=10,
                ),
                MarketOrder(
                    order_id=2,
                    type_id=3001,
                    location_id=60003760,
                    region_id=10000002,
                    is_buy_order=False,
                    price=5000.0,
                    volume_remain=100,
                    volume_total=100,
                ),
            ]
        )
        public_session.commit()
        public_session.close()

        private_session: Session = database.get_private_session(777)
        private_session.add(Character(character_id=555, name="Unit Tester"))
        private_session.add(
            BlueprintRow(
                item_id=9001,
                character_id=555,
                type_id=1001,
                material_efficiency=10,
                time_efficiency=14,
                runs=5,
                quantity=1,
                location_id=60003760,
                location_flag="Hangar",
            )
        )
        private_session.commit()
        private_session.close()

    def test_generates_profitability_report(self) -> None:
        settings = ManufacturingSettings()
        report = generate_industry_report(777, settings, sde_root=self.sde_root)

        self.assertEqual(report.summary["blueprint_total"], 1)
        self.assertEqual(len(report.library), 1)
        entry = report.library[0]
        self.assertEqual(entry.blueprint_name, "Test Blueprint")
        self.assertAlmostEqual(entry.materials[0].adjusted_quantity, 9)
        self.assertAlmostEqual(entry.profit_per_run, 55000.0, places=2)
        self.assertTrue(report.manufacturing_plan)
        plan_item = report.manufacturing_plan[0]
        self.assertAlmostEqual(plan_item.isk_per_hour, 383720.93, places=2)

    def test_handles_missing_blueprints_gracefully(self) -> None:
        missing_root = os.path.join(self.tempdir.name, "missing")
        os.makedirs(missing_root, exist_ok=True)
        settings = ManufacturingSettings()
        report = generate_industry_report(777, settings, sde_root=missing_root)
        self.assertEqual(report.summary["blueprint_total"], 0)
        self.assertFalse(report.library)
        self.assertFalse(report.manufacturing_plan)

