"""Unit tests for the Billa Bulgaria PDF brochure scraper.

All HTTP calls and external dependencies are mocked — no live requests are made.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.billa import BillaScraper


@pytest.fixture
def scraper() -> BillaScraper:
    """A fresh BillaScraper instance."""
    return BillaScraper()


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


# Canonical Billa brochure page HTML fixture — contains a Publitas viewer URL.
_BILLA_PAGE_HTML = """
<html>
<body>
  <iframe src="https://view.publitas.com/billa-bulgaria/week-15-2026/"></iframe>
</body>
</html>
"""

# Canonical Publitas viewer page — contains a direct PDF download URL.
_PUBLITAS_PAGE_HTML = """
<html>
<body>
  <a href="https://view.publitas.com/12345/67890/pdfs/billa-week-15.pdf">
    Download PDF
  </a>
</body>
</html>
"""

_EXPECTED_PDF_URL = (
    "https://view.publitas.com/12345/67890/pdfs/billa-week-15.pdf"
)
_EXPECTED_PUBLITAS_URL = "https://view.publitas.com/billa-bulgaria/week-15-2026"


# ------------------------------------------------------------------
# TestStoreSlug
# ------------------------------------------------------------------


class TestStoreSlug:
    """Verify the scraper identifies itself correctly."""

    def test_store_slug_is_billa(self, scraper: BillaScraper) -> None:
        """store_slug must be 'billa'."""
        assert scraper.store_slug == "billa"


# ------------------------------------------------------------------
# TestFetch
# ------------------------------------------------------------------


class TestFetch:
    """Tests for BillaScraper.fetch() with mocked httpx."""

    @pytest.mark.asyncio
    async def test_fetch_happy_path_returns_pdf_item(
        self, scraper: BillaScraper
    ) -> None:
        """Full happy path: Billa page → Publitas page → PDF URL returned."""
        mock_client = _make_mock_client(
            [_ok_response(_BILLA_PAGE_HTML), _ok_response(_PUBLITAS_PAGE_HTML)]
        )

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["pdf_url"] == _EXPECTED_PDF_URL
        assert result[0]["title"] == "Billa weekly brochure"

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_billa_page_non_200(
        self, scraper: BillaScraper
    ) -> None:
        """Non-200 from the Billa page must return empty list."""
        mock_client = _make_mock_client([_error_response(503)])

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_no_publitas_url(
        self, scraper: BillaScraper
    ) -> None:
        """Billa page without a Publitas viewer URL must return empty list."""
        html = "<html><body><p>No viewer here.</p></body></html>"
        mock_client = _make_mock_client([_ok_response(html)])

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_publitas_page_has_no_pdf(
        self, scraper: BillaScraper
    ) -> None:
        """Publitas page without a PDF download URL must return empty list."""
        publitas_no_pdf = "<html><body><p>No PDF link here.</p></body></html>"
        mock_client = _make_mock_client(
            [_ok_response(_BILLA_PAGE_HTML), _ok_response(publitas_no_pdf)]
        )

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_billa_http_error(
        self, scraper: BillaScraper
    ) -> None:
        """httpx.HTTPError fetching the Billa page must return empty list."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_publitas_http_error(
        self, scraper: BillaScraper
    ) -> None:
        """httpx.HTTPError fetching the Publitas page must return empty list."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok_response(_BILLA_PAGE_HTML),
                httpx.ConnectError("Publitas unreachable"),
            ]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_publitas_url_is_fetched_with_trailing_slash(
        self, scraper: BillaScraper
    ) -> None:
        """The Publitas base URL must be requested with a trailing slash appended."""
        mock_client = _make_mock_client(
            [_ok_response(_BILLA_PAGE_HTML), _ok_response(_PUBLITAS_PAGE_HTML)]
        )

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            await scraper.fetch()

        # Second call should be to the Publitas base URL + "/"
        calls = mock_client.get.call_args_list
        assert len(calls) == 2
        publitas_call_url: str = calls[1][0][0]
        assert publitas_call_url == _EXPECTED_PUBLITAS_URL + "/"


# ------------------------------------------------------------------
# TestParse
# ------------------------------------------------------------------


class TestParse:
    """Tests for BillaScraper.parse() with mocked settings and pdf_parser."""

    def _mock_settings(self, *, llm_enabled: bool = False) -> MagicMock:
        """Return a MagicMock Settings object."""
        s = MagicMock()
        s.LLM_PARSER_ENABLED = llm_enabled
        return s

    def test_parse_calls_pdf_parser_when_llm_disabled(
        self, scraper: BillaScraper
    ) -> None:
        """When LLM_PARSER_ENABLED=False, parse_pdf_brochure must be called."""
        from app.scrapers.pdf_parser import BrochureItem

        fake_item = BrochureItem(name="Прясно мляко", price=Decimal("2.49"))

        with (
            patch(
                "app.scrapers.billa.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.billa.parse_pdf_brochure",
                return_value=[fake_item],
            ) as mock_parse,
            patch(
                "app.scrapers.billa.brochure_items_to_scraped",
                return_value=[MagicMock()],
            ) as mock_convert,
        ):
            result = scraper.parse([{"pdf_url": _EXPECTED_PDF_URL}])

        mock_parse.assert_called_once_with(
            _EXPECTED_PDF_URL, store_slug="billa"
        )
        mock_convert.assert_called_once()
        assert len(result) == 1

    def test_parse_returns_empty_list_for_empty_raw(
        self, scraper: BillaScraper
    ) -> None:
        """Empty raw list must return empty items list without calling any parser."""
        with patch(
            "app.scrapers.billa.get_settings",
            return_value=self._mock_settings(),
        ):
            result = scraper.parse([])

        assert result == []

    def test_parse_skips_entry_missing_pdf_url(
        self, scraper: BillaScraper
    ) -> None:
        """Entry without 'pdf_url' key must be silently skipped."""
        with (
            patch(
                "app.scrapers.billa.get_settings",
                return_value=self._mock_settings(),
            ),
            patch(
                "app.scrapers.billa.parse_pdf_brochure",
                return_value=[],
            ) as mock_parse,
        ):
            result = scraper.parse([{"title": "No URL here"}])

        mock_parse.assert_not_called()
        assert result == []

    def test_parse_logs_warning_and_returns_empty_on_pdf_error(
        self, scraper: BillaScraper
    ) -> None:
        """Exception raised by parse_pdf_brochure must be caught and logged."""
        with (
            patch(
                "app.scrapers.billa.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.billa.parse_pdf_brochure",
                side_effect=ValueError("corrupted PDF"),
            ),
        ):
            result = scraper.parse([{"pdf_url": _EXPECTED_PDF_URL}])

        assert result == []

    def test_parse_aggregates_items_from_multiple_entries(
        self, scraper: BillaScraper
    ) -> None:
        """parse() must accumulate items from all entries in the raw list."""
        from app.scrapers.base import ScrapedItem

        fake_scraped = ScrapedItem(name="Кисело мляко", price=Decimal("1.29"))

        with (
            patch(
                "app.scrapers.billa.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.billa.parse_pdf_brochure",
                return_value=[MagicMock()],
            ),
            patch(
                "app.scrapers.billa.brochure_items_to_scraped",
                return_value=[fake_scraped],
            ),
        ):
            result = scraper.parse([
                {"pdf_url": _EXPECTED_PDF_URL},
                {"pdf_url": "https://view.publitas.com/12345/67890/pdfs/billa-alt.pdf"},
            ])

        assert len(result) == 2


# ------------------------------------------------------------------
# TestNormalise
# ------------------------------------------------------------------


class TestNormalise:
    """Verify normalisation works correctly with Billa items."""

    def test_normalise_strips_and_titlecases(
        self, scraper: BillaScraper
    ) -> None:
        """Normalise must strip whitespace and title-case names."""
        from app.scrapers.base import ScrapedItem

        item = ScrapedItem(
            name="  домати български  ",
            price=Decimal("3.99"),
            unit=" кг ",
        )
        result = scraper.normalise(item)
        assert result.name == "Домати Български"
        assert result.unit == "кг"
        assert result.currency == "EUR"


# ------------------------------------------------------------------
# TestRegistry
# ------------------------------------------------------------------


class TestRegistry:
    """Verify the scraper is registered in the task registry."""

    def test_billa_in_registry(self) -> None:
        """BillaScraper must be in _SCRAPER_REGISTRY under 'billa'."""
        from app.scrapers.tasks import _SCRAPER_REGISTRY

        assert "billa" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["billa"] is BillaScraper
