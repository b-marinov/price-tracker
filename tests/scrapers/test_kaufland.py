"""Unit tests for the Kaufland Bulgaria PDF brochure scraper.

All HTTP calls and external dependencies are mocked — no live requests are made.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.kaufland import KauflandScraper


@pytest.fixture
def scraper() -> KauflandScraper:
    """A fresh KauflandScraper instance."""
    return KauflandScraper()


def _ok_response(html: str) -> MagicMock:
    """Return a mock 200 response with the given HTML body."""
    resp = MagicMock()
    resp.status_code = 200
    resp.text = html
    return resp


def _error_response(status: int = 503) -> MagicMock:
    """Return a mock non-200 response."""
    resp = MagicMock()
    resp.status_code = status
    resp.text = "Error"
    return resp


def _make_mock_client(responses: list[MagicMock]) -> AsyncMock:
    """Build a mocked async httpx client that returns *responses* in order."""
    mock_client = AsyncMock()
    if len(responses) == 1:
        mock_client.get = AsyncMock(return_value=responses[0])
    else:
        mock_client.get = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


_PDF_URL = "https://cdn.kaufland.bg/brochures/weekly-brochure.pdf"

# Brochures listing page with a single m-flyer-tile element.
_BROCHURES_PAGE_HTML = (
    '<html><body>'
    '<div class="m-flyer-tile"'
    ' data-parameter="aktualna-broshura"'
    f' data-download-url="{_PDF_URL}"'
    ' data-aa-detail="Kaufland weekly brochure">'
    '</div>'
    '</body></html>'
)

# Page with a non-preferred tile only (no aktualna-broshura).
_BROCHURES_PAGE_FALLBACK_HTML = (
    '<html><body>'
    '<div class="m-flyer-tile"'
    ' data-parameter="other-brochure"'
    f' data-download-url="{_PDF_URL}"'
    ' data-aa-detail="Other brochure">'
    '</div>'
    '</body></html>'
)


# ------------------------------------------------------------------
# TestStoreSlug
# ------------------------------------------------------------------


class TestStoreSlug:
    """Verify the scraper identifies itself correctly."""

    def test_store_slug_is_kaufland(self, scraper: KauflandScraper) -> None:
        """store_slug must be 'kaufland'."""
        assert scraper.store_slug == "kaufland"


# ------------------------------------------------------------------
# TestFetch
# ------------------------------------------------------------------


class TestFetch:
    """Tests for KauflandScraper.fetch() with mocked httpx."""

    @pytest.mark.asyncio
    async def test_fetch_happy_path_returns_pdf_item(
        self, scraper: KauflandScraper
    ) -> None:
        """Happy path: brochures page with aktualna-broshura tile returns PDF URL."""
        mock_client = _make_mock_client([_ok_response(_BROCHURES_PAGE_HTML)])

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["pdf_url"] == _PDF_URL
        assert result[0]["title"] == "Kaufland weekly brochure"

    @pytest.mark.asyncio
    async def test_fetch_falls_back_to_first_tile(
        self, scraper: KauflandScraper
    ) -> None:
        """When preferred tile absent, first available tile is used."""
        mock_client = _make_mock_client([_ok_response(_BROCHURES_PAGE_FALLBACK_HTML)])

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["pdf_url"] == _PDF_URL

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_non_200(
        self, scraper: KauflandScraper
    ) -> None:
        """Non-200 response from brochures page must return empty list."""
        mock_client = _make_mock_client([_error_response(503)])

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_no_tiles(
        self, scraper: KauflandScraper
    ) -> None:
        """Page with no m-flyer-tile elements must return empty list."""
        html = "<html><body><p>No tiles here.</p></body></html>"
        mock_client = _make_mock_client([_ok_response(html)])

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_tile_missing_download_url(
        self, scraper: KauflandScraper
    ) -> None:
        """Tile without data-download-url attribute must return empty list."""
        html = (
            '<html><body>'
            '<div class="m-flyer-tile" data-parameter="aktualna-broshura">'
            '</div>'
            '</body></html>'
        )
        mock_client = _make_mock_client([_ok_response(html)])

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_http_error(
        self, scraper: KauflandScraper
    ) -> None:
        """httpx.HTTPError must be caught and return empty list."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []


# ------------------------------------------------------------------
# TestParse
# ------------------------------------------------------------------


