"""PDF brochure parser for extracting product prices from store flyers.

Uses pdfplumber for text-based PDFs.  Falls back to pytesseract OCR for
pages that yield no extractable text (image-heavy / scanned PDFs).

Supported input: local file path or HTTP(S) URL.
Output: list of :class:`ScrapedItem` with ``source="brochure"``.

Bulgarian text is handled transparently by pdfplumber (UTF-8) and by
passing ``lang="bul"`` to Tesseract when OCR is needed.

Dependencies (added to pyproject.toml):
- pdfplumber>=0.11.0
- pytesseract>=0.3.10
- Pillow>=10.0.0
"""

from __future__ import annotations

import io
import logging
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pdfplumber

if TYPE_CHECKING:
    import pdfplumber as _pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public dataclass — extends ScrapedItem with brochure-specific fields
# ---------------------------------------------------------------------------


@dataclass
class BrochureItem:
    """A single product offer extracted from a store brochure PDF.

    Attributes:
        name: Product display name as printed in the brochure.
        price: Promotional price as a fixed-point decimal.
        currency: ISO 4217 code (always BGN for Bulgarian brochures).
        unit: Unit descriptor if present (e.g. "кг", "л", "бр").
        valid_from: Start date of the promotional period (if found).
        valid_to: End date of the promotional period (if found).
        page: 1-based page number in the source PDF.
        source: Always "brochure".
        raw: Raw extracted text block for debugging.
    """

    name: str
    price: Decimal
    currency: str = "BGN"
    unit: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    page: int = 1
    source: str = "brochure"
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Regex patterns for Bulgarian price / date extraction
# ---------------------------------------------------------------------------

# Matches: "1.99", "12,50", "1 99", "0.79 лв", "2,49лв.", "3.00 BGN"
_PRICE_RE = re.compile(
    r"(\d{1,4})[.,\s](\d{2})\s*(?:лв\.?|bgn|лева)?",
    re.IGNORECASE,
)

# Matches: "01.04 - 07.04", "1.04–7.04.2026", "01/04/2026 до 07/04/2026"
_DATE_RANGE_RE = re.compile(
    r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?"
    r"\s*[-–—до]+\s*"
    r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?",
    re.IGNORECASE,
)

# Matches unit strings embedded in product text
_UNIT_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?\s*(?:кг|г|л|мл|бр|пак|kg|g|l|ml|pc|pcs)\.?)\b",
    re.IGNORECASE,
)

# Minimum characters a line must have to be a candidate product name
_MIN_NAME_LEN = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_price(text: str) -> Decimal | None:
    """Extract the first price-like pattern from *text*.

    Args:
        text: Raw text string from a PDF page or OCR result.

    Returns:
        A :class:`~decimal.Decimal` price, or ``None`` if no pattern matched.
    """
    match = _PRICE_RE.search(text)
    if not match:
        return None
    integer_part, decimal_part = match.group(1), match.group(2)
    try:
        return Decimal(f"{integer_part}.{decimal_part}")
    except InvalidOperation:
        return None


def _parse_date_range(text: str, year: int) -> tuple[date | None, date | None]:
    """Extract a promotional validity date range from *text*.

    If the year is not explicitly stated in the text the supplied *year*
    is used as the default.

    Args:
        text: Raw text to search for a date range pattern.
        year: Default year to use when not present in the pattern.

    Returns:
        A ``(valid_from, valid_to)`` tuple; either value may be ``None``
        if parsing fails.
    """
    match = _DATE_RANGE_RE.search(text)
    if not match:
        return None, None

    d1, m1, y1, d2, m2, y2 = match.groups()
    try:
        from_year = int(y1) if y1 else year
        to_year = int(y2) if y2 else year
        # Handle 2-digit years
        if from_year < 100:
            from_year += 2000
        if to_year < 100:
            to_year += 2000
        valid_from = date(from_year, int(m1), int(d1))
        valid_to = date(to_year, int(m2), int(d2))
        return valid_from, valid_to
    except (ValueError, TypeError):
        return None, None


def _extract_unit(text: str) -> str | None:
    """Pull a unit descriptor from a product text line.

    Args:
        text: A single product text line.

    Returns:
        The unit string (e.g. ``"1 кг"``), or ``None`` if not found.
    """
    match = _UNIT_RE.search(text)
    return match.group(1).strip() if match else None


def _ocr_page(page: Any) -> str:
    """Render a pdfplumber page to an image and run Tesseract OCR on it.

    Called only when ``page.extract_text()`` returns no usable content.

    Args:
        page: A ``pdfplumber.Page`` instance.

    Returns:
        The OCR'd text string (may be empty on failure).
    """
    try:
        import pytesseract
        from PIL import Image

        # Render page at 200 DPI to a PIL image
        img = page.to_image(resolution=200).original
        if not isinstance(img, Image.Image):
            img = Image.fromarray(img)  # type: ignore[arg-type]
        text: str = pytesseract.image_to_string(img, lang="bul+eng")
        return text
    except Exception as exc:  # noqa: BLE001
        logger.warning("OCR failed on page %d: %s", page.page_number, exc)
        return ""


