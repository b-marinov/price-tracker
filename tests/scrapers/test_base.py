"""Tests for BaseScraper abstract class and ScrapedItem dataclass."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.scrapers.base import BaseScraper, ScrapedItem


class FakeScraper(BaseScraper):
    """Concrete scraper for testing the BaseScraper interface."""

    store_slug = "fake-store"

    def __init__(self, raw_data: list[dict] | None = None) -> None:
        self._raw_data = raw_data or []

    async def fetch(self) -> list[dict]:
        """Return pre-configured raw data."""
        return self._raw_data

    def parse(self, raw: list[dict]) -> list[ScrapedItem]:
        """Parse raw dicts into ScrapedItem instances."""
        return [
            ScrapedItem(
                name=d["name"],
                price=Decimal(str(d["price"])),
                barcode=d.get("barcode"),
            )
            for d in raw
        ]


class TestScrapedItem:
    """Tests for the ScrapedItem dataclass."""

    def test_defaults(self) -> None:
        """ScrapedItem should have sensible defaults."""
        item = ScrapedItem(name="Test", price=Decimal("1.00"))
        assert item.currency == "EUR"
        assert item.unit is None
        assert item.image_url is None
        assert item.barcode is None
        assert item.source == "web"
        assert item.raw == {}

    def test_all_fields(self) -> None:
        """ScrapedItem should accept all optional fields."""
        item = ScrapedItem(
            name="Product",
            price=Decimal("5.99"),
            currency="EUR",
            unit="kg",
            image_url="https://example.com/img.jpg",
            barcode="1234567890123",
            source="brochure",
            raw={"key": "value"},
        )
        assert item.currency == "EUR"
        assert item.source == "brochure"
        assert item.raw == {"key": "value"}


class TestBaseScraper:
    """Tests for the BaseScraper abstract interface."""

    def test_cannot_instantiate_abstract(self) -> None:
        """BaseScraper cannot be instantiated directly."""
        with pytest.raises(TypeError):
            BaseScraper()  # type: ignore[abstract]

    def test_normalise_strips_whitespace(self) -> None:
        """normalise() should strip whitespace from name."""
        scraper = FakeScraper()
        item = ScrapedItem(name="  hello world  ", price=Decimal("1.00"))
        result = scraper.normalise(item)
        assert result.name == "Hello World"

    def test_normalise_title_cases(self) -> None:
        """normalise() should title-case the product name."""
        scraper = FakeScraper()
        item = ScrapedItem(name="organic milk", price=Decimal("3.50"))
        result = scraper.normalise(item)
        assert result.name == "Organic Milk"

    def test_normalise_default_currency(self) -> None:
        """normalise() should default to EUR when currency is empty."""
        scraper = FakeScraper()
        item = ScrapedItem(name="Test", price=Decimal("1.00"), currency="")
        result = scraper.normalise(item)
        assert result.currency == "EUR"

    def test_normalise_preserves_existing_currency(self) -> None:
        """normalise() should keep a non-empty currency unchanged."""
        scraper = FakeScraper()
        item = ScrapedItem(name="Test", price=Decimal("1.00"), currency="EUR")
        result = scraper.normalise(item)
        assert result.currency == "EUR"

    def test_normalise_strips_unit(self) -> None:
        """normalise() should strip whitespace from unit if present."""
        scraper = FakeScraper()
        item = ScrapedItem(name="Test", price=Decimal("1.00"), unit="  kg ")
        result = scraper.normalise(item)
        assert result.unit == "kg"

    def test_normalise_strips_barcode(self) -> None:
        """normalise() should strip whitespace from barcode if present."""
        scraper = FakeScraper()
        item = ScrapedItem(
            name="Test", price=Decimal("1.00"), barcode=" 123456 "
        )
        result = scraper.normalise(item)
        assert result.barcode == "123456"

    @pytest.mark.asyncio
    async def test_run_pipeline(self) -> None:
        """run() should execute fetch -> parse -> normalise."""
        raw = [
            {"name": "  apple  ", "price": "1.50", "barcode": "111"},
            {"name": "banana", "price": "0.99"},
        ]
        scraper = FakeScraper(raw_data=raw)
        results = await scraper.run()

        assert len(results) == 2
        assert results[0].name == "Apple"
        assert results[0].price == Decimal("1.50")
        assert results[0].barcode == "111"
        assert results[1].name == "Banana"

    @pytest.mark.asyncio
    async def test_run_empty_result(self) -> None:
        """run() should return an empty list when fetch returns nothing."""
        scraper = FakeScraper(raw_data=[])
        results = await scraper.run()
        assert results == []

    def test_normalise_preserves_price(self) -> None:
        """normalise() should not alter the price value."""
        scraper = FakeScraper()
        item = ScrapedItem(name="Test", price=Decimal("12.345"))
        result = scraper.normalise(item)
        assert result.price == Decimal("12.345")

    def test_normalise_none_unit_stays_none(self) -> None:
        """normalise() should leave unit as None when not provided."""
        scraper = FakeScraper()
        item = ScrapedItem(name="Test", price=Decimal("1.00"), unit=None)
        result = scraper.normalise(item)
        assert result.unit is None

    def test_normalise_none_barcode_stays_none(self) -> None:
        """normalise() should leave barcode as None when not provided."""
        scraper = FakeScraper()
        item = ScrapedItem(name="Test", price=Decimal("1.00"), barcode=None)
        result = scraper.normalise(item)
        assert result.barcode is None

    def test_normalise_preserves_image_url(self) -> None:
        """normalise() should pass image_url through unchanged."""
        scraper = FakeScraper()
        url = "https://example.com/image.jpg"
        item = ScrapedItem(name="Test", price=Decimal("1.00"), image_url=url)
        result = scraper.normalise(item)
        assert result.image_url == url

    def test_normalise_preserves_source(self) -> None:
        """normalise() should pass source through unchanged."""
        scraper = FakeScraper()
        item = ScrapedItem(name="Test", price=Decimal("1.00"), source="brochure")
        result = scraper.normalise(item)
        assert result.source == "brochure"

    def test_normalise_preserves_raw(self) -> None:
        """normalise() should pass the raw dict through unchanged."""
        scraper = FakeScraper()
        raw_data = {"original_key": "original_value", "count": 42}
        item = ScrapedItem(name="Test", price=Decimal("1.00"), raw=raw_data)
        result = scraper.normalise(item)
        assert result.raw == raw_data

    def test_cannot_instantiate_missing_fetch(self) -> None:
        """A subclass without fetch() cannot be instantiated."""
        with pytest.raises(TypeError):
            class IncompleteScraper(BaseScraper):  # type: ignore[abstract]
                store_slug = "incomplete"
                def parse(self, raw: list[dict]) -> list[ScrapedItem]:
                    return []
            IncompleteScraper()

    def test_cannot_instantiate_missing_parse(self) -> None:
        """A subclass without parse() cannot be instantiated."""
        with pytest.raises(TypeError):
            class IncompleteScraper(BaseScraper):  # type: ignore[abstract]
                store_slug = "incomplete"
                async def fetch(self) -> list[dict]:
                    return []
            IncompleteScraper()

    @pytest.mark.asyncio
    async def test_run_applies_normalise_to_all_items(self) -> None:
        """run() must normalise every item, not just the first."""
        raw = [
            {"name": "  apple  ", "price": "1.00"},
            {"name": "  BANANA REPUBLIC  ", "price": "2.00"},
            {"name": "cherry", "price": "3.00"},
        ]
        scraper = FakeScraper(raw_data=raw)
        results = await scraper.run()
        assert results[0].name == "Apple"
        assert results[1].name == "Banana Republic"
        assert results[2].name == "Cherry"


class TestScrapedItemDefaults:
    """Additional edge-case tests for ScrapedItem field defaults."""

    def test_raw_field_is_independent_per_instance(self) -> None:
        """Each ScrapedItem should have its own raw dict (no shared mutable default)."""
        a = ScrapedItem(name="A", price=Decimal("1.00"))
        b = ScrapedItem(name="B", price=Decimal("2.00"))
        a.raw["key"] = "value"
        assert "key" not in b.raw

    def test_source_default_is_web(self) -> None:
        """source should default to 'web'."""
        item = ScrapedItem(name="X", price=Decimal("0.01"))
        assert item.source == "web"

    def test_currency_default_is_bgn(self) -> None:
        """currency should default to "EUR"."""
        item = ScrapedItem(name="X", price=Decimal("0.01"))
        assert item.currency == "EUR"
