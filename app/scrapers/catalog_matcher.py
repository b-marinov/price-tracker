"""Catalog-based product name normaliser.

Maps raw scraped product titles to a canonical name from ``catalog.yaml``,
extracting brand, pack_info, and additional_info as separate fields.

Matching runs in three tiers (fast-to-slow):

1. **Exact / near-exact** — rapidfuzz ``token_sort_ratio`` ≥ 92.  No LLM,
   runs in microseconds.
2. **Top-N fuzzy short-list + LLM** — top-5 candidates sent to a text LLM
   (qwen3.5:9b) with the raw title for structured extraction.
3. **No match** — item falls through unchanged; existing ``find_or_create_product``
   logic handles it with status ``pending_review``.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CATALOG_PATH = Path(__file__).parent / "catalog.yaml"

# rapidfuzz is an optional dependency — import lazily so the app still starts
# without it (matching will fall back to LLM-only).
try:
    from rapidfuzz import fuzz, process as fuzz_process
    _HAS_RAPIDFUZZ = True
except ImportError:  # pragma: no cover
    _HAS_RAPIDFUZZ = False
    logger.warning("rapidfuzz not installed — catalog fuzzy matching disabled (LLM fallback only)")

_FUZZY_EXACT_THRESHOLD = 92   # >= this → confident match without LLM
_FUZZY_CANDIDATES = 5         # number of candidates passed to LLM


@dataclass
class CatalogMatch:
    """Result of a successful catalog lookup.

    Attributes:
        catalog_name: Exact canonical name from catalog.yaml (e.g. "Бира").
        category: Category tag from catalog.yaml (e.g. "Бира").
        brand: Manufacturer / label extracted from the raw title, or None.
        pack_info: Size / quantity string (e.g. "0.5 л", "500 г"), or None.
        additional_info: Variety, preparation, origin, etc., or None.
    """

    catalog_name: str
    category: str
    brand: str | None
    pack_info: str | None
    additional_info: str | None


@dataclass
class _CatalogEntry:
    name: str
    category: str
    normalised: str   # pre-computed for matching


def _normalise(text: str) -> str:
    """Lower-case, NFKD-normalise, strip punctuation for fuzzy comparison.

    Args:
        text: Raw string to normalise.

    Returns:
        Normalised ASCII-friendly string suitable for fuzzy matching.
    """
    value = unicodedata.normalize("NFKD", text)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s]", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def _load_catalog() -> list[_CatalogEntry]:
    """Load and parse catalog.yaml into a list of CatalogEntry objects.

    Returns:
        List of CatalogEntry instances, one per product in the catalog.
    """
    with _CATALOG_PATH.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    entries: list[_CatalogEntry] = []
    for item in data.get("products", []):
        name = item["name"]
        category = item.get("category", "")
        entries.append(_CatalogEntry(name=name, category=category, normalised=_normalise(name)))
    logger.info("Loaded %d catalog entries from %s", len(entries), _CATALOG_PATH)
    return entries


_CATALOG_SYSTEM_PROMPT = """\
You are a grocery product data extractor for a Bulgarian supermarket price-tracker.

You will receive a raw product title scraped from a store, plus a list of candidate \
canonical product names from our catalog.

Your job:
1. Pick the best matching canonical name from the candidates list, or return null if \
   none is a good match (e.g. the scraped title is for a non-food item or something \
   completely different).
2. Extract the brand (manufacturer / label), pack_info (size/quantity), and \
   additional_info (variety, preparation, origin, flavour) from the raw title.

Rules:
- catalog_match MUST be the exact text of one of the candidates, or null.
- brand is the manufacturer name (e.g. "Heineken", "Metro Chef", "Milka").  \
  Leave null for unbranded / generic items.
- pack_info is size or quantity only (e.g. "0.5 л", "500 г", "6 х 100 г", "2 бр").  \
  Leave null if not present.
- additional_info is everything else that describes the variant but is NOT brand or \
  size (e.g. "Финосмляна", "Готово за консумация", "Пушена", "Натурален").  \
  Leave null if nothing applies.
- Respond ONLY with valid JSON — no extra text, no markdown.

