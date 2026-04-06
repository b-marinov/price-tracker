"""Unit tests for the Lidl Bulgaria scraper.

All HTTP calls are mocked — no live requests are made.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.lidl import LidlScraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(filename: str) -> str:
    """Load an HTML fixture file as a string."""
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


@pytest.fixture
def page1_html() -> str:
    """Fixture HTML for Lidl page 1 (5 products, has next-page link)."""
    return _load_fixture("lidl_page1.html")


@pytest.fixture
def page2_html() -> str:
    """Fixture HTML for Lidl page 2 (3 products, no next-page link)."""
    return _load_fixture("lidl_page2.html")


@pytest.fixture
def scraper() -> LidlScraper:
    """A fresh LidlScraper instance."""
    return LidlScraper()


# ------------------------------------------------------------------
# store_slug
# ------------------------------------------------------------------


class TestStoreSlug:
    """Verify the scraper identifies itself correctly."""

    def test_store_slug_is_lidl(self, scraper: LidlScraper) -> None:
        """Store slug must be 'lidl'."""
        assert scraper.store_slug == "lidl"


# ------------------------------------------------------------------
# parse()
# ------------------------------------------------------------------


class TestParse:
    """Tests for the parse method using fixture HTML."""

    def test_parse_page1_returns_five_items(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Page 1 fixture contains exactly 5 offer cards."""
        raw = [{"html": page1_html, "page": 1}]
        items = scraper.parse(raw)
        assert len(items) == 5

    def test_parse_page2_returns_three_items(
        self, scraper: LidlScraper, page2_html: str
    ) -> None:
        """Page 2 fixture contains exactly 3 offer cards."""
        raw = [{"html": page2_html, "page": 2}]
        items = scraper.parse(raw)
        assert len(items) == 3

    def test_parse_multiple_pages(
        self, scraper: LidlScraper, page1_html: str, page2_html: str
    ) -> None:
        """Parsing both pages should yield 8 items total."""
        raw = [
            {"html": page1_html, "page": 1},
            {"html": page2_html, "page": 2},
        ]
        items = scraper.parse(raw)
        assert len(items) == 8

    def test_parse_extracts_product_name(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Product names should be extracted from offer-card__title."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        names = [item.name for item in items]
        assert "Пилешко филе охладено" in names
        assert "Кисело мляко 2% 400г" in names

    def test_parse_extracts_correct_price(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Price should be parsed as Decimal from the pricebox."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        chicken = next(i for i in items if "Пилешко" in i.name)
        assert chicken.price == Decimal("11.99")

    def test_parse_extracts_unit(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Unit should be extracted from pricebox__unit span."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        chicken = next(i for i in items if "Пилешко" in i.name)
        assert chicken.unit == "кг"

    def test_parse_extracts_image_url(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Image URL should be extracted from img src attribute."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        chicken = next(i for i in items if "Пилешко" in i.name)
        assert chicken.image_url == "https://www.lidl.bg/images/offers/pilesko-file.jpg"

    def test_parse_extracts_data_src_image(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Product with data-src instead of src should still get image_url."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        tomatoes = next(i for i in items if "Домати" in i.name)
        assert tomatoes.image_url == "https://www.lidl.bg/images/offers/domati.jpg"

    def test_parse_extracts_validity_from(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Validity-from date should be extracted and stored in raw dict."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        chicken = next(i for i in items if "Пилешко" in i.name)
        assert chicken.raw["validity_from"] == "2026-04-01"

    def test_parse_extracts_validity_to(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Validity-to date should be extracted and stored in raw dict."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        chicken = next(i for i in items if "Пилешко" in i.name)
        assert chicken.raw["validity_to"] == "2026-04-07"

    def test_parse_missing_validity_dates(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Items without validity dates should not have those keys in raw."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        chocolate = next(i for i in items if "Шоколад" in i.name)
        assert "validity_from" not in chocolate.raw
        assert "validity_to" not in chocolate.raw

    def test_parse_sets_currency_bgn(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """All items should have currency set to BGN."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        assert all(item.currency == "EUR" for item in items)

    def test_parse_sets_source_web(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """All items should have source set to 'web'."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        assert all(item.source == "web" for item in items)

    def test_parse_empty_html(self, scraper: LidlScraper) -> None:
        """Empty HTML page should yield no items."""
        items = scraper.parse([{"html": "<html></html>", "page": 1}])
        assert items == []

    def test_parse_empty_list(self, scraper: LidlScraper) -> None:
        """Empty raw list should yield no items."""
        items = scraper.parse([])
        assert items == []

    def test_parse_skips_card_without_name(self, scraper: LidlScraper) -> None:
        """Offer card missing the title should be skipped."""
        html = """
        <article class="offer-card">
            <div class="pricebox">
                <span class="pricebox__price">1,00 лв.</span>
            </div>
        </article>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert items == []

    def test_parse_skips_card_without_price(self, scraper: LidlScraper) -> None:
        """Offer card missing the pricebox should be skipped."""
        html = """
        <article class="offer-card">
            <p class="offer-card__title">Тест продукт</p>
        </article>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert items == []

    def test_parse_price_without_lv_suffix(self, scraper: LidlScraper) -> None:
        """Price tag without лв. suffix should still parse correctly."""
        html = """
        <article class="offer-card">
            <p class="offer-card__title">Тест</p>
            <div class="pricebox">
                <span class="pricebox__price">5,50</span>
            </div>
        </article>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert len(items) == 1
        assert items[0].price == Decimal("5.50")


# ------------------------------------------------------------------
# fetch()
# ------------------------------------------------------------------


class TestFetch:
    """Tests for the fetch method with mocked httpx."""

    @pytest.mark.asyncio
    async def test_fetch_single_page_no_pagination(
        self, scraper: LidlScraper, page2_html: str
    ) -> None:
        """Page without next-page link should return only one page."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = page2_html

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.lidl.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["page"] == 1
        assert result[0]["html"] == page2_html

    @pytest.mark.asyncio
    async def test_fetch_follows_pagination(
        self, scraper: LidlScraper, page1_html: str, page2_html: str
    ) -> None:
        """Scraper should follow next-page links across multiple pages."""
        resp1 = MagicMock()
        resp1.status_code = 200
        resp1.text = page1_html

        resp2 = MagicMock()
        resp2.status_code = 200
        resp2.text = page2_html

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resp1, resp2])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.lidl.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 2
        assert result[0]["page"] == 1
        assert result[1]["page"] == 2

    @pytest.mark.asyncio
    async def test_fetch_stops_on_non_200(
        self, scraper: LidlScraper
    ) -> None:
        """Non-200 response should stop pagination without raising."""
        resp_fail = MagicMock()
        resp_fail.status_code = 503
        resp_fail.text = "Service Unavailable"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp_fail)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.lidl.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_stops_on_http_error(
        self, scraper: LidlScraper
    ) -> None:
        """httpx.HTTPError during request should stop pagination gracefully."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.lidl.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_respects_max_pages(
        self, scraper: LidlScraper, page1_html: str
    ) -> None:
        """Fetch should stop after _MAX_PAGES even if next-page links exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = page1_html  # always has a next-page link

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.lidl.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 10


# ------------------------------------------------------------------
# Pagination helpers
# ------------------------------------------------------------------


class TestPaginationHelper:
    """Tests for the _extract_next_page_url static method."""

    def test_extracts_absolute_next_page_url(self, page1_html: str) -> None:
        """Page 1 has an absolute next-page URL."""
        url = LidlScraper._extract_next_page_url(page1_html)
        assert url == "https://www.lidl.bg/c/sedmichni-predlozheniya?page=2"

    def test_returns_none_when_no_next_page(self, page2_html: str) -> None:
        """Page 2 has no next-page link."""
        url = LidlScraper._extract_next_page_url(page2_html)
        assert url is None

    def test_converts_relative_url_to_absolute(self) -> None:
        """Relative href should be converted to absolute lidl.bg URL."""
        html = '<a class="next-page" href="/c/sedmichni-predlozheniya?page=3">Next</a>'
        url = LidlScraper._extract_next_page_url(html)
        assert url == "https://www.lidl.bg/c/sedmichni-predlozheniya?page=3"

    def test_returns_none_for_empty_href(self) -> None:
        """Empty href attribute should return None."""
        html = '<a class="next-page" href="">Next</a>'
        url = LidlScraper._extract_next_page_url(html)
        assert url is None


# ------------------------------------------------------------------
# Validity date extraction
# ------------------------------------------------------------------


class TestValidityDates:
    """Tests for validity date extraction from offer cards."""

    def test_validity_dates_in_page2(
        self, scraper: LidlScraper, page2_html: str
    ) -> None:
        """Page 2 items with dates should have them in raw dict."""
        items = scraper.parse([{"html": page2_html, "page": 2}])
        banani = next(i for i in items if i.name == "Банани")
        assert banani.raw["validity_from"] == "2026-04-01"
        assert banani.raw["validity_to"] == "2026-04-07"

    def test_validity_dates_different_range(
        self, scraper: LidlScraper, page2_html: str
    ) -> None:
        """Butter item has different validity dates than other items."""
        items = scraper.parse([{"html": page2_html, "page": 2}])
        butter = next(i for i in items if "масло" in i.name.lower())
        assert butter.raw["validity_from"] == "2026-04-02"
        assert butter.raw["validity_to"] == "2026-04-08"


# ------------------------------------------------------------------
# normalise() (inherited from BaseScraper)
# ------------------------------------------------------------------


class TestNormalise:
    """Verify normalisation works correctly with Lidl items."""

    def test_normalise_strips_and_titlecases(
        self, scraper: LidlScraper
    ) -> None:
        """Normalise should strip whitespace and title-case names."""
        from app.scrapers.base import ScrapedItem

        item = ScrapedItem(
            name="  пилешко филе охладено  ",
            price=Decimal("11.99"),
            unit=" кг ",
        )
        result = scraper.normalise(item)
        assert result.name == "Пилешко Филе Охладено"
        assert result.unit == "кг"
        assert result.currency == "EUR"


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------


class TestRegistry:
    """Verify the scraper is registered in the task registry."""

    def test_lidl_in_registry(self) -> None:
        """LidlScraper must be registered under 'lidl' in the registry."""
        from app.scrapers.tasks import _SCRAPER_REGISTRY

        assert "lidl" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["lidl"] is LidlScraper