def _parse_page_text(text: str, page_num: int, year: int) -> list[BrochureItem]:
    """Extract BrochureItems from the raw text of a single PDF page.

    The parser uses a sliding-window heuristic:
    1. Split text into non-empty lines.
    2. For each line containing a price pattern, treat that line (and up to
       two preceding lines) as the product name block.
    3. Extract unit from the same text block.
    4. Look for a date range in any line on the same page.

    This handles the common two-column brochure layout where the product
    name appears above the price line.

    Args:
        text: Full extracted text of one PDF page.
        page_num: 1-based page number (stored in BrochureItem.page).
        year: Default year to use when date range year is absent.

    Returns:
        A list of :class:`BrochureItem` objects found on this page.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []

    # Detect a date range for the whole page (brochures usually have one)
    page_text = " ".join(lines)
    valid_from, valid_to = _parse_date_range(page_text, year)

    items: list[BrochureItem] = []

    for i, line in enumerate(lines):
        price = _parse_price(line)
        if price is None:
            continue

        # Collect candidate name lines: the current line + up to 2 above it
        name_lines = [lines[j] for j in range(max(0, i - 2), i + 1)]
        # Remove lines that are purely numeric or very short
        name_lines = [
            ln for ln in name_lines
            if len(ln) >= _MIN_NAME_LEN and not re.fullmatch(r"[\d\s.,]+", ln)
        ]
        if not name_lines:
            continue

        name = " ".join(name_lines).strip()
        # Strip the price portion from the name if it leaked in
        name = _PRICE_RE.sub("", name).strip(" -–—·•")
        if len(name) < _MIN_NAME_LEN:
            continue

        unit = _extract_unit(line) or _extract_unit(name)
        # Remove unit from name to avoid duplication
        if unit:
            name = _UNIT_RE.sub("", name).strip()

        items.append(
            BrochureItem(
                name=name,
                price=price,
                currency="BGN",
                unit=unit,
                valid_from=valid_from,
                valid_to=valid_to,
                page=page_num,
                source="brochure",
                raw={"line": line, "name_lines": name_lines},
            )
        )

    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_pdf_brochure(
    source: str | Path,
    store_slug: str = "unknown",
    *,
    ocr_fallback: bool = True,
) -> list[BrochureItem]:
    """Parse a PDF brochure and extract all product price offers.

    Accepts a local file path or an HTTP(S) URL.  For URL inputs the PDF
    is streamed into memory using ``httpx`` (sync).

    For each page:
    * If ``pdfplumber`` extracts ≥ 10 characters of text, use text parsing.
    * Otherwise (image-heavy / scanned page), fall back to pytesseract OCR
      if *ocr_fallback* is ``True``.

    Args:
        source: Local ``Path`` / path string, or an ``https://`` URL.
        store_slug: Identifying slug of the store (used in logging only).
        ocr_fallback: Whether to attempt OCR on image-heavy pages.

    Returns:
        A list of :class:`BrochureItem` objects, one per detected offer.

    Raises:
        ValueError: If *source* is a URL and the download fails.
        FileNotFoundError: If *source* is a path that does not exist.
    """
    from datetime import date as _date

    source = str(source)
    year = _date.today().year

    # --- Acquire PDF bytes ---
    if source.startswith(("http://", "https://")):
        logger.info("Downloading brochure PDF from %s", source)
        try:
            response = httpx.get(source, follow_redirects=True, timeout=60)
            response.raise_for_status()
            pdf_bytes = io.BytesIO(response.content)
        except httpx.HTTPError as exc:
            raise ValueError(f"Failed to download PDF from {source!r}: {exc}") from exc
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        pdf_bytes = path  # type: ignore[assignment]  # pdfplumber accepts Path

    # --- Parse pages ---
    all_items: list[BrochureItem] = []

    with pdfplumber.open(pdf_bytes) as pdf:
        logger.info(
            "Parsing brochure for %s — %d page(s)", store_slug, len(pdf.pages)
        )

        for page in pdf.pages:
            page_num: int = page.page_number
            text: str = page.extract_text() or ""

            if len(text.strip()) < 10:
                if ocr_fallback:
                    logger.debug(
                        "Page %d has little text — trying OCR", page_num
                    )
                    text = _ocr_page(page)
                else:
                    logger.debug("Page %d skipped (no text, OCR disabled)", page_num)
                    continue

            page_items = _parse_page_text(text, page_num, year)
            logger.debug("Page %d: found %d item(s)", page_num, len(page_items))
            all_items.extend(page_items)

    logger.info(
        "Brochure parse complete for %s — %d item(s) total",
        store_slug,
        len(all_items),
    )
    return all_items


def brochure_items_to_scraped(items: list[BrochureItem]) -> list[Any]:
    """Convert :class:`BrochureItem` objects to :class:`ScrapedItem` format.

    This bridges the brochure parser output to the existing scraper pipeline
    so brochure items can flow through the same normalisation and upsert path
    as web-scraped items.

    Args:
        items: Output of :func:`parse_pdf_brochure`.

    Returns:
        A list of :class:`~app.scrapers.base.ScrapedItem` instances.
    """
    from app.scrapers.base import ScrapedItem

    result: list[ScrapedItem] = []
    for item in items:
        raw: dict[str, Any] = {
            **item.raw,
            "page": item.page,
            "valid_from": item.valid_from.isoformat() if item.valid_from else None,
            "valid_to": item.valid_to.isoformat() if item.valid_to else None,
        }
        result.append(
            ScrapedItem(
                name=item.name,
                price=item.price,
                currency=item.currency,
                unit=item.unit,
                source="brochure",
                raw=raw,
            )
        )
    return result
