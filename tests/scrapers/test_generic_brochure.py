"""Unit tests for GenericBrochureScraper.

Playwright and Ollama are fully mocked — no browser or network required.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.generic_brochure import GenericBrochureScraper


def _make_scraper(slug: str = "teststore") -> GenericBrochureScraper:
    return GenericBrochureScraper(
        store_slug=slug,
        brochure_listing_url="https://example.com/brochures",
    )


def _mock_settings(*, llm_enabled: bool = True) -> MagicMock:
    s = MagicMock()
    s.LLM_PARSER_ENABLED = llm_enabled
    s.LLM_OLLAMA_HOST = "http://localhost:11434"
    s.LLM_MODEL = "gemma4:e4b"
    s.LLM_TEMPERATURE = 0.0
    s.LLM_TIMEOUT_SECONDS = 120
    s.LLM_PAGE_DPI = 150
    return s


def _patch_playwright(pw_mock: MagicMock) -> patch:  # type: ignore[type-arg]
    fake_module = ModuleType("playwright.async_api")
    fake_module.async_playwright = pw_mock  # type: ignore[attr-defined]
    return patch.dict(sys.modules, {"playwright.async_api": fake_module})


def _make_page_mock(
    *,
    title: str = "Test Store",
    direct_pdf_links: list[dict] | None = None,
    all_links: list[dict] | None = None,
    screenshot_bytes: bytes = b"\xff\xd8\xff\xe0screenshot",
) -> MagicMock:
    """Build a Playwright page mock."""
    page = MagicMock()
    page.goto = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    page.title = AsyncMock(return_value=title)
    page.screenshot = AsyncMock(return_value=screenshot_bytes)

    # evaluate() returns different values depending on call order.
    # fetch() calls evaluate() 4 times:
    #   1. direct PDF links (list[dict])
    #   2. iframe srcs (list[str]) — always empty in tests
    #   3. raw viewer anchor hrefs (list[str]) — always empty in tests
    #   4. all links for LLM text analysis (list[dict])
    _call_count = [0]
    _responses: list[list] = [
        direct_pdf_links if direct_pdf_links is not None else [],
        [],  # iframe srcs
        [],  # raw viewer links
        all_links if all_links is not None else [],
    ]

    async def _evaluate(expr: str) -> list:
        idx = min(_call_count[0], len(_responses) - 1)
        _call_count[0] += 1
        return _responses[idx]

    page.evaluate = AsyncMock(side_effect=_evaluate)
    return page


def _make_browser_mock(page: MagicMock) -> MagicMock:
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)

    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    return browser


def _make_pw_mock(browser: MagicMock) -> MagicMock:
    chromium = MagicMock()
    chromium.launch = AsyncMock(return_value=browser)

    pw = MagicMock()
    pw.chromium = chromium
    pw.__aenter__ = AsyncMock(return_value=pw)
    pw.__aexit__ = AsyncMock(return_value=False)
    pw.return_value = pw
    return pw


# ---------------------------------------------------------------------------
# Instance basics
# ---------------------------------------------------------------------------


class TestInstanceAttributes:
    def test_store_slug_set_per_instance(self) -> None:
        s = _make_scraper("lidl")
        assert s.store_slug == "lidl"

    def test_brochure_url_set_per_instance(self) -> None:
        s = _make_scraper()
        assert s.brochure_listing_url == "https://example.com/brochures"

    def test_different_slugs_independent(self) -> None:
        a = _make_scraper("kaufland")
        b = _make_scraper("billa")
        assert a.store_slug == "kaufland"
        assert b.store_slug == "billa"


# ---------------------------------------------------------------------------
# fetch() — early exits
# ---------------------------------------------------------------------------


class TestFetchEarlyExit:
    @pytest.mark.asyncio
    async def test_returns_empty_when_llm_disabled(self) -> None:
        scraper = _make_scraper()
        with patch(
            "app.config.get_settings",
            return_value=_mock_settings(llm_enabled=False),
        ):
            result = await scraper.fetch()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_playwright_missing(self) -> None:
        scraper = _make_scraper()
        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch.dict("sys.modules", {"playwright.async_api": None}),  # type: ignore[dict-item]
        ):
            result = await scraper.fetch()
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_ollama_unavailable(self) -> None:
        scraper = _make_scraper()
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = False

        page = _make_page_mock()
        browser = _make_browser_mock(page)
        pw = _make_pw_mock(browser)

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            _patch_playwright(pw),
        ):
            result = await scraper.fetch()
        assert result == []


# ---------------------------------------------------------------------------
# fetch() — Strategy 1: direct PDF links in DOM
# ---------------------------------------------------------------------------


class TestFetchStrategy1DirectLinks:
    @pytest.mark.asyncio
    async def test_single_direct_pdf_link_used_directly(self) -> None:
        scraper = _make_scraper()
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True

        page = _make_page_mock(
            title="Kaufland Brochure",
            direct_pdf_links=[
                {"href": "https://cdn.kaufland.bg/brochure.pdf", "text": "Download PDF"}
            ],
        )
        pw = _make_pw_mock(_make_browser_mock(page))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            _patch_playwright(pw),
        ):
            result = await scraper.fetch()

        assert len(result) == 1
        assert result[0]["pdf_url"] == "https://cdn.kaufland.bg/brochure.pdf"
        assert result[0]["title"] == "Kaufland Brochure"

    @pytest.mark.asyncio
    async def test_multiple_direct_links_uses_llm_to_pick(self) -> None:
        scraper = _make_scraper()
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True

        direct_links = [
            {"href": "https://cdn.example.com/old.pdf", "text": "April brochure"},
            {"href": "https://cdn.example.com/current.pdf", "text": "Current brochure"},
        ]
        page = _make_page_mock(direct_pdf_links=direct_links)
        pw = _make_pw_mock(_make_browser_mock(page))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            patch(
                "app.scrapers.llm_parser.discover_pdf_urls",
                return_value=["https://cdn.example.com/current.pdf"],
            ) as mock_discover,
            _patch_playwright(pw),
        ):
            result = await scraper.fetch()

        mock_discover.assert_called_once()
        assert result[0]["pdf_url"] == "https://cdn.example.com/current.pdf"

    @pytest.mark.asyncio
    async def test_multiple_direct_links_falls_back_to_first_when_llm_returns_empty(
        self,
    ) -> None:
        scraper = _make_scraper()
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True

        direct_links = [
            {"href": "https://cdn.example.com/a.pdf", "text": "A"},
            {"href": "https://cdn.example.com/b.pdf", "text": "B"},
        ]
        page = _make_page_mock(direct_pdf_links=direct_links)
        pw = _make_pw_mock(_make_browser_mock(page))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            patch(
                "app.scrapers.llm_parser.discover_pdf_urls",
                return_value=[],   # LLM uncertain
            ),
            _patch_playwright(pw),
        ):
            result = await scraper.fetch()

        assert result[0]["pdf_url"] == "https://cdn.example.com/a.pdf"


# ---------------------------------------------------------------------------
# fetch() — Strategy 2: LLM text analysis of all page links
# ---------------------------------------------------------------------------


class TestFetchStrategy2TextAnalysis:
    @pytest.mark.asyncio
    async def test_llm_text_discovers_pdf_url(self) -> None:
        scraper = _make_scraper()
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True

        page = _make_page_mock(
            direct_pdf_links=[],   # no direct PDFs
            all_links=[
                {"href": "https://store.com/brochure-viewer", "text": "View brochure"},
                {"href": "https://cdn.store.com/weekly.pdf", "text": "Download"},
            ],
        )
        pw = _make_pw_mock(_make_browser_mock(page))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            patch(
                "app.scrapers.llm_parser.discover_pdf_urls",
                return_value=["https://cdn.store.com/weekly.pdf"],
            ),
            _patch_playwright(pw),
        ):
            result = await scraper.fetch()

        assert result[0]["pdf_url"] == "https://cdn.store.com/weekly.pdf"


# ---------------------------------------------------------------------------
# fetch() — Strategy 3: screenshot / vision fallback
# ---------------------------------------------------------------------------


class TestFetchStrategy3Vision:
    @pytest.mark.asyncio
    async def test_vision_fallback_used_when_text_fails(self) -> None:
        scraper = _make_scraper()
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True

        page = _make_page_mock(
            direct_pdf_links=[],
            all_links=[],
            screenshot_bytes=b"\xff\xd8\xff\xe0testscreenshot",
        )
        pw = _make_pw_mock(_make_browser_mock(page))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            patch(
                "app.scrapers.llm_parser.discover_pdf_urls",
                return_value=[],   # text analysis fails
            ),
            patch(
                "app.scrapers.llm_parser.discover_pdf_urls_from_screenshot",
                return_value=["https://cdn.store.com/vision-found.pdf"],
            ) as mock_vision,
            _patch_playwright(pw),
        ):
            result = await scraper.fetch()

        mock_vision.assert_called_once()
        assert result[0]["pdf_url"] == "https://cdn.store.com/vision-found.pdf"

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_strategies_fail(self) -> None:
        scraper = _make_scraper()
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True

        page = _make_page_mock(direct_pdf_links=[], all_links=[])
        pw = _make_pw_mock(_make_browser_mock(page))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            patch("app.scrapers.llm_parser.discover_pdf_urls", return_value=[]),
            patch(
                "app.scrapers.llm_parser.discover_pdf_urls_from_screenshot",
                return_value=[],
            ),
            _patch_playwright(pw),
        ):
            result = await scraper.fetch()

        assert result == []

    @pytest.mark.asyncio
    async def test_playwright_exception_returns_empty(self) -> None:
        scraper = _make_scraper()
        mock_llm = MagicMock()
        mock_llm.is_available.return_value = True

        page = MagicMock()
        page.goto = AsyncMock(side_effect=RuntimeError("net::ERR_NAME_NOT_RESOLVED"))
        page.wait_for_timeout = AsyncMock()

        pw = _make_pw_mock(_make_browser_mock(page))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            _patch_playwright(pw),
        ):
            result = await scraper.fetch()

        assert result == []


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------


class TestParse:
    def test_empty_raw_returns_empty(self) -> None:
        assert _make_scraper().parse([]) == []

    def test_skips_entry_without_pdf_url(self) -> None:
        result = _make_scraper().parse([{"title": "no url here"}])
        assert result == []

    def test_llm_parse_called_when_enabled(self) -> None:
        from app.scrapers.base import ScrapedItem

        scraped = ScrapedItem(name="Кисело мляко", price=Decimal("1.29"))
        mock_llm = MagicMock()

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch(
                "app.scrapers.llm_parser.OllamaVisionClient",
                return_value=mock_llm,
            ),
            patch(
                "app.scrapers.llm_parser.parse_pdf_with_llm",
                return_value=[MagicMock()],
            ),
            patch(
                "app.scrapers.llm_parser.llm_items_to_scraped",
                return_value=[scraped],
            ),
        ):
            result = _make_scraper().parse([{"pdf_url": "https://cdn.test/a.pdf"}])

        assert len(result) == 1
        assert result[0].name == "Кисело мляко"

    def test_regex_fallback_when_llm_disabled(self) -> None:
        from app.scrapers.base import ScrapedItem

        scraped = ScrapedItem(name="Банани", price=Decimal("1.99"))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=False),
            ),
            patch(
                "app.scrapers.pdf_parser.parse_pdf_brochure",
                return_value=[MagicMock()],
            ),
            patch(
                "app.scrapers.pdf_parser.brochure_items_to_scraped",
                return_value=[scraped],
            ),
        ):
            result = _make_scraper().parse([{"pdf_url": "https://cdn.test/a.pdf"}])

        assert len(result) == 1

    def test_parse_error_skipped_continues(self) -> None:
        from app.scrapers.base import ScrapedItem

        ok_item = ScrapedItem(name="Домати", price=Decimal("2.49"))

        with (
            patch(
                "app.config.get_settings",
                return_value=_mock_settings(llm_enabled=True),
            ),
            patch("app.scrapers.llm_parser.OllamaVisionClient"),
            patch(
                "app.scrapers.llm_parser.parse_pdf_with_llm",
                side_effect=[RuntimeError("timeout"), [MagicMock()]],
            ),
            patch(
                "app.scrapers.llm_parser.llm_items_to_scraped",
                return_value=[ok_item],
            ),
        ):
            result = _make_scraper().parse([
                {"pdf_url": "https://cdn.test/broken.pdf"},
                {"pdf_url": "https://cdn.test/ok.pdf"},
            ])

        assert len(result) == 1
        assert result[0].name == "Домати"


# ---------------------------------------------------------------------------
# normalise()
# ---------------------------------------------------------------------------


class TestNormalise:
    def test_strips_and_titlecases(self) -> None:
        from app.scrapers.base import ScrapedItem

        item = ScrapedItem(
            name="  пилешко филе охладено  ",
            price=Decimal("11.99"),
            unit=" кг ",
        )
        result = _make_scraper().normalise(item)
        assert result.name == "Пилешко Филе Охладено"
        assert result.unit == "кг"
        assert result.currency == "EUR"
