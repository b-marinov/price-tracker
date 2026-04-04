"""Unit tests for the Kaufland Bulgaria scraper.

All HTTP calls are mocked — no live requests are made.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.kaufland import KauflandScraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(filename: str) -> str:
    """Load an HTML fixture file as a string."""
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


@pytest.fixture
def page1_html() -> str:
    """Fixture HTML for Kaufland page 1."""
    return _load_fixture("kaufland_page1.html")


@pytest.fixture
def page2_html() -> str:
    """Fixture HTML for Kaufland page 2."""
    return _load_fixture("kaufland_page2.html")


@pytest.fixture
def scraper() -> KauflandScraper:
    """A fresh KauflandScraper instance."""
    return KauflandScraper()


# ------------------------------------------------------------------
# store_slug
# ------------------------------------------------------------------


class TestStoreSlug:
    """Verify the scraper identifies itself correctly."""

    def test_store_slug_is_kaufland(self, scraper: KauflandScraper) -> None:
        assert scraper.store_slug == "kaufland"


# ------------------------------------------------------------------
# parse()
# ------------------------------------------------------------------


class TestParse:
    """Tests for the parse method using fixture HTML."""

    def test_parse_page1_returns_five_items(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        raw = [{"html": page1_html, "page": 1}]
        items = scraper.parse(raw)
        assert len(items) == 5

    def test_parse_page2_returns_three_items(
        self, scraper: KauflandScraper, page2_html: str
    ) -> None:
        raw = [{"html": page2_html, "page": 2}]
        items = scraper.parse(raw)
        assert len(items) == 3

    def test_parse_multiple_pages(
        self, scraper: KauflandScraper, page1_html: str, page2_html: str
    ) -> None:
        raw = [
            {"html": page1_html, "page": 1},
            {"html": page2_html, "page": 2},
        ]
        items = scraper.parse(raw)
        assert len(items) == 8

    def test_parse_extracts_product_name(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        items = scraper.parse([{"html": page1_html, "page": 1}])
        names = [item.name for item in items]
        assert "Банани" in names
        assert "Кисело мляко БДС 3.6%" in names

    def test_parse_extracts_correct_price(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        items = scraper.parse([{"html": page1_html, "page": 1}])
        banani = next(i for i in items if i.name == "Банани")
        assert banani.price == Decimal("2.49")

    def test_parse_extracts_unit(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        items = scraper.parse([{"html": page1_html, "page": 1}])
        banani = next(i for i in items if i.name == "Банани")
        assert banani.unit == "кг"

    def test_parse_extracts_image_url(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        items = scraper.parse([{"html": page1_html, "page": 1}])
        banani = next(i for i in items if i.name == "Банани")
        assert banani.image_url == "https://www.kaufland.bg/images/product/banani-1kg.jpg"

    def test_parse_extracts_data_src_image(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        """Product with data-src instead of src on <img> should still get image_url."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        chicken = next(i for i in items if "Пилешки" in i.name)
        assert chicken.image_url == "https://www.kaufland.bg/images/product/pileshki-butcheta.jpg"

    def test_parse_extracts_category_hint(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        items = scraper.parse([{"html": page1_html, "page": 1}])
        banani = next(i for i in items if i.name == "Банани")
        assert banani.raw["category_hint"] == "Плодове и зеленчуци"

    def test_parse_sets_currency_bgn(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        items = scraper.parse([{"html": page1_html, "page": 1}])
        assert all(item.currency == "BGN" for item in items)

    def test_parse_sets_source_web(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        items = scraper.parse([{"html": page1_html, "page": 1}])
        assert all(item.source == "web" for item in items)

    def test_parse_empty_html(self, scraper: KauflandScraper) -> None:
        items = scraper.parse([{"html": "<html></html>", "page": 1}])
        assert items == []

    def test_parse_empty_list(self, scraper: KauflandScraper) -> None:
        items = scraper.parse([])
        assert items == []

    def test_parse_skips_tile_without_name(self, scraper: KauflandScraper) -> None:
        html = """
        <div class="product-tile">
            <span class="price">1,00 лв.</span>
        </div>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert items == []

    def test_parse_skips_tile_without_price(self, scraper: KauflandScraper) -> None:
        html = """
        <div class="product-tile">
            <h3 class="product-title">Тест продукт</h3>
        </div>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert items == []

    def test_parse_price_without_lv_suffix(self, scraper: KauflandScraper) -> None:
        """Price tag without лв. suffix should still parse."""
        html = """
        <div class="product-tile">
            <h3 class="product-title">Тест</h3>
            <span class="price">5,50</span>
        </div>
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
        self, scraper: KauflandScraper, page2_html: str
    ) -> None:
        """Page without next-page link should return only one page."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = page2_html

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["page"] == 1
        assert result[0]["html"] == page2_html

    @pytest.mark.asyncio
    async def test_fetch_follows_pagination(
        self, scraper: KauflandScraper, page1_html: str, page2_html: str
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

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 2
        assert result[0]["page"] == 1
        assert result[1]["page"] == 2

    @pytest.mark.asyncio
    async def test_fetch_stops_on_non_200(
        self, scraper: KauflandScraper
    ) -> None:
        """Non-200 response should stop pagination without raising."""
        resp_fail = MagicMock()
        resp_fail.status_code = 503
        resp_fail.text = "Service Unavailable"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp_fail)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_stops_on_http_error(
        self, scraper: KauflandScraper
    ) -> None:
        """httpx.HTTPError during request should stop pagination gracefully."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_respects_max_pages(
        self, scraper: KauflandScraper, page1_html: str
    ) -> None:
        """Fetch should stop after _MAX_PAGES even if next-page links exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # page1_html always has a next-page link
        mock_response.text = page1_html

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.kaufland.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        # Should have exactly _MAX_PAGES (10) entries
        assert len(result) == 10


# ------------------------------------------------------------------
# Pagination helpers
# ------------------------------------------------------------------


class TestPaginationHelper:
    """Tests for the _extract_next_page_url static method."""

    def test_extracts_absolute_next_page_url(self, page1_html: str) -> None:
        url = KauflandScraper._extract_next_page_url(page1_html)
        assert url == "https://www.kaufland.bg/products/?page=2"

    def test_returns_none_when_no_next_page(self, page2_html: str) -> None:
        url = KauflandScraper._extract_next_page_url(page2_html)
        assert url is None

    def test_converts_relative_url_to_absolute(self) -> None:
        html = '<a class="next-page" href="/products/?page=3">Next</a>'
        url = KauflandScraper._extract_next_page_url(html)
        assert url == "https://www.kaufland.bg/products/?page=3"

    def test_returns_none_for_empty_href(self) -> None:
        html = '<a class="next-page" href="">Next</a>'
        url = KauflandScraper._extract_next_page_url(html)
        assert url is None


# ------------------------------------------------------------------
# normalise() (inherited from BaseScraper)
# ------------------------------------------------------------------


class TestNormalise:
    """Verify normalisation works correctly with Kaufland items."""

    def test_normalise_strips_and_titlecases(
        self, scraper: KauflandScraper
    ) -> None:
        from app.scrapers.base import ScrapedItem

        item = ScrapedItem(
            name="  бял хляб нарязан  ",
            price=Decimal("1.29"),
            unit=" бр ",
        )
        result = scraper.normalise(item)
        assert result.name == "Бял Хляб Нарязан"
        assert result.unit == "бр"
        assert result.currency == "BGN"


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------


class TestRegistry:
    """Verify the scraper is registered in the task registry."""

    def test_kaufland_in_registry(self) -> None:
        from app.scrapers.tasks import _SCRAPER_REGISTRY

        assert "kaufland" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["kaufland"] is KauflandScraper
