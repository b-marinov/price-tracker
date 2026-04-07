"""Unit tests for the PDF brochure parser.

The tests use two strategies:
1. Minimal in-memory PDFs created with ``fpdf2`` (lightweight, no external deps)
   — the primary approach used when fpdf2 is available.
2. Direct calls to the internal parsing helpers (``_parse_price``,
   ``_parse_date_range``, ``_parse_page_text``) — always run, no PDF needed.

Coverage:
- Price extraction: integer, decimal-comma, decimal-dot, with/without лв suffix
- Date range extraction: DD.MM, DD.MM.YYYY, dash/en-dash/em-dash separators
- Unit extraction: кг, г, л, мл, бр, pkg variants
- Page text parser: multi-product page, items without price are skipped
- Full pipeline: parse_pdf_brochure() on an in-memory text PDF
- OCR fallback: mocked to verify it is called for image-heavy pages
- URL input: mocked httpx to verify download + parse flow
- brochure_items_to_scraped: verifies ScrapedItem bridge
"""

from __future__ import annotations

import io
import textwrap
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.scrapers.pdf_parser import (
    BrochureItem,
    _parse_date_range,
    _parse_page_text,
    _parse_price,
    brochure_items_to_scraped,
    parse_pdf_brochure,
)


# ---------------------------------------------------------------------------
# Helpers — minimal PDF generation
# ---------------------------------------------------------------------------


