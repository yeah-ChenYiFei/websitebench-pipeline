from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


CLONE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CLONE_ROOT))

from backend.site_backend_integration import open_site_services
from backend.walmart_backend import PRODUCTS


class GeneratedBackendLifecycleTests(unittest.TestCase):
    def test_existing_catalog_upgrade_keeps_cart(self) -> None:
        import backend.walmart_backend as catalog
        with tempfile.TemporaryDirectory(prefix='walmart-upgrade-') as temporary:
            root=Path(temporary)
            runtime=json.loads((CLONE_ROOT.parent/'backend/runtime.json').read_text(encoding='utf-8'))
            legacy=root/'legacy-runtime.json'
            runtime['database']['migration_hook']='backend.walmart_backend:migrate'
            legacy.write_text(json.dumps(runtime),encoding='utf-8')
            database=root/'walmart.sqlite3'
            env={'WEBSITEBENCH_SITE_BACKEND_DATABASE':str(database),'WEBSITEBENCH_SITE_BACKEND_RUNTIME':str(legacy)}
            with patch.dict(os.environ,env),patch.object(catalog,'PRODUCTS',PRODUCTS[:6]):
                backend,_=open_site_services()
                with backend.lifecycle.connection(transaction=True) as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM wb_walmart_products').fetchone()[0],6)
                    connection.execute('INSERT INTO wb_walmart_carts(cart_id,product_id,option_id,quantity) VALUES (?,?,?,?)',('upgrade-cart','dawn-18','original-18',3))
            env['WEBSITEBENCH_SITE_BACKEND_RUNTIME']=str(CLONE_ROOT.parent/'backend/runtime.json')
            with patch.dict(os.environ,env):
                upgraded,_=open_site_services()
                with upgraded.lifecycle.connection() as connection:
                    self.assertEqual(connection.execute('SELECT COUNT(*) FROM wb_walmart_products').fetchone()[0],len(PRODUCTS))
                    self.assertEqual(connection.execute('SELECT quantity FROM wb_walmart_carts WHERE cart_id=?',('upgrade-cart',)).fetchone()[0],3)

    def test_migration_backup_restore_and_reset(self) -> None:
        with tempfile.TemporaryDirectory(prefix="walmart-backend-lifecycle-") as temporary:
            root = Path(temporary).resolve()
            database = root / "data" / "walmart.sqlite3"
            database.parent.mkdir()
            with patch.dict(os.environ, {"WEBSITEBENCH_SITE_BACKEND_DATABASE": str(database)}):
                backend, _ = open_site_services()
                self.assertEqual(backend.config.site_id, "walmart")
                self.assertEqual(backend.lifecycle.database_path, database.resolve())
                with backend.lifecycle.connection(transaction=True) as connection:
                    product_count = connection.execute("SELECT COUNT(*) FROM wb_walmart_products").fetchone()[0]
                    self.assertEqual(product_count, len(PRODUCTS))
                    connection.execute("INSERT INTO wb_walmart_carts(cart_id,product_id,option_id,quantity) VALUES (?,?,?,?)", ("lifecycle-probe", "dawn-18", "original-18", 2))

                backup_path = root / "backup" / "walmart.backup.sqlite3"
                report = backend.lifecycle.backup(backup_path)
                self.assertEqual(report["site_id"], "walmart")
                self.assertTrue(backup_path.is_file())
                with backend.lifecycle.connection(transaction=True) as connection:
                    connection.execute("DELETE FROM wb_walmart_carts")
                backend.lifecycle.restore(backup_path)
                with backend.lifecycle.connection() as connection:
                    quantity = connection.execute("SELECT quantity FROM wb_walmart_carts WHERE cart_id=?", ("lifecycle-probe",)).fetchone()[0]
                    self.assertEqual(quantity, 2)

                backend.lifecycle.reset(confirm_site_id="walmart")
                with backend.lifecycle.connection() as connection:
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM wb_walmart_carts").fetchone()[0], 0)
                    self.assertEqual(connection.execute("SELECT COUNT(*) FROM wb_walmart_products").fetchone()[0], len(PRODUCTS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
