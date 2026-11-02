import tempfile
import unittest
from pathlib import Path

from bot.database.repository import DuplicateFileError, SQLiteFileRepository
from bot.services.file_registry import FileRegistry


class FileRegistryTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "registry.db"
        self.repository = SQLiteFileRepository(self.path)
        self.registry = FileRegistry(self.repository, -100123)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_two_files_resolve_to_different_messages(self):
        first = self.registry.register("course-1", "Course one", [101])
        second = self.registry.register("course-2", "Course two", [202])
        self.assertNotEqual(first.public_token, second.public_token)
        self.assertEqual((101,), self.repository.get_by_token(first.public_token).message_ids)
        self.assertEqual((202,), self.repository.get_by_token(second.public_token).message_ids)

    def test_multiple_messages_keep_order_after_restart(self):
        record = self.registry.register("album-1", "Album", [12, 11, 15])
        reopened = SQLiteFileRepository(self.path)
        loaded = reopened.get_by_token(record.public_token)
        self.assertEqual((12, 11, 15), loaded.message_ids)

    def test_disabled_token_is_not_publicly_resolved(self):
        record = self.registry.register("pdf-1", "PDF", [44])
        self.repository.set_active("pdf-1", False)
        self.assertIsNone(self.repository.get_by_token(record.public_token))
        self.assertIsNotNone(self.repository.get_by_token(record.public_token, active_only=False))

    def test_duplicate_website_id_is_rejected(self):
        self.registry.register("same-id", "One", [1])
        with self.assertRaises(DuplicateFileError):
            self.registry.register("same-id", "Two", [2])

    def test_update_keeps_public_token(self):
        old = self.registry.register("replace-me", "File", [1])
        updated = self.registry.replace_messages("replace-me", [5, 6])
        self.assertEqual(old.public_token, updated.public_token)
        self.assertEqual((5, 6), updated.message_ids)
