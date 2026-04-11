"""Unit tests for the Lidl Bulgaria Playwright/LLM brochure scraper.

Playwright and Ollama are fully mocked — no browser or GPU required.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.lidl import LidlScraper


@pytest.fixture
def scraper() -> LidlScraper:
    """A fresh LidlScraper instance."""
    return LidlScraper()


def _mock_settings(*, llm_enabled: bool = True) -> MagicMock:
    """Return a MagicMock Settings object."""
    s = MagicMock()
    s.LLM_PARSER_ENABLED = llm_enabled
    s.LLM_OLLAMA_HOST = "http://localhost:11434"
    s.LLM_MODEL = "gemma4:e4b"
    s.LLM_TEMPERATURE = 0.0
    s.LLM_TIMEOUT_SECONDS = 120
    return s


_PNG_PAGE_1 = b"\x89PNG\r\n\x1a\npage1"
_PNG_PAGE_2 = b"\x89PNG\r\n\x1a\npage2"


def _make_playwright_mock(pages: list[bytes], has_next: bool = False) -> MagicMock:
    """Build a Playwright async_playwright context mock that returns *pages*.

    Args:
        pages: List of PNG byte strings to return from screenshot(), one per page.
        has_next: Whether to simulate a visible next-page button for the last page.
    """
    call_count: list[int] = [0]

    async def _screenshot(**_: object) -> bytes:
        idx = min(call_count[0], len(pages) - 1)
        return pages[idx]

    async def _is_visible() -> bool:
        # Visible if there is a next page to go to.
        nxt = call_count[0] + 1
        call_count[0] += 1
        return nxt < len(pages) or has_next

    page_mock = MagicMock()
    page_mock.goto = AsyncMock()
    page_mock.wait_for_timeout = AsyncMock()
    page_mock.screenshot = AsyncMock(side_effect=_screenshot)

    next_btn = MagicMock()
    next_btn.is_visible = AsyncMock(side_effect=_is_visible)
    next_btn.click = AsyncMock()

    page_mock.locator = MagicMock(return_value=MagicMock(first=next_btn))

    context_mock = MagicMock()
    context_mock.new_page = AsyncMock(return_value=page_mock)

    browser_mock = MagicMock()
    browser_mock.new_context = AsyncMock(return_value=context_mock)
    browser_mock.close = AsyncMock()

    chromium_mock = MagicMock()
    chromium_mock.launch = AsyncMock(return_value=browser_mock)

    pw_mock = MagicMock()
    pw_mock.chromium = chromium_mock
    pw_mock.__aenter__ = AsyncMock(return_value=pw_mock)
    pw_mock.__aexit__ = AsyncMock(return_value=False)
    # async_playwright() is called with no args; the return value must be an
    # async context manager.  Make pw_mock() return itself.
    pw_mock.return_value = pw_mock

    return pw_mock


def _patch_playwright(pw_mock: MagicMock) -> patch:  # type: ignore[type-arg]
    """Return a context manager that injects *pw_mock* as async_playwright.

    Because `from playwright.async_api import async_playwright` happens inside
    fetch(), we inject it by patching the module-level attribute on a fake
    ``playwright.async_api`` module in sys.modules.
    """
    fake_module = ModuleType("playwright.async_api")
    fake_module.async_playwright = pw_mock  # type: ignore[attr-defined]
    return patch.dict(sys.modules, {"playwright.async_api": fake_module})


# ------------------------------------------------------------------
# TestStoreSlug
# ------------------------------------------------------------------


class TestStoreSlug:
    """Verify the scraper identifies itself correctly."""

    def test_store_slug_is_lidl(self, scraper: LidlScraper) -> None:
        """store_slug must be 'lidl'."""
        assert scraper.store_slug == "lidl"


# ------------------------------------------------------------------
# TestFetch
# ------------------------------------------------------------------


class TestFetch:
    """Tests for LidlScraper.fetch() with mocked Playwright."""

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_llm_disabled(
        self, scraper: LidlScraper
    ) -> None:
        """When LLM_PARSER_ENABLED=False, fetch must return empty list immediately."""
        with patch(
            "app.scrapers.lidl.get_settings",
            return_value=_mock_settings(llm_enabled=False),
        ):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_playwright_not_installed(
        self, scraper: LidlScraper
    ) -> None:
        """ImportError for playwright must return empty list gracefully."""
        with (
            patch(
                "app.scrapers.lidl.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch.dict("sys.modules", {"playwright.async_api": None}),  # type: ignore[dict-item]
        ):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_single_page_brochure(
        self, scraper: LidlScraper
    ) -> None:
        """Single-page brochure (no next button) should return one screenshot."""
        pw_mock = _make_playwright_mock([_PNG_PAGE_1])

        with (
            patch(
                "app.scrapers.lidl.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            _patch_playwright(pw_mock),
        ):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["screenshot"] == _PNG_PAGE_1
        assert result[0]["page_num"] == 1

    @pytest.mark.asyncio
    async def test_fetch_multi_page_brochure(
        self, scraper: LidlScraper
    ) -> None:
        """Two-page brochure should return two screenshot entries."""
        pw_mock = _make_playwright_mock([_PNG_PAGE_1, _PNG_PAGE_2])

        with (
            patch(
                "app.scrapers.lidl.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            _patch_playwright(pw_mock),
        ):
            result = await scraper.fetch()

        assert len(result) == 2
        assert result[0]["page_num"] == 1
        assert result[1]["page_num"] == 2

    @pytest.mark.asyncio
    async def test_fetch_returns_empty_on_navigation_error(
        self, scraper: LidlScraper
    ) -> None:
        """Exception during page navigation must be caught; empty list returned."""
        # Raise inside the inner try/except (page.goto fails).
        page_mock = MagicMock()
        page_mock.goto = AsyncMock(side_effect=RuntimeError("net::ERR_NAME_NOT_RESOLVED"))
        page_mock.wait_for_timeout = AsyncMock()

        context_mock = MagicMock()
        context_mock.new_page = AsyncMock(return_value=page_mock)

        browser_mock = MagicMock()
        browser_mock.new_context = AsyncMock(return_value=context_mock)
        browser_mock.close = AsyncMock()

        chromium_mock = MagicMock()
        chromium_mock.launch = AsyncMock(return_value=browser_mock)

        pw_mock = MagicMock()
        pw_mock.chromium = chromium_mock
        pw_mock.__aenter__ = AsyncMock(return_value=pw_mock)
        pw_mock.__aexit__ = AsyncMock(return_value=False)
        pw_mock.return_value = pw_mock

        with (
            patch(
                "app.scrapers.lidl.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            _patch_playwright(pw_mock),
        ):
            result = await scraper.fetch()

        assert result == []


# ------------------------------------------------------------------
# TestParse
# ------------------------------------------------------------------


class TestParse:
    """Tests for LidlScraper.parse() with mocked Ollama vision client."""

    def test_parse_returns_empty_for_empty_raw(
        self, scraper: LidlScraper
    ) -> None:
        """Empty raw list must return empty items list immediately."""
        result = scraper.parse([])
        assert result == []

    def test_parse_returns_empty_when_llm_disabled(
        self, scraper: LidlScraper
    ) -> None:
        """LLM_PARSER_ENABLED=False must return empty list without calling Ollama."""
        with patch(
            "app.scrapers.lidl.get_settings",
            return_value=_mock_settings(llm_enabled=False),
        ):
            result = scraper.parse([{"screenshot": _PNG_PAGE_1, "page_num": 1}])

        assert result == []

    def test_parse_returns_empty_when_ollama_unavailable(
        self, scraper: LidlScraper
    ) -> None:
        """Unavailable Ollama service must return empty list without extracting."""
        mock_client = MagicMock()
        mock_client.is_available.return_value = False

        with (
            patch(
                "app.scrapers.lidl.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_client,
            ),
        ):
            result = scraper.parse([{"screenshot": _PNG_PAGE_1, "page_num": 1}])

        assert result == []

    def test_parse_calls_extract_for_each_page(
        self, scraper: LidlScraper
    ) -> None:
        """extract_from_screenshot must be called once per screenshot entry."""
        from app.scrapers.base import ScrapedItem

        fake_scraped = ScrapedItem(name="Пилешко филе", price=Decimal("11.99"))

        mock_client = MagicMock()
        mock_client.is_available.return_value = True

        with (
            patch(
                "app.scrapers.lidl.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_client,
            ),
            patch(
                "app.scrapers.llm_parser.extract_from_screenshot",
                return_value=[MagicMock()],
            ) as mock_extract,
            patch(
                "app.scrapers.llm_parser.llm_items_to_scraped",
                return_value=[fake_scraped],
            ),
        ):
            result = scraper.parse([
                {"screenshot": _PNG_PAGE_1, "page_num": 1},
                {"screenshot": _PNG_PAGE_2, "page_num": 2},
            ])

        assert mock_extract.call_count == 2
        assert len(result) == 2

    def test_parse_continues_on_per_page_error(
        self, scraper: LidlScraper
    ) -> None:
        """Exception on one page must be logged and remaining pages processed."""
        from app.scrapers.base import ScrapedItem

        fake_scraped = ScrapedItem(name="Домати", price=Decimal("2.49"))

        mock_client = MagicMock()
        mock_client.is_available.return_value = True

        with (
            patch(
                "app.scrapers.lidl.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_client,
            ),
            patch(
                "app.scrapers.llm_parser.extract_from_screenshot",
                side_effect=[RuntimeError("LLM timeout"), [MagicMock()]],
            ),
            patch(
                "app.scrapers.llm_parser.llm_items_to_scraped",
                return_value=[fake_scraped],
            ),
        ):
            result = scraper.parse([
                {"screenshot": _PNG_PAGE_1, "page_num": 1},
                {"screenshot": _PNG_PAGE_2, "page_num": 2},
            ])

        # Page 1 failed, page 2 succeeded → 1 item total
        assert len(result) == 1
        assert result[0].name == "Домати"

    def test_parse_aggregates_items_across_pages(
        self, scraper: LidlScraper
    ) -> None:
        """Items from all pages must be combined into a flat list."""
        from app.scrapers.base import ScrapedItem

        item1 = ScrapedItem(name="Пилешко", price=Decimal("11.99"))
        item2 = ScrapedItem(name="Банани", price=Decimal("1.99"))

        mock_client = MagicMock()
        mock_client.is_available.return_value = True

        with (
            patch(
                "app.scrapers.lidl.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_client,
            ),
            patch(
                "app.scrapers.llm_parser.extract_from_screenshot",
                side_effect=[[MagicMock()], [MagicMock()]],
            ),
            patch(
                "app.scrapers.llm_parser.llm_items_to_scraped",
                side_effect=[[item1], [item2]],
            ),
        ):
            result = scraper.parse([
                {"screenshot": _PNG_PAGE_1, "page_num": 1},
                {"screenshot": _PNG_PAGE_2, "page_num": 2},
            ])

        assert len(result) == 2
        names = {r.name for r in result}
        assert names == {"Пилешко", "Банани"}


# ------------------------------------------------------------------
# TestNormalise
# ------------------------------------------------------------------


class TestNormalise:
    """Verify normalisation works correctly with Lidl items."""

    def test_normalise_strips_and_titlecases(
        self, scraper: LidlScraper
    ) -> None:
        """Normalise must strip whitespace and title-case names."""
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
# TestRegistry
# ------------------------------------------------------------------


class TestRegistry:
    """Verify the scraper is registered in the task registry."""

    def test_lidl_in_registry(self) -> None:
        """LidlScraper must be in _SCRAPER_REGISTRY under 'lidl'."""
        from app.scrapers.tasks import _SCRAPER_REGISTRY

        assert "lidl" in _SCRAPER_REGISTRY
        assert _SCRAPER_REGISTRY["lidl"] is LidlScraper
