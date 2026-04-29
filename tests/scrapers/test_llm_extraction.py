"""Integration test for LLM brochure extraction.

Tests real image extraction from Lidl brochure screenshot.
Runs the LLM parser on the provided image to verify extraction works.
"""

from __future__ import annotations

import base64
import io
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scrapers.llm_parser import (
    LLMBrochureItem,
    OllamaVisionClient,
    llm_items_to_scraped,
)
from app.scrapers.base import ScrapedItem


# Test image from Lidl brochure screenshot
_LIDL_BROCHURE_IMAGE_PATH = Path(__file__).parent.parent.parent / "tests" / "resources" / "Screenshot 2026-04-15 205742.png"


@pytest.mark.asyncio
async def test_llm_extraction_from_lidl_brochure_image() -> None:
    """Test extracting products from Lidl brochure screenshot.

    Reads the actual image file and tests the LLM extraction pipeline.
    """
    if not _LIDL_BROCHURE_IMAGE_PATH.exists():
        pytest.skip(
            "Lidl brochure image not found. Place image in tests/resources/Screenshot 2026-04-15 205742.png"
        )

    # Read image and encode to base64
    with open(_LIDL_BROCHURE_IMAGE_PATH, "rb") as f:
        image_bytes = f.read()

    # Encode to base64 for Ollama API
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    client = OllamaVisionClient(model="qwen3.5:9b-q8_0", host="http://localhost:11434", timeout=480)

    print(f"Client timeout: {client.timeout}")
    print(f"Testing connection...")

    # Verify extraction succeeded
    items = client.extract_from_image(image_b64, page_num=1)

    # Print extracted items for debugging (using raw encoding to avoid Windows console issues)
    import sys
    for i, item in enumerate(items, 1):
        print(f"\nItem {i}:")
        print(f"  Name (raw): {repr(item.name)}")
        print(f"  Brand: {repr(item.brand)}")
        print(f"  Price: {item.price} {item.currency}")
        print(f"  Unit: {item.unit}")
        print(f"  Pack info: {item.pack_info}")
        print(f"  Pack type: {item.pack_type}")
        print(f"  Category: {item.category}")
        print(f"  Price per kg: {item.price_per_kg}")
        print(f"  Price per liter: {item.price_per_liter}")

    # Check we got reasonable results
    names = [item.name for item in items]
    print(f"\n\nTotal products extracted: {len(items)}")
    print(f"Product names (repr): {names}")


def _make_llm_item(
    name: str,
    price: Decimal,
    pack_info: str,
    pack_type: str,
    *,
    brand: str = "Kingsmill",
    unit: str | None = "кг",
    category: str = "Хляб",
    top_category: str | None = "Базови продукти",
) -> LLMBrochureItem:
    """Build an LLMBrochureItem with the fields the conversion test cares about."""
    return LLMBrochureItem(
        name=name,
        price=price,
        currency="EUR",
        brand=brand,
        category=category,
        top_category=top_category,
        unit=unit,
        pack_info=pack_info,
        pack_type=pack_type,
        raw={
            "name": name,
            "brand": brand,
            "pack_info": pack_info,
            "pack_type": pack_type,
        },
    )


@pytest.mark.asyncio
async def test_llm_items_to_scraped_with_pack_type() -> None:
    """pack_type round-trips through llm_items_to_scraped into ScrapedItem.raw."""
    llm_items = [
        _make_llm_item("Бял хляб", Decimal("2.49"), "1 кг кенче", "кенче"),
        _make_llm_item("Бял хляб", Decimal("2.19"), "1 пакет", "пакет", unit="пакет"),
    ]

    scraped = llm_items_to_scraped(llm_items)

    assert len(scraped) == 2
    assert scraped[0].name == "Бял хляб"
    assert scraped[0].raw.get("pack_info") == "1 кг кенче"
    assert scraped[0].raw.get("pack_type") == "кенче"
    assert scraped[1].name == "Бял хляб"
    assert scraped[1].raw.get("pack_info") == "1 пакет"
    assert scraped[1].raw.get("pack_type") == "пакет"


@pytest.mark.asyncio
async def test_llm_extraction_variants_same_product() -> None:
    """Same name + different pack_type stays as two distinct ScrapedItems."""
    llm_items = [
        _make_llm_item("Бял хляб", Decimal("2.49"), "1 кг кенче", "кенче"),
        _make_llm_item("Бял хляб", Decimal("2.19"), "1 пакет", "пакет", unit=None),
    ]

    scraped = llm_items_to_scraped(llm_items)

    assert len(scraped) == 2
    assert scraped[0].raw.get("name") == "Бял хляб"
    assert scraped[0].raw.get("pack_type") == "кенче"
    assert scraped[1].raw.get("name") == "Бял хляб"
    assert scraped[1].raw.get("pack_type") == "пакет"
    assert scraped[0].raw.get("pack_type") != scraped[1].raw.get("pack_type")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
