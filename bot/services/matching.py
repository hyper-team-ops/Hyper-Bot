"""Conservative Telegram-to-catalog matching."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import PurePath

from bot.database.models import CatalogEntry, MatchStatus
from bot.services.discovery import ResourceMetadata

ALIASES = {
    "vscode": "visual studio code",
    "vs code": "visual studio code",
    "photoshop": "adobe photoshop",
}
VERSION = re.compile(r"\b(?:v(?:er(?:sion)?)?\s*)?\d+(?:[._-]\d+)*(?:\s*(?:x64|x86|64bit|32bit))?\b")
NOISE = re.compile(r"\b(?:setup|installer|portable|user|win(?:dows)?|linux|macos|x64|x86)\b")


def normalize_filename(value: str) -> str:
    stem = PurePath(value.replace("\\", "/")).stem
    stem = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", stem)
    stem = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem)
    text = unicodedata.normalize("NFKC", stem).casefold()
    text = re.sub(r"[_+.\-]+", " ", text)
    text = VERSION.sub(" ", text)
    text = NOISE.sub(" ", text)
    text = " ".join(text.split())
    return ALIASES.get(text, text)


def _size_bytes(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"([\d.]+)\s*(b|kb|mb|gb|tb)?", value.casefold().replace(",", ""))
    if not match:
        return None
    units = {None: 1, "b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}
    return int(float(match.group(1)) * units[match.group(2)])


@dataclass(frozen=True, slots=True)
class MatchResult:
    status: MatchStatus
    entry: CatalogEntry | None
    confidence: float
    alternatives: tuple[CatalogEntry, ...] = ()
    reason: str = ""


class FileMatcher:
    def __init__(self, *, exact_threshold: float = 0.90, ambiguous_threshold: float = 0.55) -> None:
        self.exact_threshold = exact_threshold
        self.ambiguous_threshold = ambiguous_threshold

    def _score(self, item: ResourceMetadata, entry: CatalogEntry) -> float:
        source = normalize_filename(item.filename or item.caption or "")
        target = normalize_filename(entry.title)
        if not source or not target:
            return 0.0
        score = SequenceMatcher(None, source, target).ratio()
        source_tokens, target_tokens = set(source.split()), set(target.split())
        if source_tokens and target_tokens:
            overlap = len(source_tokens & target_tokens) / len(source_tokens | target_tokens)
            score = max(score, overlap)
        if source == target:
            score = 1.0
        extension = PurePath(item.filename or "").suffix.casefold().lstrip(".")
        source_type = (entry.source_type or "").casefold().lstrip(".")
        if extension and source_type and extension in source_type:
            score = min(1.0, score + 0.04)
        expected_size = _size_bytes(entry.size)
        if expected_size and item.file_size:
            delta = abs(expected_size - item.file_size) / max(expected_size, item.file_size)
            if delta <= 0.03:
                score = min(1.0, score + 0.08)
            elif delta > 0.25:
                score *= 0.75
        context = " ".join(filter(None, (item.topic_title, item.caption))).casefold()
        if entry.category and entry.category.casefold() in context:
            score = min(1.0, score + 0.04)
        return round(score, 4)

    def match(self, item: ResourceMetadata, catalog: list[CatalogEntry]) -> MatchResult:
        ranked = sorted(((self._score(item, entry), entry) for entry in catalog),
                        key=lambda pair: pair[0], reverse=True)
        ranked = [pair for pair in ranked if pair[0] >= self.ambiguous_threshold]
        if not ranked:
            return MatchResult(MatchStatus.UNMATCHED, None, 0, reason="no reliable catalog match")
        best_score, best = ranked[0]
        alternatives = tuple(entry for _, entry in ranked[1:5])
        gap = best_score - (ranked[1][0] if len(ranked) > 1 else 0)
        if best_score >= self.exact_threshold and gap >= 0.10:
            return MatchResult(MatchStatus.EXACT, best, best_score, alternatives,
                               "unique high-confidence filename match")
        return MatchResult(MatchStatus.AMBIGUOUS, best, best_score, alternatives,
                           "similar or insufficiently unique catalog entries")
