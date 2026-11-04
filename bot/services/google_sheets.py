"""Private, idempotent Google Sheets catalog access."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bot.database.models import CatalogEntry
from bot.services.deep_links import validate_website_id

logger = logging.getLogger(__name__)

SHEET_NAMES = ("softwares", "courses")
REQUIRED_COLUMNS = ("File ID", "Telegram Link", "Telegram Status")
GOOGLE_API_RETRIES = 3


class SheetsError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CatalogIdTarget:
    row_number: int
    requested_file_id: str
    expected_title: str
    expected_source_url: str


def _column_name(index: int) -> str:
    value = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        value = chr(65 + remainder) + value
    return value


def _header_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _positions(headers: list[str]) -> dict[str, int]:
    """Map whitespace/case-normalized headings while keeping the original row."""
    return {_header_key(str(name)): index for index, name in enumerate(headers)}


def _column_index(headers: list[str], name: str) -> int | None:
    return _positions(headers).get(_header_key(name))


def _execute(request: Any) -> dict[str, Any]:
    """Use the Google client's bounded retry support for transient API failures."""
    return request.execute(num_retries=GOOGLE_API_RETRIES)


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
            response = _execute(self._values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet_name}'",
            ))
            return response.get("values", [])
        except Exception as exc:
            logger.warning("Google Sheets catalog read failed: %s", type(exc).__name__)
            raise SheetsError("Unable to read Google Sheets catalog") from exc

    def _ensure_columns(self, sheet_name: str, values: list[list[str]]) -> tuple[list[str], list[list[str]]]:
        headers = list(values[0]) if values else []
        positions = _positions(headers)
        missing = [
            column for column in REQUIRED_COLUMNS
            if _header_key(column) not in positions
        ]
        if missing:
            headers.extend(missing)
            try:
                _execute(self._values().update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{sheet_name}'!1:1", valueInputOption="RAW",
                    body={"values": [headers]},
                ))
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
            positions = _positions(headers)
            for row_number, row in enumerate(values[1:], start=2):
                def cell(name: str) -> str | None:
                    index = positions.get(_header_key(name))
                    return row[index].strip() if index is not None and index < len(row) and row[index].strip() else None
                file_id, title = cell("File ID"), cell("File Name")
                if title:
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
            file_id_index = _column_index(headers, "File ID")
            name_index = _column_index(headers, "File Name")
            if file_id_index is None:
                raise SheetsError("Unable to locate the File ID column")
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
                    _execute(self._values().batchUpdate(
                        spreadsheetId=self.spreadsheet_id,
                        body={"valueInputOption": "RAW", "data": updates},
                    ))
                except Exception as exc:
                    raise SheetsError("Unable to initialize stable File IDs") from exc
                changed += len(updates)
        return changed

    def ensure_entry_file_id(
        self, *, sheet_name: str, row_number: int, requested_file_id: str,
        expected_title: str, expected_source_url: str, approved: bool = False,
    ) -> CatalogEntry:
        """Initialize one verified catalog row without touching any other row ID."""
        return self.ensure_entries_file_ids(
            sheet_name=sheet_name,
            targets=(CatalogIdTarget(
                row_number=row_number, requested_file_id=requested_file_id,
                expected_title=expected_title,
                expected_source_url=expected_source_url,
            ),),
            approved=approved,
        )[0]

    def ensure_entries_file_ids(
        self, *, sheet_name: str, targets: tuple[CatalogIdTarget, ...],
        approved: bool = False,
    ) -> list[CatalogEntry]:
        """Initialize a verified set of rows in one bounded, idempotent batch."""
        if not approved:
            raise ValueError("Targeted File ID initialization requires explicit approval")
        if sheet_name not in SHEET_NAMES or not targets:
            raise ValueError("Invalid catalog sheet or empty target set")
        if len({target.row_number for target in targets}) != len(targets):
            raise ValueError("Target rows cannot be repeated")
        normalized_targets = tuple(CatalogIdTarget(
            row_number=target.row_number,
            requested_file_id=validate_website_id(target.requested_file_id.strip()),
            expected_title=target.expected_title,
            expected_source_url=target.expected_source_url,
        ) for target in targets)
        if any(target.row_number < 2 for target in normalized_targets):
            raise ValueError("Invalid catalog data row")

        values = self._read(sheet_name)
        if not values or any(
            target.row_number > len(values) for target in normalized_targets
        ):
            raise SheetsError("Target catalog row does not exist")
        original_headers = list(values[0])
        original_positions = _positions(original_headers)
        title_index = original_positions.get(_header_key("File Name"))
        source_index = original_positions.get(_header_key("Source Type"))
        for target in normalized_targets:
            target_row = values[target.row_number - 1]

            def original_cell(index: int | None) -> str | None:
                if index is None or index >= len(target_row):
                    return None
                value = target_row[index].strip()
                return value or None

            if (original_cell(title_index) != target.expected_title
                    or original_cell(source_index) != target.expected_source_url):
                raise SheetsError("Target catalog row identity changed; refusing update")

        headers, _ = self._ensure_columns(sheet_name, values)
        file_id_index = _column_index(headers, "File ID")
        if file_id_index is None:
            raise SheetsError("Unable to locate the File ID column")
        entries = self.load_entries()
        by_file_id: dict[str, list[CatalogEntry]] = {}
        for entry in entries:
            if entry.file_id:
                by_file_id.setdefault(entry.file_id, []).append(entry)
        reserved_ids = set(by_file_id)
        expected_ids: dict[int, str] = {}
        updates: list[dict[str, Any]] = []
        for target in normalized_targets:
            target_row = values[target.row_number - 1]
            existing_file_id = (
                target_row[file_id_index].strip()
                if file_id_index < len(target_row) else ""
            )
            if existing_file_id:
                matches = by_file_id.get(existing_file_id, [])
                if (len(matches) != 1 or matches[0].sheet_name != sheet_name
                        or matches[0].row_number != target.row_number):
                    raise SheetsError(
                        "Existing File ID must identify exactly one catalog row"
                    )
                expected_ids[target.row_number] = existing_file_id
                continue
            if target.requested_file_id in reserved_ids:
                raise SheetsError(
                    "Requested File ID already belongs to another catalog row"
                )
            reserved_ids.add(target.requested_file_id)
            expected_ids[target.row_number] = target.requested_file_id
            updates.append({
                "range": (
                    f"'{sheet_name}'!{_column_name(file_id_index + 1)}"
                    f"{target.row_number}"
                ),
                "values": [[target.requested_file_id]],
            })
        if updates:
            try:
                _execute(self._values().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": updates},
                ))
            except Exception as exc:
                raise SheetsError("Unable to initialize target File IDs") from exc

        refreshed = {
            entry.row_number: entry for entry in self.load_entries()
            if entry.sheet_name == sheet_name
            and entry.row_number in expected_ids
        }
        if any(
            row_number not in refreshed
            or refreshed[row_number].file_id != expected_file_id
            for row_number, expected_file_id in expected_ids.items()
        ):
            raise SheetsError("Target File ID writes could not be verified")
        return [refreshed[target.row_number] for target in normalized_targets]

    def update_registration(self, file_id: str, telegram_link: str | None,
                            status: str) -> CatalogEntry:
        return self.update_registrations({file_id: (telegram_link, status)})[0]

    def update_registrations(
        self, updates: dict[str, tuple[str | None, str]],
    ) -> list[CatalogEntry]:
        """Synchronize a validated set of stable IDs in one bounded batch."""
        if not updates:
            return []
        allowed_statuses = {"available", "unavailable", "pending_review"}
        if any(status not in allowed_statuses for _, status in updates.values()):
            raise ValueError("Invalid Telegram Status")
        entries = self.load_entries()
        by_file_id: dict[str, list[CatalogEntry]] = {}
        for entry in entries:
            if entry.file_id in updates:
                by_file_id.setdefault(entry.file_id, []).append(entry)
        if any(len(by_file_id.get(file_id, [])) != 1 for file_id in updates):
            raise SheetsError("Each File ID must identify exactly one catalog row")
        targets = [by_file_id[file_id][0] for file_id in updates]
        columns: dict[str, tuple[str, str]] = {}
        for sheet_name in {entry.sheet_name for entry in targets}:
            values = self._read(sheet_name)
            headers, _ = self._ensure_columns(sheet_name, values)
            link_index = _column_index(headers, "Telegram Link")
            status_index = _column_index(headers, "Telegram Status")
            if link_index is None or status_index is None:
                raise SheetsError("Unable to locate Telegram synchronization columns")
            columns[sheet_name] = (
                _column_name(link_index + 1),
                _column_name(status_index + 1),
            )
        data: list[dict[str, Any]] = []
        for file_id, (telegram_link, status) in updates.items():
            entry = by_file_id[file_id][0]
            link_col, status_col = columns[entry.sheet_name]
            data.extend((
                {"range": f"'{entry.sheet_name}'!{link_col}{entry.row_number}",
                 "values": [[telegram_link or ""]]},
                {"range": f"'{entry.sheet_name}'!{status_col}{entry.row_number}",
                 "values": [[status]]},
            ))
        try:
            _execute(self._values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            ))
        except Exception as exc:
            logger.warning("Google Sheets registration update failed: %s", type(exc).__name__)
            raise SheetsError("Unable to synchronize Google Sheets") from exc
        refreshed_by_id = {
            entry.file_id: entry for entry in self.load_entries()
            if entry.file_id in updates
        }
        if any(
            file_id not in refreshed_by_id
            or refreshed_by_id[file_id].telegram_link != (link or None)
            or refreshed_by_id[file_id].telegram_status != status
            for file_id, (link, status) in updates.items()
        ):
            raise SheetsError("Google Sheets synchronization could not be verified")
        return [refreshed_by_id[file_id] for file_id in updates]
