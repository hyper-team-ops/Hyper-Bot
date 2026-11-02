import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.config import CatalogSettings
from bot.database.repository import SQLiteFileRepository
from bot.services.file_registry import FileRegistry
from scripts.export_links import build_rows


class LinkExportTests(unittest.TestCase):
    def test_export_configuration_does_not_require_bot_credentials(self):
        with patch.dict(
            "os.environ",
            {
                "BOT_USERNAME": "HyperTeamITE_Bot",
                "DATABASE_URL": "sqlite:///catalog.db",
            },
            clear=True,
        ):
            settings = CatalogSettings.from_env(
                dotenv_path=Path("/definitely/missing/.env")
            )
        self.assertEqual("HyperTeamITE_Bot", settings.bot_username)
        self.assertEqual(Path("catalog.db"), settings.database_path)

    def test_export_is_stable_and_contains_no_telegram_source_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteFileRepository(Path(directory) / "export.db")
            registry = FileRegistry(repository, -100123456)
            first = registry.register("z-file", "Z file", [900])
            registry.register("a-file", "A file", [100, 101])

            rows = build_rows(repository, "HyperTeamITE_Bot")
            self.assertEqual(["a-file", "z-file"], [row["website_id"] for row in rows])
            self.assertEqual(
                f"https://t.me/HyperTeamITE_Bot?start={first.public_token}",
                rows[1]["telegram_url"],
            )
            self.assertEqual(
                {"website_id", "title", "telegram_url", "active"},
                set(rows[0]),
            )
            rendered = repr(rows)
            self.assertNotIn("-100123456", rendered)
            self.assertNotIn("message_id", rendered)

    def test_inactive_records_are_excluded_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SQLiteFileRepository(Path(directory) / "export.db")
            registry = FileRegistry(repository, -100123456)
            registry.register("disabled", "Disabled", [1])
            repository.set_active("disabled", False)
            self.assertEqual([], build_rows(repository, "test_bot"))
            self.assertEqual(
                1,
                len(
                    build_rows(
                        repository, "test_bot", include_inactive=True
                    )
                ),
            )
