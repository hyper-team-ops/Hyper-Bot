"""Private, idempotent Google Sheets catalog access."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any

from bot.database.models import CatalogEntry

logger = logging.getLogger(__name__)

SHEET_NAMES = ("softwares", "courses")
REQUIRED_COLUMNS = ("File ID", "Telegram Link", "Telegram Status")


class SheetsError(RuntimeError):
    pass


def _column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


class GoogleSheetsCatalog:
    def __init__(
        self, spreadsheet_id: str, credentials_path: str | None = None,
        *, service: Any | None = None,
    ) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.credentials_path = credentials_path
        self._service = service

    @property
    def service(self) -> Any:
        if self._service is None:
            try:
                from google.oauth2.service_account import Credentials
                from googleapiclient.discovery import build
            except ImportError as exc:
                raise SheetsError(
                    "Google dependencies are not installed; run pip install -r requirements.txt"
                ) from exc
            scopes = ["https://www.googleapis.com/auth/spreadsheets"]
            credentials = Credentials.from_service_account_file(
                self.credentials_path, scopes=scopes
            ) if self.credentials_path else None
            self._service = build("sheets", "v4", credentials=credentials,
                                  cache_discovery=False)
        return self._service

    def _values(self) -> Any:
        return self.service.spreadsheets().values()

    def _read(self, sheet_name: str) -> list[list[str]]:
        try:
            response = self._values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet_name}'",
            ).execute()
            return response.get("values", [])
        except Exception as exc:
            logger.warning("Google Sheets catalog read failed: %s", type(exc).__name__)
            raise SheetsError("Unable to read Google Sheets catalog") from exc

    def _ensure_columns(self, sheet_name: str, values: list[list[str]]) -> tuple[list[str], list[list[str]]]:
        headers = list(values[0]) if values else []
        missing = [column for column in REQUIRED_COLUMNS if column not in headers]
        if missing:
            headers.extend(missing)
            try:
                self._values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{sheet_name}'!1:1", valueInputOption="RAW",
                    body={"values": [headers]},
                ).execute()
            except Exception as exc:
                raise SheetsError("Unable to add catalog columns") from exc
        return headers, values[1:] if values else []

    def load_entries(self) -> list[CatalogEntry]:
        result: list[CatalogEntry] = []
        for sheet_name in SHEET_NAMES:
            values = self._read(sheet_name)
            if not values:
                continue
            headers = values[0]
            positions = {name: index for index, name in enumerate(headers)}
            for row_number, row in enumerate(values[1:], start=2):
                def cell(name: str) -> str | None:
                    index = positions.get(name)
                    return row[index].strip() if index is not None and index < len(row) and row[index].strip() else None
                file_id, title = cell("File ID"), cell("File Name")
                if file_id and title:
                    result.append(CatalogEntry(
                        file_id=file_id, title=title, size=cell("Size"),
                        category=cell("Category"), source_type=cell("Source Type"),
                        sheet_name=sheet_name, row_number=row_number,
                        telegram_link=cell("Telegram Link"),
                        telegram_status=cell("Telegram Status"),
                    ))
        return result

    def initialize_missing_file_ids(self, *, approved: bool = False) -> int:
        """Explicitly initialize stable IDs; never called by routine synchronization."""
        if not approved:
            raise ValueError("File ID initialization requires explicit approval")
        changed = 0
        for sheet_name in SHEET_NAMES:
            values = self._read(sheet_name)
            headers, rows = self._ensure_columns(sheet_name, values)
            file_id_index = headers.index("File ID")
            name_index = headers.index("File Name") if "File Name" in headers else None
            prefix = "sw" if sheet_name == "softwares" else "course"
            updates: list[dict[str, Any]] = []
            for row_number, row in enumerate(rows, start=2):
                has_name = name_index is not None and name_index < len(row) and row[name_index].strip()
                has_id = file_id_index < len(row) and row[file_id_index].strip()
                if has_name and not has_id:
                    updates.append({"range": f"'{sheet_name}'!{_column_name(file_id_index + 1)}{row_number}",
                                    "values": [[f"{prefix}_{uuid.uuid4().hex}"]]})
            if updates:
                try:
                    self._values().batchUpdate(
                        spreadsheetId=self.spreadsheet_id,
                        body={"valueInputOption": "RAW", "data": updates},
                    ).execute()
                except Exception as exc:
                    raise SheetsError("Unable to initialize stable File IDs") from exc
                changed += len(updates)
        return changed

    def update_registration(self, file_id: str, telegram_link: str | None,
                            status: str) -> CatalogEntry:
        if status not in {"available", "unavailable", "pending_review"}:
            raise ValueError("Invalid Telegram Status")
        matches = [entry for entry in self.load_entries() if entry.file_id == file_id]
        if len(matches) != 1:
            raise SheetsError("File ID must identify exactly one catalog row")
        entry = matches[0]
        values = self._read(entry.sheet_name)
        headers, _ = self._ensure_columns(entry.sheet_name, values)
        link_col = _column_name(headers.index("Telegram Link") + 1)
        status_col = _column_name(headers.index("Telegram Status") + 1)
        data = [
            {"range": f"'{entry.sheet_name}'!{link_col}{entry.row_number}",
             "values": [[telegram_link or ""]]},
            {"range": f"'{entry.sheet_name}'!{status_col}{entry.row_number}",
             "values": [[status]]},
        ]
        try:
            self._values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            ).execute()
        except Exception as exc:
            logger.warning("Google Sheets registration update failed: %s", type(exc).__name__)
            raise SheetsError("Unable to synchronize Google Sheets") from exc
        return entry
