"""Unit tests for the Billa Bulgaria scraper.

All HTTP calls are mocked — no live requests are made.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.billa import BillaScraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(filename: str) -> str:
    """Load an HTML fixture file as a string."""
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


@pytest.fixture
def page1_html() -> str:
    """Fixture HTML for Billa page 1."""
    return _load_fixture("billa_page1.html")


@pytest.fixture
def page2_html() -> str:
    """Fixture HTML for Billa page 2."""
    return _load_fixture("billa_page2.html")


@pytest.fixture
def scraper() -> BillaScraper:
    """A fresh BillaScraper instance."""
    return BillaScraper()


# ------------------------------------------------------------------
# store_slug
# ------------------------------------------------------------------


class TestStoreSlug:
    """Verify the scraper identifies itself correctly."""

    def test_store_slug_is_billa(self, scraper: BillaScraper) -> None:
        """store_slug must be 'billa'."""
        assert scraper.store_slug == "billa"


# ------------------------------------------------------------------
# parse() — product-tile layout
# ------------------------------------------------------------------


class TestParseTiles:
    """Tests for parsing <div class='product-tile'> elements."""

    def test_parse_page1_tile_count(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Page 1 has 4 product-tile divs + 2 articles = 6 total items."""
        raw = [{"html": page1_html, "page": 1}]
        items = scraper.parse(raw)
        assert len(items) == 6

    def test_parse_page2_returns_three_items(
        self, scraper: BillaScraper, page2_html: str
    ) -> None:
        """Page 2 has 2 product-tile divs + 1 article = 3 total items."""
        raw = [{"html": page2_html, "page": 2}]
        items = scraper.parse(raw)
        assert len(items) == 3

    def test_parse_multiple_pages(
        self, scraper: BillaScraper, page1_html: str, page2_html: str
    ) -> None:
        """Parsing both pages yields all 9 items."""
        raw = [
            {"html": page1_html, "page": 1},
            {"html": page2_html, "page": 2},
        ]
        items = scraper.parse(raw)
        assert len(items) == 9

    def test_parse_extracts_product_name(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Known product names should appear in parsed results."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        names = [item.name for item in items]
        assert "Домати български" in names
        assert "Прясно мляко 3.6% 1л" in names

    def test_parse_extracts_correct_price(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Verify exact price extraction for a known product."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        domati = next(i for i in items if i.name == "Домати български")
        assert domati.price == Decimal("3.99")

    def test_parse_extracts_unit(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Unit should be extracted from product-unit span."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        domati = next(i for i in items if i.name == "Домати български")
        assert domati.unit == "кг"

    def test_parse_extracts_image_url(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Image URL should be extracted from img src."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        domati = next(i for i in items if i.name == "Домати български")
        assert domati.image_url == "https://ssm.billa.bg/images/product/domati-1kg.jpg"

    def test_parse_extracts_data_src_image(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Product with data-src instead of src on <img> should still get image_url."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        hlyab = next(i for i in items if "Хляб типов" in i.name)
        assert hlyab.image_url == "https://ssm.billa.bg/images/product/hlyab-tipov.jpg"

    def test_parse_extracts_category_hint(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Category hint should be in the raw dict."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        domati = next(i for i in items if i.name == "Домати български")
        assert domati.raw["category_hint"] == "Плодове и зеленчуци"

    def test_parse_sets_currency_bgn(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """All items should default to BGN currency."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        assert all(item.currency == "BGN" for item in items)

    def test_parse_sets_source_web(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Source should be 'web' for all items."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        assert all(item.source == "web" for item in items)

    def test_parse_empty_html(self, scraper: BillaScraper) -> None:
        """Empty HTML should produce no items."""
        items = scraper.parse([{"html": "<html></html>", "page": 1}])
        assert items == []

    def test_parse_empty_list(self, scraper: BillaScraper) -> None:
        """Empty raw list should produce no items."""
        items = scraper.parse([])
        assert items == []

    def test_parse_skips_tile_without_name(self, scraper: BillaScraper) -> None:
        """Tile without a product name should be skipped."""
        html = """
        <div class="product-tile">
            <span class="price">1,00 лв.</span>
        </div>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert items == []

    def test_parse_skips_tile_without_price(self, scraper: BillaScraper) -> None:
        """Tile without a price should be skipped."""
        html = """
        <div class="product-tile">
            <h3 class="product-title">Тест продукт</h3>
        </div>
        """
        items = scraper.parse([{"html": html, "page": 1}])
        assert items == []

    def test_parse_price_without_lv_suffix(self, scraper: BillaScraper) -> None:
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
# parse() — article layout
# ------------------------------------------------------------------


class TestParseArticles:
    """Tests for parsing <article class='product'> elements."""

    def test_parse_article_extracts_name(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Article products should have their name extracted."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        names = [item.name for item in items]
        assert "Кока-Кола 500мл" in names

    def test_parse_article_extracts_price(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Article product should have correct price."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        cola = next(i for i in items if "Кока-Кола" in i.name)
        assert cola.price == Decimal("1.69")

    def test_parse_article_extracts_unit(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Article product should have unit extracted."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        cola = next(i for i in items if "Кока-Кола" in i.name)
        assert cola.unit == "бр"

    def test_parse_article_extracts_category(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Article product should have category hint."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        cola = next(i for i in items if "Кока-Кола" in i.name)
        assert cola.raw["category_hint"] == "Напитки"

    def test_parse_article_with_h3_title(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Article with h3.product-title (instead of span.product-name) should parse."""
        items = scraper.parse([{"html": page1_html, "page": 1}])
        biskviti = next(i for i in items if "Бисквити" in i.name)
        assert biskviti.price == Decimal("3.29")


# ------------------------------------------------------------------
# fetch()
# ------------------------------------------------------------------


class TestFetch:
    """Tests for the fetch method with mocked httpx."""

    @pytest.mark.asyncio
    async def test_fetch_single_page_no_pagination(
        self, scraper: BillaScraper, page2_html: str
    ) -> None:
        """Page without next-page link should return only one page."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = page2_html

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["page"] == 1
        assert result[0]["html"] == page2_html

    @pytest.mark.asyncio
    async def test_fetch_follows_pagination(
        self, scraper: BillaScraper, page1_html: str, page2_html: str
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

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 2
        assert result[0]["page"] == 1
        assert result[1]["page"] == 2

    @pytest.mark.asyncio
    async def test_fetch_stops_on_non_200(
        self, scraper: BillaScraper
    ) -> None:
        """Non-200 response should stop pagination without raising."""
        resp_fail = MagicMock()
        resp_fail.status_code = 503
        resp_fail.text = "Service Unavailable"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp_fail)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_stops_on_http_error(
        self, scraper: BillaScraper
    ) -> None:
        """httpx.HTTPError during request should stop pagination gracefully."""
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
    async def test_fetch_respects_max_pages(
        self, scraper: BillaScraper, page1_html: str
    ) -> None:
        """Fetch should stop after _MAX_PAGES even if next-page links exist."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = page1_html  # always has a next-page link

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.scrapers.billa.httpx.AsyncClient", return_value=mock_client):
            result = await scraper.fetch()

        assert len(result) == 10


# ------------------------------------------------------------------
# Pagination helpers
# ------------------------------------------------------------------


class TestPaginationHelper:
    """Tests for the _extract_next_page_url static method."""

    def test_extracts_absolute_next_page_url(self, page1_html: str) -> None:
        """Page 1 has an absolute next-page URL."""
        url = BillaScraper._extract_next_page_url(page1_html)
        assert url == "https://ssm.billa.bg/products?page=2"

    def test_returns_none_when_no_next_page(self, page2_html: str) -> None:
        """Page 2 has no next-page link."""
        url = BillaScraper._extract_next_page_url(page2_html)
        assert url is None

    def test_converts_relative_url_to_absolute(self) -> None:
        """Relative hrefs should be prefixed with the Billa domain."""
        html = '<a class="next-page" href="/products?page=3">Next</a>'
        url = BillaScraper._extract_next_page_url(html)
        assert url == "https://ssm.billa.bg/products?page=3"

    def test_returns_none_for_empty_href(self) -> None:
        """Empty href should return None."""
        html = '<a class="next-page" href="">Next</a>'
        url = BillaScraper._extract_next_page_url(html)
        assert url is None


# ------------------------------------------------------------------
# normalise() (inherited from BaseScraper)
# ------------------------------------------------------------------


class TestNormalise:
    """Verify normalisation works correctly with Billa items."""

    def test_normalise_strips_and_titlecases(
        self, scraper: BillaScraper
    ) -> None:
        """Normalise should strip whitespace and title-case names."""
        from app.scrapers.base import ScrapedItem

        item = ScrapedItem(
            name="  домати български  ",
            price=Decimal("3.99"),
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

    def test_billa_in_registry(self) -> None:
        """BillaScraper should be in _SCRAPER_REGISTRY under 'billa'."""
        from app.scrapers.tasks import _SCRAPER_REGISTRY

        assert "billa" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["billa"] is BillaScraper