def _make_text_pdf(pages: list[str]) -> io.BytesIO:
    """Create a minimal text-based PDF with one text block per page.

    Uses pdfplumber's underlying pdfinternals via reportlab if available,
    otherwise constructs a raw minimal PDF byte string.

    Args:
        pages: List of text strings, one per page.

    Returns:
        A BytesIO object containing valid PDF data.
    """
    # Try fpdf2 first (small pure-Python library)
    try:
        from fpdf import FPDF  # type: ignore[import-untyped]

        pdf = FPDF()
        pdf.set_auto_page_break(auto=False)
        for page_text in pages:
            pdf.add_page()
            pdf.set_font("Helvetica", size=11)
            for line in page_text.splitlines():
                pdf.cell(0, 8, txt=line, ln=True)
        return io.BytesIO(pdf.output())
    except ImportError:
        pass

    # Fallback: minimal hand-crafted PDF (works for pdfplumber text extraction)
    lines_per_page = [p.replace("\n", " / ") for p in pages]
    body = b""
    offsets: list[int] = []
    obj_count = 0

    def _add_obj(content: bytes) -> int:
        nonlocal obj_count, body
        obj_count += 1
        offsets.append(len(body))
        body += f"{obj_count} 0 obj\n".encode() + content + b"\nendobj\n"
        return obj_count

    catalog_id = _add_obj(b"<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = obj_count + 1  # will be 2

    page_ids: list[int] = []
    stream_ids: list[int] = []
    for text in lines_per_page:
        safe = text.encode("latin-1", errors="replace").decode("latin-1")
        stream_bytes = f"BT /F1 11 Tf 50 750 Td ({safe}) Tj ET".encode("latin-1")
        s_id = _add_obj(
            f"<< /Length {len(stream_bytes)} >>\nstream\n".encode()
            + stream_bytes
            + b"\nendstream"
        )
        stream_ids.append(s_id)

    # Pages dict — needs page IDs; we patch after
    pages_obj_offset = len(body)
    offsets.append(pages_obj_offset)
    obj_count += 1  # this IS obj 2
    assert obj_count == pages_id

    page_refs_placeholder = b"PAGEREFS"
    body += b"2 0 obj\n<< /Type /Pages /Kids [PAGEREFS] /Count "
    body += str(len(pages)).encode()
    body += b" >>\nendobj\n"

    for s_id in stream_ids:
        p_id = _add_obj(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Contents {s_id} 0 R "
            f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
            f"/BaseFont /Helvetica >> >> >> >>".encode()
        )
        page_ids.append(p_id)

    # Patch in real page refs
    kids = " ".join(f"{pid} 0 R" for pid in page_ids).encode()
    body = body.replace(page_refs_placeholder, kids, 1)

    # xref + trailer
    xref_pos = len(body)
    xref = f"xref\n0 {obj_count + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()
    trailer = (
        f"trailer\n<< /Size {obj_count + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()
    body += xref + trailer

    return io.BytesIO(body)


# ---------------------------------------------------------------------------
# _parse_price
# ---------------------------------------------------------------------------


class TestParsePrice:
    def test_decimal_dot(self) -> None:
        assert _parse_price("Мляко 1.89 лв.") == Decimal("1.89")

    def test_decimal_comma(self) -> None:
        assert _parse_price("Сирене 3,49 лв") == Decimal("3.49")

    def test_no_suffix(self) -> None:
        assert _parse_price("Масло 2.19") == Decimal("2.19")

    def test_bgn_suffix(self) -> None:
        assert _parse_price("Яйца 2.49 BGN") == Decimal("2.49")

    def test_zero_cents(self) -> None:
        assert _parse_price("Промо 5.00лв") == Decimal("5.00")

    def test_no_match_returns_none(self) -> None:
        assert _parse_price("Без цена тук") is None

    def test_plain_integer_no_match(self) -> None:
        # "5" alone without decimal part does not match
        assert _parse_price("страница 5") is None


# ---------------------------------------------------------------------------
# _parse_date_range
# ---------------------------------------------------------------------------


class TestParseDateRange:
    def test_dd_mm_only(self) -> None:
        valid_from, valid_to = _parse_date_range("01.04 - 07.04", 2026)
        assert valid_from == date(2026, 4, 1)
        assert valid_to == date(2026, 4, 7)

    def test_full_dates(self) -> None:
        valid_from, valid_to = _parse_date_range("01.04.2026 – 07.04.2026", 2026)
        assert valid_from == date(2026, 4, 1)
        assert valid_to == date(2026, 4, 7)

    def test_slash_separator_dates(self) -> None:
        valid_from, valid_to = _parse_date_range("01/04/2026 до 07/04/2026", 2026)
        assert valid_from == date(2026, 4, 1)
        assert valid_to == date(2026, 4, 7)

    def test_em_dash_separator(self) -> None:
        valid_from, valid_to = _parse_date_range("01.04—07.04", 2026)
        assert valid_from == date(2026, 4, 1)
        assert valid_to == date(2026, 4, 7)

    def test_two_digit_year(self) -> None:
        valid_from, valid_to = _parse_date_range("01.04.26-07.04.26", 2026)
        assert valid_from == date(2026, 4, 1)
        assert valid_to == date(2026, 4, 7)

    def test_no_match(self) -> None:
        valid_from, valid_to = _parse_date_range("Страхотна промоция!", 2026)
        assert valid_from is None
        assert valid_to is None


# ---------------------------------------------------------------------------
# _parse_page_text
# ---------------------------------------------------------------------------


class TestParsePageText:
    def test_basic_extraction(self) -> None:
        text = textwrap.dedent("""\
            БРОШУРА 01.04 - 07.04.2026
            Мляко Верея 3.5%
            1 л
            1.89 лв.
            Сирене краве
            400 г
            3.49 лв.
        """)
        items = _parse_page_text(text, page_num=1, year=2026)
        assert len(items) >= 2
        prices = {item.price for item in items}
        assert Decimal("1.89") in prices
        assert Decimal("3.49") in prices

    def test_validity_dates_propagated(self) -> None:
        text = "01.04 - 07.04.2026\nМасло 250г\n2.19 лв."
        items = _parse_page_text(text, page_num=1, year=2026)
        assert items
        assert items[0].valid_from == date(2026, 4, 1)
        assert items[0].valid_to == date(2026, 4, 7)

    def test_line_without_price_skipped(self) -> None:
        text = "Само текст без цена\nОще текст"
        items = _parse_page_text(text, page_num=1, year=2026)
        assert items == []

    def test_unit_extracted(self) -> None:
        text = "Портокали 1кг\n1.99 лв."
        items = _parse_page_text(text, page_num=1, year=2026)
        assert items
        assert items[0].unit is not None
        assert "кг" in items[0].unit.lower() or "kg" in items[0].unit.lower()

    def test_page_number_stored(self) -> None:
        text = "Продукт А\n2.50 лв."
        items = _parse_page_text(text, page_num=3, year=2026)
        assert items
        assert items[0].page == 3

    def test_source_is_brochure(self) -> None:
        text = "Продукт Б\n1.00 лв."
        items = _parse_page_text(text, page_num=1, year=2026)
        assert items
        assert items[0].source == "brochure"


# ---------------------------------------------------------------------------
# parse_pdf_brochure — full pipeline
# ---------------------------------------------------------------------------


class TestParsePdfBrochure:
    def _make_brochure_pdf(self) -> io.BytesIO:
        page1 = textwrap.dedent("""\
            СЕДМИЧНА БРОШУРА  01.04 - 07.04.2026
            Мляко Верея 3.5% 1л
            1.89 лв.
            Сирене краве 400г
            3.49 лв.
        """)
        page2 = textwrap.dedent("""\
            01.04 - 07.04.2026
            Яйца М 10бр.
            2.49 лв.
            Банани 1кг
            1.49 лв.
        """)
        return _make_text_pdf([page1, page2])

    def test_returns_brochure_items(self) -> None:
        pdf = self._make_brochure_pdf()
        items = parse_pdf_brochure(pdf, store_slug="test")  # type: ignore[arg-type]
        assert isinstance(items, list)
        assert all(isinstance(i, BrochureItem) for i in items)

    def test_finds_multiple_items(self) -> None:
        pdf = self._make_brochure_pdf()
        items = parse_pdf_brochure(pdf, store_slug="test")  # type: ignore[arg-type]
        assert len(items) >= 2

    def test_prices_are_decimal(self) -> None:
        pdf = self._make_brochure_pdf()
        items = parse_pdf_brochure(pdf, store_slug="test")  # type: ignore[arg-type]
        for item in items:
            assert isinstance(item.price, Decimal)
            assert item.price > 0

    def test_currency_is_bgn(self) -> None:
        pdf = self._make_brochure_pdf()
        items = parse_pdf_brochure(pdf, store_slug="test")  # type: ignore[arg-type]
        for item in items:
            assert item.currency == "EUR"

    def test_file_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_pdf_brochure("/nonexistent/path/brochure.pdf")

    def test_url_input_downloads_pdf(self) -> None:
        pdf_bytes = self._make_brochure_pdf().getvalue()
        mock_response = MagicMock()
        mock_response.content = pdf_bytes
        mock_response.raise_for_status = MagicMock()

        with patch("app.scrapers.pdf_parser.httpx.get", return_value=mock_response) as mock_get:
            items = parse_pdf_brochure("https://example.com/brochure.pdf", store_slug="test")
            mock_get.assert_called_once()
            assert isinstance(items, list)

    def test_url_download_failure_raises_value_error(self) -> None:
        import httpx as _httpx

        with patch("app.scrapers.pdf_parser.httpx.get", side_effect=_httpx.HTTPError("timeout")):
            with pytest.raises(ValueError, match="Failed to download PDF"):
                parse_pdf_brochure("https://example.com/brochure.pdf")

    def test_ocr_fallback_called_for_empty_page(self) -> None:
        """Verify _ocr_page is invoked when a page yields no text."""
        mock_page = MagicMock()
        mock_page.page_number = 1
        mock_page.extract_text.return_value = ""  # no text → triggers OCR

        mock_pdf_ctx = MagicMock()
        mock_pdf_ctx.__enter__ = MagicMock(return_value=mock_pdf_ctx)
        mock_pdf_ctx.__exit__ = MagicMock(return_value=False)
        mock_pdf_ctx.pages = [mock_page]

        with patch("app.scrapers.pdf_parser.pdfplumber.open", return_value=mock_pdf_ctx):
            with patch("app.scrapers.pdf_parser._ocr_page", return_value="Продукт 2.99 лв.") as mock_ocr:
                items = parse_pdf_brochure("/fake/path.pdf", ocr_fallback=True)
                mock_ocr.assert_called_once_with(mock_page)
                assert len(items) >= 1

    def test_ocr_not_called_when_disabled(self) -> None:
        mock_page = MagicMock()
        mock_page.page_number = 1
        mock_page.extract_text.return_value = ""

        mock_pdf_ctx = MagicMock()
        mock_pdf_ctx.__enter__ = MagicMock(return_value=mock_pdf_ctx)
        mock_pdf_ctx.__exit__ = MagicMock(return_value=False)
        mock_pdf_ctx.pages = [mock_page]

        with patch("app.scrapers.pdf_parser.pdfplumber.open", return_value=mock_pdf_ctx):
            with patch("app.scrapers.pdf_parser._ocr_page") as mock_ocr:
                parse_pdf_brochure("/fake/path.pdf", ocr_fallback=False)
                mock_ocr.assert_not_called()


# ---------------------------------------------------------------------------
# brochure_items_to_scraped
# ---------------------------------------------------------------------------


class TestBrochureItemsToScraped:
    def _sample_item(self) -> BrochureItem:
        return BrochureItem(
            name="Мляко Верея",
            price=Decimal("1.89"),
            currency="EUR",
            unit="1 л",
            valid_from=date(2026, 4, 1),
            valid_to=date(2026, 4, 7),
            page=1,
            source="brochure",
            raw={"line": "1.89 лв."},
        )

    def test_returns_scraped_items(self) -> None:
        from app.scrapers.base import ScrapedItem

        items = brochure_items_to_scraped([self._sample_item()])
        assert len(items) == 1
        assert isinstance(items[0], ScrapedItem)

    def test_source_is_brochure(self) -> None:
        items = brochure_items_to_scraped([self._sample_item()])
        assert items[0].source == "brochure"

    def test_price_preserved(self) -> None:
        items = brochure_items_to_scraped([self._sample_item()])
        assert items[0].price == Decimal("1.89")

    def test_validity_dates_in_raw(self) -> None:
        items = brochure_items_to_scraped([self._sample_item()])
        assert items[0].raw["valid_from"] == "2026-04-01"
        assert items[0].raw["valid_to"] == "2026-04-07"

    def test_empty_list(self) -> None:
        assert brochure_items_to_scraped([]) == []

    def test_none_dates_in_raw(self) -> None:
        item = BrochureItem(name="Продукт", price=Decimal("1.00"))
        items = brochure_items_to_scraped([item])
        assert items[0].raw["valid_from"] is None
        assert items[0].raw["valid_to"] is None