class TestParse:
    """Tests for KauflandScraper.parse() with mocked settings and parsers."""

    def _mock_settings(self, *, llm_enabled: bool = False) -> MagicMock:
        """Return a MagicMock Settings object."""
        s = MagicMock()
        s.LLM_PARSER_ENABLED = llm_enabled
        s.LLM_OLLAMA_HOST = "http://localhost:11434"
        s.LLM_MODEL = "gemma4:e4b"
        s.LLM_TEMPERATURE = 0.0
        s.LLM_TIMEOUT_SECONDS = 120
        s.LLM_PAGE_DPI = 150
        return s

    def test_parse_calls_pdf_parser_when_llm_disabled(
        self, scraper: KauflandScraper
    ) -> None:
        """When LLM_PARSER_ENABLED=False, parse_pdf_brochure must be called."""
        from app.scrapers.pdf_parser import BrochureItem

        fake_item = BrochureItem(name="Банани", price=Decimal("2.49"))

        with (
            patch(
                "app.scrapers.kaufland.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.kaufland.parse_pdf_brochure",
                return_value=[fake_item],
            ) as mock_parse,
            patch(
                "app.scrapers.kaufland.brochure_items_to_scraped",
                return_value=[MagicMock()],
            ) as mock_convert,
        ):
            result = scraper.parse([{"pdf_url": _PDF_URL, "title": "Kaufland"}])

        mock_parse.assert_called_once_with(_PDF_URL, store_slug="kaufland")
        mock_convert.assert_called_once()
        assert len(result) == 1

    def test_parse_returns_empty_for_empty_raw(
        self, scraper: KauflandScraper
    ) -> None:
        """Empty raw list must return empty items list."""
        with patch(
            "app.scrapers.kaufland.get_settings",
            return_value=self._mock_settings(),
        ):
            result = scraper.parse([])

        assert result == []

    def test_parse_skips_entry_missing_pdf_url(
        self, scraper: KauflandScraper
    ) -> None:
        """Entry without 'pdf_url' key must be silently skipped."""
        with (
            patch(
                "app.scrapers.kaufland.get_settings",
                return_value=self._mock_settings(),
            ),
            patch(
                "app.scrapers.kaufland.parse_pdf_brochure",
                return_value=[],
            ) as mock_parse,
        ):
            result = scraper.parse([{"title": "No URL here"}])

        mock_parse.assert_not_called()
        assert result == []

    def test_parse_logs_warning_and_continues_on_pdf_error(
        self, scraper: KauflandScraper
    ) -> None:
        """Exception from parse_pdf_brochure must be caught; remaining entries processed."""
        with (
            patch(
                "app.scrapers.kaufland.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.kaufland.parse_pdf_brochure",
                side_effect=ValueError("corrupted PDF"),
            ),
        ):
            result = scraper.parse([{"pdf_url": _PDF_URL}])

        assert result == []

    def test_parse_aggregates_items_from_multiple_entries(
        self, scraper: KauflandScraper
    ) -> None:
        """parse() must accumulate items from all entries in the raw list."""
        from app.scrapers.base import ScrapedItem

        fake_scraped = ScrapedItem(name="Кисело мляко", price=Decimal("1.29"))

        with (
            patch(
                "app.scrapers.kaufland.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.kaufland.parse_pdf_brochure",
                return_value=[MagicMock()],
            ),
            patch(
                "app.scrapers.kaufland.brochure_items_to_scraped",
                return_value=[fake_scraped],
            ),
        ):
            result = scraper.parse([
                {"pdf_url": _PDF_URL},
                {"pdf_url": "https://cdn.kaufland.bg/brochures/alt.pdf"},
            ])

        assert len(result) == 2


# ------------------------------------------------------------------
# TestNormalise
# ------------------------------------------------------------------


class TestNormalise:
    """Verify normalisation works correctly with Kaufland items."""

    def test_normalise_strips_and_titlecases(
        self, scraper: KauflandScraper
    ) -> None:
        """Normalise must strip whitespace and title-case names."""
        from app.scrapers.base import ScrapedItem

        item = ScrapedItem(
            name="  бял хляб нарязан  ",
            price=Decimal("1.29"),
            unit=" бр ",
        )
        result = scraper.normalise(item)
        assert result.name == "Бял Хляб Нарязан"
        assert result.unit == "бр"
        assert result.currency == "EUR"


# ------------------------------------------------------------------
# TestRegistry
# ------------------------------------------------------------------


class TestRegistry:
    """Verify the scraper is registered in the task registry."""

    def test_kaufland_in_registry(self) -> None:
        """KauflandScraper must be in _SCRAPER_REGISTRY under 'kaufland'."""
        from app.scrapers.tasks import _SCRAPER_REGISTRY

        assert "kaufland" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["kaufland"] is KauflandScraper
