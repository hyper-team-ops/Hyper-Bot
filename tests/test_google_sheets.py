import unittest

from bot.services.google_sheets import GoogleSheetsCatalog, SheetsError


class Request:
    def __init__(self, result=None, error=None):
        self.result, self.error = result, error

    def execute(self):
        if self.error:
            raise self.error
        return self.result or {}


class ValuesAPI:
    def __init__(self, sheets, fail_updates=False):
        self.sheets = sheets
        self.fail_updates = fail_updates
        self.batch_bodies = []

    def get(self, **kwargs):
        name = kwargs["range"].strip("'").split("'!")[0]
        return Request({"values": self.sheets.get(name, [])})

    def update(self, **kwargs):
        return Request({})

    def batchUpdate(self, **kwargs):
        self.batch_bodies.append(kwargs["body"])
        return Request(error=RuntimeError("offline") if self.fail_updates else None)


class Service:
    def __init__(self, values):
        self.values_api = values

    def spreadsheets(self):
        return self

    def values(self):
        return self.values_api


class GoogleSheetsTests(unittest.TestCase):
    def sheet_data(self):
        headers = ["File Name", "Size", "Path", "Category", "Source Type",
                   "File ID", "Telegram Link", "Telegram Status"]
        return {"softwares": [headers, ["Editor", "2 MB", "/x", "Tools", "exe",
                                                "sw_1", "", "unavailable"]],
                "courses": [headers]}

    def test_load_and_update_use_stable_id_and_only_target_cells(self):
        values = ValuesAPI(self.sheet_data())
        catalog = GoogleSheetsCatalog("sheet", service=Service(values))
        entries = catalog.load_entries()
        self.assertEqual("sw_1", entries[0].file_id)
        catalog.update_registration("sw_1", "https://t.me/bot?start=f_token", "available")
        data = values.batch_bodies[-1]["data"]
        self.assertEqual(2, len(data))
        self.assertTrue(all(item["range"].endswith("2") for item in data))
        self.assertNotIn("Path", repr(data))

    def test_google_write_failure_is_wrapped_without_credentials_leak(self):
        values = ValuesAPI(self.sheet_data(), fail_updates=True)
        catalog = GoogleSheetsCatalog("sheet", service=Service(values))
        with self.assertRaises(SheetsError) as caught:
            catalog.update_registration("sw_1", "link", "available")
        self.assertNotIn("offline", str(caught.exception))

    def test_missing_id_initialization_requires_explicit_approval(self):
        catalog = GoogleSheetsCatalog("sheet", service=Service(ValuesAPI(self.sheet_data())))
        with self.assertRaises(ValueError):
            catalog.initialize_missing_file_ids()


if __name__ == "__main__":
    unittest.main()
