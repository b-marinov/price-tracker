"""Unit tests for the Fantastico Bulgaria scraper.

All HTTP calls are mocked — no live requests are made.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.fantastico import FantasticoScraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(filename: str) -> str:
    """Load an HTML fixture file as a string."""
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


@pytest.fixture
def page1_html() -> str:
    """Fixture HTML for Fantastico page 1."""
    return _load_fixture("fantastico_page1.html")


@pytest.fixture
def page2_html() -> str:
    """Fixture HTML for Fantastico page 2."""
    return _load_fixture("fantastico_page2.html")


@pytest.fixture
def scraper() -> FantasticoScraper:
    """A fresh FantasticoScraper instance."""
    return FantasticoScraper()


# ------------------------------------------------------------------
# store_slug
# ------------------------------------------------------------------


class TestStoreSlug:
    """Verify the scraper identifies itself correctly."""

    def test_store_slug_is_fantastico(self, scraper: FantasticoScraper) -> None:
        """Store slug must be 'fantastico'."""
        assert scraper.store_slug == "fantastico"


# ------------------------------------------------------------------
# parse()
# ------------------------------------------------------------------


class TestParse:
    """Tests for the parse method using fixture HTML."""

    def test_parse_page1_returns_five_items(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """Page 1 fixture contains 5 products (4 product-card + 1 promotion-item)."""
        raw = [{"html": page1_html, "page": 1}]
        items = scraper.parse(raw)
        assert len(items) == 5

    def test_parse_page2_returns_three_items(
        self, scraper: FantasticoScraper, page2_html: str
    ) -> None:
        """Page 2 fixture contains 3 products (2 product-card + 1 promotion-item)."""
        raw = [{"html": page2_html, "page": 2}]
        items = scraper.parse(raw)
        assert len(items) == 3

    def test_parse_multiple_pages(
        self, scraper: FantasticoScraper, page1_html: str, page2_html: str
    ) -> None:
        """Parsing both pages should yield 8 items total."""
        raw = [
            {"html": page1_html, "page": 1},
            {"html": page2_html, "page": 2},
        ]
        items = scraper.parse(raw)
        assert len(items) == 8

    def test_parse_extracts_product_name(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """Known product names from page 1 must appear in results."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        names = [item.name for item in items]
        assert "Домати български" in names
        assert "Кисело мляко 2%" in names

    def test_parse_extracts_correct_price(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """Verify decimal price extraction for a known product."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        domati = next(i for i in items if i.name == "Домати български")
        assert domati.price == Decimal("3.49")

    def test_parse_extracts_unit(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """Unit descriptor must be extracted correctly."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        domati = next(i for i in items if i.name == "Домати български")
        assert domati.unit == "кг"

    def test_parse_extracts_image_url(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """Image URL from src attribute must be extracted."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        domati = next(i for i in items if i.name == "Домати български")
        assert domati.image_url == "https://fantastico.bg/images/promo/domati-1kg.jpg"

    def test_parse_extracts_data_src_image(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """Product with data-src instead of src on <img> should still get image_url."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        shunka = next(i for i in items if "Шунка" in i.name)
        assert shunka.image_url == "https://fantastico.bg/images/promo/shunka-slice.jpg"

    def test_parse_sets_currency_bgn(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """All items must have BGN currency."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        assert all(item.currency == "BGN" for item in items)

    def test_parse_sets_source_web(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """All items must have source set to 'web'."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        assert all(item.source == "web" for item in items)

    def test_parse_empty_html(self, scraper: FantasticoScraper) -> None:
        """Empty HTML should produce zero items."""
        items = scraper.parse([{"html": "<html></html>", "page": 1}])
        assert items == []

    def test_parse_empty_list(self, scraper: FantasticoScraper) -> None:
        """Empty raw list should produce zero items."""
        items = scraper.parse([])
        assert items == []

    def test_parse_skips_card_without_name(self, scraper: FantasticoScraper) -> None:
        """Card missing product-name element should be skipped."""
        html = """
        <div class="product-card">
            <span class="product-price">1,00 лв.</span>
        </div>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert items == []

    def test_parse_skips_card_without_price(self, scraper: FantasticoScraper) -> None:
        """Card missing product-price element should be skipped."""
        html = """
        <div class="product-card">
            <h3 class="product-name">Тест продукт</h3>
        </div>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert items == []

    def test_parse_price_without_lv_suffix(self, scraper: FantasticoScraper) -> None:
        """Price tag without лв. suffix should still parse."""
        html = """
        <div class="product-card">
            <h3 class="product-name">Тест</h3>
            <span class="product-price">5,50</span>
        </div>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert len(items) == 1
        assert items[0].price == Decimal("5.50")

    def test_parse_promotion_item_container(
        self, scraper: FantasticoScraper
    ) -> None:
        """Products inside promotion-item divs must be parsed."""
        html = """
        <div class="promotion-item">
            <h3 class="product-name">Промо продукт</h3>
            <span class="product-price">2,99 лв.</span>
            <span class="product-unit">бр</span>
        </div>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert len(items) == 1
        assert items[0].name == "Промо продукт"
        assert items[0].price == Decimal("2.99")
        assert items[0].unit == "бр"


# ------------------------------------------------------------------
# fetch()
# ------------------------------------------------------------------


class TestFetch:
    """Tests for the fetch method with mocked httpx."""

    @pytest.mark.asyncio
    async def test_fetch_single_page_no_pagination(
        self, scraper: FantasticoScraper, page2_html: str
    ) -> None:
        """Page without next-page link should return only one page."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = page2_html

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["page"] == 1
        assert result[0]["html"] == page2_html

    @pytest.mark.asyncio
    async def test_fetch_follows_pagination(
        self, scraper: FantasticoScraper, page1_html: str, page2_html: str
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

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 2
        assert result[0]["page"] == 1
        assert result[1]["page"] == 2

    @pytest.mark.asyncio
    async def test_fetch_stops_on_non_200(
        self, scraper: FantasticoScraper
    ) -> None:
        """Non-200 response should stop pagination without raising."""
        resp_fail = MagicMock()
        resp_fail.status_code = 503
        resp_fail.text = "Service Unavailable"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp_fail)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_stops_on_http_error(
        self, scraper: FantasticoScraper
    ) -> None:
        """httpx.HTTPError during request should stop pagination gracefully."""
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
    async def test_fetch_respects_max_pages(
        self, scraper: FantasticoScraper, page1_html: str
    ) -> None:
        """Fetch should stop after _MAX_PAGES even if next-page links exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = page1_html  # always has a next-page link

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.fantastico.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 10


# ------------------------------------------------------------------
# Pagination helpers
# ------------------------------------------------------------------


class TestPaginationHelper:
    """Tests for the _extract_next_page_url static method."""

    def test_extracts_absolute_next_page_url(self, page1_html: str) -> None:
        """Page 1 fixture has an absolute next-page URL."""
        url = FantasticoScraper._extract_next_page_url(page1_html)
        assert url == "https://fantastico.bg/promotions?page=2"

    def test_returns_none_when_no_next_page(self, page2_html: str) -> None:
        """Page 2 fixture has no next-page link."""
        url = FantasticoScraper._extract_next_page_url(page2_html)
        assert url is None

    def test_converts_relative_url_to_absolute(self) -> None:
        """Relative href should be prefixed with the Fantastico domain."""
        html = '<a class="next-page" href="/promotions?page=3">Next</a>'
        url = FantasticoScraper._extract_next_page_url(html)
        assert url == "https://fantastico.bg/promotions?page=3"

    def test_returns_none_for_empty_href(self) -> None:
        """Empty href attribute should return None."""
        html = '<a class="next-page" href="">Next</a>'
        url = FantasticoScraper._extract_next_page_url(html)
        assert url is None


# ------------------------------------------------------------------
# normalise() (inherited from BaseScraper)
# ------------------------------------------------------------------


class TestNormalise:
    """Verify normalisation works correctly with Fantastico items."""

    def test_normalise_strips_and_titlecases(
        self, scraper: FantasticoScraper
    ) -> None:
        """Normalisation should strip whitespace and title-case names."""
        from app.scrapers.base import ScrapedItem

        item = ScrapedItem(
            name="  домати български  ",
            price=Decimal("3.49"),
            unit=" кг ",
        )
        result = scraper.normalise(item)
        assert result.name == "Домати Български"
        assert result.unit == "кг"
        assert result.currency == "BGN"


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------


class TestRegistry:
    """Verify the scraper is registered in the task registry."""

    def test_fantastico_in_registry(self) -> None:
        """FantasticoScraper must be in _SCRAPER_REGISTRY under 'fantastico'."""
        from app.scrapers.tasks import _SCRAPER_REGISTRY

        assert "fantastico" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["fantastico"] is FantasticoScraper
