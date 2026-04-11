"""Unit tests for the Fantastico Bulgaria PDF brochure scraper.

All HTTP calls and external dependencies are mocked — no live requests are made.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from app.scrapers.fantastico import FantasticoScraper


@pytest.fixture
def scraper() -> FantasticoScraper:
    """A fresh FantasticoScraper instance."""
    return FantasticoScraper()


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


def _soup(html: str) -> BeautifulSoup:
    """Parse inline HTML into a BeautifulSoup tree."""
    return BeautifulSoup(html, "lxml")


# ------------------------------------------------------------------
# TestStoreSlug
# ------------------------------------------------------------------


class TestStoreSlug:
    """Verify the scraper identifies itself correctly."""

    def test_store_slug_is_fantastico(self, scraper: FantasticoScraper) -> None:
        """store_slug must be 'fantastico'."""
        assert scraper.store_slug == "fantastico"


# ------------------------------------------------------------------
# TestExtractDirectPdfLinks
# ------------------------------------------------------------------


class TestExtractDirectPdfLinks:
    """Tests for FantasticoScraper._extract_direct_pdf_links."""

    def test_finds_href_ending_in_pdf(self) -> None:
        """Anchor with href ending in .pdf must be returned."""
        html = '<a href="https://example.com/brochure.pdf">Download</a>'
        result = FantasticoScraper._extract_direct_pdf_links(_soup(html))
        assert result == ["https://example.com/brochure.pdf"]

    def test_finds_uppercase_pdf_extension(self) -> None:
        """Anchor with href ending in .PDF (uppercase) must be found."""
        html = '<a href="https://example.com/brochure.PDF">Download</a>'
        result = FantasticoScraper._extract_direct_pdf_links(_soup(html))
        assert result == ["https://example.com/brochure.PDF"]

    def test_finds_pdf_with_query_string(self) -> None:
        """Anchor href containing .pdf? (with query params) must be found."""
        html = '<a href="https://example.com/brochure.pdf?token=abc">Download</a>'
        result = FantasticoScraper._extract_direct_pdf_links(_soup(html))
        assert result == ["https://example.com/brochure.pdf?token=abc"]

    def test_returns_empty_when_no_pdf_links(self) -> None:
        """Page with no PDF anchors must return an empty list."""
        html = '<a href="https://example.com/page.html">Visit</a>'
        result = FantasticoScraper._extract_direct_pdf_links(_soup(html))
        assert result == []

    def test_ignores_relative_pdf_links(self) -> None:
        """Relative hrefs (non-http) must not be included."""
        html = '<a href="/downloads/brochure.pdf">Download</a>'
        result = FantasticoScraper._extract_direct_pdf_links(_soup(html))
        assert result == []

    def test_returns_multiple_pdf_links(self) -> None:
        """All matching PDF anchors on a page must be returned."""
        html = (
            '<a href="https://cdn.example.com/a.pdf">A</a>'
            '<a href="https://cdn.example.com/b.pdf">B</a>'
        )
        result = FantasticoScraper._extract_direct_pdf_links(_soup(html))
        assert len(result) == 2
        assert "https://cdn.example.com/a.pdf" in result
        assert "https://cdn.example.com/b.pdf" in result


# ------------------------------------------------------------------
# TestExtractDataAttrPdfs
# ------------------------------------------------------------------


class TestExtractDataAttrPdfs:
    """Tests for FantasticoScraper._extract_data_attr_pdfs."""

    def test_finds_pdf_url_in_data_attribute(self) -> None:
        """Element with a data-* attr containing a PDF URL must be found."""
        html = '<div data-pdf-url="https://example.com/brochure.pdf"></div>'
        result = FantasticoScraper._extract_data_attr_pdfs(_soup(html))
        assert result == ["https://example.com/brochure.pdf"]

    def test_returns_empty_when_no_data_attrs_contain_pdf(self) -> None:
        """Page with no data-* PDF attrs must return empty list."""
        html = '<div data-category="food">Nothing here</div>'
        result = FantasticoScraper._extract_data_attr_pdfs(_soup(html))
        assert result == []

    def test_ignores_non_data_attributes(self) -> None:
        """Non data-* attributes containing PDF text must be ignored."""
        html = '<a href="https://example.com/brochure.pdf">Link</a>'
        result = FantasticoScraper._extract_data_attr_pdfs(_soup(html))
        assert result == []

    def test_finds_pdf_in_data_src_attribute(self) -> None:
        """data-src containing a PDF URL must be found."""
        html = '<div data-src="https://cdn.example.com/week.pdf?v=2"></div>'
        result = FantasticoScraper._extract_data_attr_pdfs(_soup(html))
        assert len(result) == 1
        assert "https://cdn.example.com/week.pdf" in result[0]


# ------------------------------------------------------------------
# TestExtractPdfUrlsByRegex
# ------------------------------------------------------------------


class TestExtractPdfUrlsByRegex:
    """Tests for FantasticoScraper._extract_pdf_urls_by_regex."""

    def test_finds_pdf_url_embedded_in_source(self) -> None:
        """PDF URL embedded in JavaScript or attribute text must be found."""
        source = 'var pdf = "https://cdn.example.com/brochure.pdf";'
        result = FantasticoScraper._extract_pdf_urls_by_regex(source)
        assert "https://cdn.example.com/brochure.pdf" in result

    def test_returns_empty_for_empty_string(self) -> None:
        """Empty source string must return empty list."""
        result = FantasticoScraper._extract_pdf_urls_by_regex("")
        assert result == []

    def test_finds_multiple_pdf_urls_in_source(self) -> None:
        """Multiple embedded PDF URLs must all be found."""
        source = (
            '"https://cdn.example.com/a.pdf" '
            '"https://cdn.example.com/b.pdf"'
        )
        result = FantasticoScraper._extract_pdf_urls_by_regex(source)
        assert len(result) == 2

    def test_returns_empty_when_no_pdf_in_source(self) -> None:
        """Source with no PDF URLs must return empty list."""
        source = "<html><body>No PDFs here</body></html>"
        result = FantasticoScraper._extract_pdf_urls_by_regex(source)
        assert result == []


# ------------------------------------------------------------------
# TestExtractViewerUrls
# ------------------------------------------------------------------


class TestExtractViewerUrls:
    """Tests for FantasticoScraper._extract_viewer_urls."""

    def test_finds_flippingbook_anchor(self) -> None:
        """Anchor linking to flippingbook.com must be returned."""
        html = '<a href="https://online.flippingbook.com/view/123">View</a>'
        result = FantasticoScraper._extract_viewer_urls(_soup(html), html)
        assert any("flippingbook.com" in u for u in result)

    def test_finds_publitas_iframe_src(self) -> None:
        """Iframe with a publitas.com src must be returned."""
        html = '<iframe src="https://view.publitas.com/foo/bar"></iframe>'
        result = FantasticoScraper._extract_viewer_urls(_soup(html), html)
        assert any("publitas.com" in u for u in result)

    def test_returns_empty_when_no_viewer_links(self) -> None:
        """Page with no viewer host links must return empty list."""
        html = '<a href="https://example.com/page">Visit</a>'
        result = FantasticoScraper._extract_viewer_urls(_soup(html), html)
        assert result == []

    def test_finds_issuu_url_in_source(self) -> None:
        """Issuu viewer URL embedded in source text must be returned."""
        html = '<p>See brochure at https://issuu.com/brand/docs/week12</p>'
        result = FantasticoScraper._extract_viewer_urls(_soup(html), html)
        assert any("issuu.com" in u for u in result)

    def test_deduplicates_viewer_urls(self) -> None:
        """The same viewer URL appearing in anchor and source must appear once."""
        html = (
            '<a href="https://online.flippingbook.com/view/999">View</a>'
            ' data: "https://online.flippingbook.com/view/999"'
        )
        result = FantasticoScraper._extract_viewer_urls(_soup(html), html)
        viewer_urls = [u for u in result if "flippingbook.com/view/999" in u]
        assert len(viewer_urls) == 1


# ------------------------------------------------------------------
# TestFetch
# ------------------------------------------------------------------


class TestFetch:
    """Tests for FantasticoScraper.fetch() with mocked httpx."""

    @pytest.mark.asyncio
    async def test_fetch_returns_pdf_item_from_direct_link(
        self, scraper: FantasticoScraper
    ) -> None:
        """Page with one direct PDF anchor must return a single-item list."""
        html = '<a href="https://cdn.fantastico.bg/brochure1.pdf">Brochure</a>'
        mock_client = _make_mock_client([_ok_response(html)])

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["pdf_url"] == "https://cdn.fantastico.bg/brochure1.pdf"
        assert result[0]["title"] == "Fantastico brochure 1"

    @pytest.mark.asyncio
    async def test_fetch_returns_multiple_pdfs(
        self, scraper: FantasticoScraper
    ) -> None:
        """Page with three distinct PDF anchors must return three items."""
        html = (
            '<a href="https://cdn.fantastico.bg/a.pdf">A</a>'
            '<a href="https://cdn.fantastico.bg/b.pdf">B</a>'
            '<a href="https://cdn.fantastico.bg/c.pdf">C</a>'
        )
        mock_client = _make_mock_client([_ok_response(html)])

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_fetch_caps_results_at_max_pdfs(
        self, scraper: FantasticoScraper
    ) -> None:
        """Fetch must return at most _MAX_PDFS=5 items even if more are found."""
        links = "".join(
            f'<a href="https://cdn.fantastico.bg/b{i}.pdf">B{i}</a>'
            for i in range(10)
        )
        html = f"<html><body>{links}</body></html>"
        mock_client = _make_mock_client([_ok_response(html)])

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) <= 5

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_non_200(
        self, scraper: FantasticoScraper
    ) -> None:
        """Non-200 response must return empty list without raising."""
        mock_client = _make_mock_client([_error_response(503)])

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_http_error(
        self, scraper: FantasticoScraper
    ) -> None:
        """httpx.HTTPError must be caught and return empty list."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_no_pdfs_found(
        self, scraper: FantasticoScraper
    ) -> None:
        """Page containing no PDF links or viewer URLs must return empty list."""
        html = "<html><body><p>No brochures here.</p></body></html>"
        mock_client = _make_mock_client([_ok_response(html)])

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_follows_viewer_url_to_extract_pdf(
        self, scraper: FantasticoScraper
    ) -> None:
        """Viewer URL on main page must be fetched; PDF inside viewer returned."""
        main_html = (
            '<a href="https://online.flippingbook.com/view/999">Brochure</a>'
        )
        viewer_html = (
            '<a href="https://cdn.fantastico.bg/weekly.pdf">Download PDF</a>'
        )
        mock_client = _make_mock_client(
            [_ok_response(main_html), _ok_response(viewer_html)]
        )

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        pdf_urls = [r["pdf_url"] for r in result]
        assert "https://cdn.fantastico.bg/weekly.pdf" in pdf_urls

    @pytest.mark.asyncio
    async def test_fetch_skips_viewer_on_http_error(
        self, scraper: FantasticoScraper
    ) -> None:
        """httpx.HTTPError fetching a viewer URL must be silently skipped."""
        import httpx

        main_html = (
            '<a href="https://online.flippingbook.com/view/999">Brochure</a>'
        )
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=[
                _ok_response(main_html),
                httpx.ConnectError("Viewer down"),
            ]
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        # Main page had no direct PDFs and viewer failed — expect empty list
        assert result == []