Response format:
{"catalog_match": "<exact candidate text or null>", "brand": "<brand or null>", \
"pack_info": "<size or null>", "additional_info": "<variant info or null>"}
"""


class CatalogMatcher:
    """3-tier catalog matcher: fuzzy → LLM → no match.

    Attributes:
        entries: All catalog entries loaded from catalog.yaml.
        _normalised_names: Pre-built list for rapidfuzz batch scoring.
        _name_to_entry: Fast lookup from normalised name → entry.
    """

    def __init__(self) -> None:
        self._entries = _load_catalog()
        self._normalised_names = [e.normalised for e in self._entries]
        self._name_to_entry: dict[str, _CatalogEntry] = {
            e.normalised: e for e in self._entries
        }
        self._llm_client: Any = None  # lazily initialised

    def _get_llm_client(self) -> Any:
        """Return a shared text LLM client, creating it on first use.

        Returns:
            OllamaVisionClient configured with the text model.
        """
        if self._llm_client is None:
            from app.scrapers.llm_parser import _get_text_client  # noqa: PLC0415
            self._llm_client = _get_text_client()
        return self._llm_client

    def _fuzzy_candidates(self, normalised_input: str, n: int = _FUZZY_CANDIDATES) -> list[_CatalogEntry]:
        """Return the top-N catalog entries by fuzzy score.

        Args:
            normalised_input: Pre-normalised input string.
            n: Number of candidates to return.

        Returns:
            Up to n CatalogEntry objects ordered by descending score.
        """
        if not _HAS_RAPIDFUZZ:
            return []
        results = fuzz_process.extract(
            normalised_input,
            self._normalised_names,
            scorer=fuzz.token_sort_ratio,
            limit=n,
        )
        return [self._name_to_entry[match] for match, _score, _idx in results]

    def _best_fuzzy_score(self, normalised_input: str) -> tuple[_CatalogEntry | None, float]:
        """Return the highest-scoring catalog entry and its score.

        Args:
            normalised_input: Pre-normalised input string.

        Returns:
            Tuple of (best entry or None, score 0-100).
        """
        if not _HAS_RAPIDFUZZ or not self._normalised_names:
            return None, 0.0
        match, score, idx = fuzz_process.extractOne(
            normalised_input,
            self._normalised_names,
            scorer=fuzz.token_sort_ratio,
        )
        return self._name_to_entry[match], score

    def _llm_match(
        self,
        raw_title: str,
        candidates: list[_CatalogEntry],
        brand: str | None,
        pack_info: str | None,
        additional_info: str | None,
    ) -> CatalogMatch | None:
        """Ask the text LLM to map the raw title to one of the candidates.

        Args:
            raw_title: Original scraped product title.
            candidates: Short-listed catalog entries for the LLM to choose from.
            brand: Brand already extracted by the scraper (may be None).
            pack_info: Pack info already extracted by the scraper (may be None).
            additional_info: Additional info already extracted (may be None).

        Returns:
            CatalogMatch if the LLM returns a valid match, else None.
        """
        candidate_names = [c.name for c in candidates]
        candidate_list = "\n".join(f"- {n}" for n in candidate_names)

        already_known: list[str] = []
        if brand:
            already_known.append(f'brand="{brand}"')
        if pack_info:
            already_known.append(f'pack_info="{pack_info}"')
        if additional_info:
            already_known.append(f'additional_info="{additional_info}"')
        known_str = f"\nAlready extracted by scraper: {', '.join(already_known)}" if already_known else ""

        user_msg = (
            f"Raw product title: \"{raw_title}\"{known_str}\n\n"
            f"Catalog candidates:\n{candidate_list}"
        )

        try:
            client = self._get_llm_client()
            raw_response = client.ask_text(_CATALOG_SYSTEM_PROMPT, user_msg)
            if not raw_response:
                return None
            data = json.loads(raw_response)
        except (json.JSONDecodeError, Exception) as exc:
            logger.debug("Catalog LLM parse error for %r: %s", raw_title, exc)
            return None

        catalog_match_name: str | None = data.get("catalog_match")
        if not catalog_match_name:
            return None

        # Find the matching entry by name (LLM must return exact text)
        entry = next((c for c in candidates if c.name == catalog_match_name), None)
        if entry is None:
            logger.debug(
                "LLM returned unknown catalog name %r for title %r",
                catalog_match_name,
                raw_title,
            )
            return None

        return CatalogMatch(
            catalog_name=entry.name,
            category=entry.category,
            brand=data.get("brand") or brand,
            pack_info=data.get("pack_info") or pack_info,
            additional_info=data.get("additional_info") or additional_info,
        )

    def match(
        self,
        raw_title: str,
        brand: str | None = None,
        pack_info: str | None = None,
        additional_info: str | None = None,
    ) -> CatalogMatch | None:
        """Match a scraped product title to the closest catalog entry.

        Tier 1: rapidfuzz token_sort_ratio >= 92 → instant match, keep scraper
                brand/pack_info/additional_info as-is.
        Tier 2: top-5 fuzzy candidates passed to text LLM for structured extraction.
        Tier 3: No match → return None (caller handles via pending_review path).

        Args:
            raw_title: Raw product name from the scraper.
            brand: Brand already extracted by the scraper (may be None).
            pack_info: Pack info already extracted by the scraper (may be None).
            additional_info: Additional info already extracted (may be None).

        Returns:
            CatalogMatch on success, None if no confident match found.
        """
        if not raw_title or not raw_title.strip():
            return None

        normalised_input = _normalise(raw_title)

        # ── Tier 1: fast fuzzy match ─────────────────────────────────────────
        best_entry, best_score = self._best_fuzzy_score(normalised_input)
        if best_entry is not None and best_score >= _FUZZY_EXACT_THRESHOLD:
            logger.debug(
                "Catalog tier-1 match: %r → %r (score=%.0f)",
                raw_title,
                best_entry.name,
                best_score,
            )
            return CatalogMatch(
                catalog_name=best_entry.name,
                category=best_entry.category,
                brand=brand,
                pack_info=pack_info,
                additional_info=additional_info,
            )

        # ── Tier 2: LLM match from top-N candidates ──────────────────────────
        candidates = self._fuzzy_candidates(normalised_input)
        if not candidates:
            logger.debug("Catalog: no fuzzy candidates for %r — skipping LLM", raw_title)
            return None

        result = self._llm_match(raw_title, candidates, brand, pack_info, additional_info)
        if result:
            logger.debug(
                "Catalog tier-2 LLM match: %r → %r",
                raw_title,
                result.catalog_name,
            )
        else:
            logger.debug("Catalog: no match found for %r", raw_title)

        return result


# ── Singleton accessor ────────────────────────────────────────────────────────

_matcher_instance: CatalogMatcher | None = None


def get_catalog_matcher() -> CatalogMatcher:
    """Return the shared CatalogMatcher singleton (loaded once per process).

    Returns:
        Shared CatalogMatcher instance.
    """
    global _matcher_instance
    if _matcher_instance is None:
        _matcher_instance = CatalogMatcher()
    return _matcher_instance