# ------------------------------------------------------------------
# TestParse
# ------------------------------------------------------------------


class TestParse:
    """Tests for FantasticoScraper.parse() with mocked settings and pdf_parser."""

    def _mock_settings(self, *, llm_enabled: bool = False) -> MagicMock:
        """Return a MagicMock Settings object."""
        s = MagicMock()
        s.LLM_PARSER_ENABLED = llm_enabled
        return s

    def test_parse_calls_pdf_parser_when_llm_disabled(
        self, scraper: FantasticoScraper
    ) -> None:
        """When LLM_PARSER_ENABLED=False, parse_pdf_brochure must be called."""
        from app.scrapers.pdf_parser import BrochureItem

        fake_item = BrochureItem(name="Домати", price=Decimal("2.99"))

        with (
            patch(
                "app.scrapers.fantastico.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.fantastico.parse_pdf_brochure",
                return_value=[fake_item],
            ) as mock_parse,
            patch(
                "app.scrapers.fantastico.brochure_items_to_scraped",
                return_value=[MagicMock()],
            ) as mock_convert,
        ):
            result = scraper.parse([{"pdf_url": "https://cdn.fantastico.bg/b.pdf"}])

        mock_parse.assert_called_once_with(
            "https://cdn.fantastico.bg/b.pdf", store_slug="fantastico"
        )
        mock_convert.assert_called_once()
        assert len(result) == 1

    def test_parse_returns_empty_list_for_empty_raw(
        self, scraper: FantasticoScraper
    ) -> None:
        """Empty raw list must return empty items list without calling any parser."""
        with patch(
            "app.scrapers.fantastico.get_settings",
            return_value=self._mock_settings(),
        ):
            result = scraper.parse([])

        assert result == []

    def test_parse_skips_entry_missing_pdf_url(
        self, scraper: FantasticoScraper
    ) -> None:
        """Entry without 'pdf_url' key must be silently skipped."""
        with (
            patch(
                "app.scrapers.fantastico.get_settings",
                return_value=self._mock_settings(),
            ),
            patch(
                "app.scrapers.fantastico.parse_pdf_brochure",
                return_value=[],
            ) as mock_parse,
        ):
            result = scraper.parse([{"title": "No URL here"}])

        mock_parse.assert_not_called()
        assert result == []

    def test_parse_logs_warning_and_continues_on_pdf_error(
        self, scraper: FantasticoScraper
    ) -> None:
        """Exception in parse_pdf_brochure must log a warning and return empty."""
        with (
            patch(
                "app.scrapers.fantastico.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.fantastico.parse_pdf_brochure",
                side_effect=ValueError("bad PDF"),
            ),
        ):
            result = scraper.parse([{"pdf_url": "https://cdn.fantastico.bg/bad.pdf"}])

        assert result == []

    def test_parse_aggregates_items_from_multiple_pdfs(
        self, scraper: FantasticoScraper
    ) -> None:
        """parse() must accumulate items from all entries in raw list."""
        from app.scrapers.base import ScrapedItem

        fake_scraped = ScrapedItem(name="Test", price=Decimal("1.00"))

        with (
            patch(
                "app.scrapers.fantastico.get_settings",
                return_value=self._mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.fantastico.parse_pdf_brochure",
                return_value=[MagicMock()],
            ),
            patch(
                "app.scrapers.fantastico.brochure_items_to_scraped",
                return_value=[fake_scraped],
            ),
        ):
            result = scraper.parse([
                {"pdf_url": "https://cdn.fantastico.bg/a.pdf"},
                {"pdf_url": "https://cdn.fantastico.bg/b.pdf"},
            ])

        assert len(result) == 2


# ------------------------------------------------------------------
# TestNormalise
# ------------------------------------------------------------------


class TestNormalise:
    """Verify normalisation works correctly with Fantastico items."""

    def test_normalise_strips_and_titlecases(
        self, scraper: FantasticoScraper
    ) -> None:
        """Normalisation must strip whitespace and title-case names."""
        from app.scrapers.base import ScrapedItem

        item = ScrapedItem(
            name="  домати български  ",
            price=Decimal("3.49"),
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

    def test_fantastico_in_registry(self) -> None:
        """FantasticoScraper must be in _SCRAPER_REGISTRY under 'fantastico'."""
        from app.scrapers.tasks import _SCRAPER_REGISTRY

        assert "fantastico" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["fantastico"] is FantasticoScraper
