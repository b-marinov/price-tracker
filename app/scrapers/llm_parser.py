"""LLM-based brochure parser using Gemma 4 vision via Ollama.

Drop-in replacement for :mod:`app.scrapers.pdf_parser`.  Instead of
regex-based text extraction it renders each PDF page to an image and asks
Gemma 4 to return a structured JSON list of product offers.

Also supports screenshot-based extraction (for JS-rendered stores such as
Lidl and Fantastico) by accepting raw image bytes directly via
:func:`extract_from_screenshot`.

Requirements (add to pyproject.toml):
    ollama>=0.4.0
    pdf2image>=1.17.0   # alternative renderer; pdfplumber.to_image() is default

Configuration (environment variables):
    LLM_PARSER_ENABLED   = "true"         # feature flag (default false)
    LLM_OLLAMA_HOST      = "http://localhost:11434"
    LLM_MODEL            = "gemma4:e4b"   # vision model — PDF/screenshot extraction
    LLM_TEXT_MODEL       = "qwen3.5:9b"  # text-only model — URL discovery tasks
    LLM_PAGE_DPI         = "150"
    LLM_TEMPERATURE      = "0.1"
    LLM_TIMEOUT_SECONDS  = "120"
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Runtime configuration (override via environment)
# ---------------------------------------------------------------------------

_OLLAMA_HOST: str = os.getenv("LLM_OLLAMA_HOST", "http://localhost:11434")
_MODEL: str = os.getenv("LLM_MODEL", "gemma4:e4b")
_TEXT_MODEL: str = os.getenv("LLM_TEXT_MODEL", "qwen3.5:9b")
_PAGE_DPI: int = int(os.getenv("LLM_PAGE_DPI", "150"))
_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.1"))
_TIMEOUT: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "120"))

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

# Sub-categories — Gemma picks exactly one of these
GROCERY_CATEGORIES: list[str] = [
    # Млечни продукти
    "Сирене",
    "Кисело мляко",
    "Прясно мляко",
    "Краве масло и маргарин",
    "Яйца",
    "Сметана и крем",
    "Млечни десерти",
    # Месо, риба и колбаси
    "Прясно месо",
    "Птиче месо",
    "Риба и морски дарове",
    "Колбаси и наденица",
    "Готови месни продукти",
    # Плодове и зеленчуци
    "Плодове",
    "Зеленчуци",
    "Гъби и маслини",
    # Хляб, тестени и зърнени
    "Хляб и питки",
    "Тестени изделия",
    "Брашно и зърнени",
    "Ориз и бобови",
    # Сладкиши и снаксове
    "Шоколад и бонбони",
    "Бисквити и вафли",
    "Торти и кексове",
    "Сладолед",
    "Чипс и солени снаксове",
    # Напитки
    "Вода и минерална вода",
    "Сокове и безалкохолни",
    "Кафе",
    "Чай и какао",
    "Бира",
    "Вино",
    "Спиртни напитки",
    # Подправки и консерви
    "Олио и мазнини",
    "Подправки и сосове",
    "Консерви и буркани",
    "Захар, сол и подсладители",
    "Замразени храни",
    # Специални
    "Детски храни",
    "Диетични и здравословни",
    "Домашни любимци",
    # Дом и хигиена
    "Почистващи препарати",
    "Хигиенни продукти",
    "Козметика и грижа за тяло",
    "Домакински стоки",
    # Нехранителни
    "Електроника",
    "Дрехи и обувки",
    "Спорт и свободно време",
    "Цветя и растения",
    # Catch-all
    "Друго",
]

# Maps sub-category → top-level category
CATEGORY_HIERARCHY: dict[str, str] = {
    "Сирене": "Млечни продукти",
    "Кисело мляко": "Млечни продукти",
    "Прясно мляко": "Млечни продукти",
    "Краве масло и маргарин": "Млечни продукти",
    "Яйца": "Млечни продукти",
    "Сметана и крем": "Млечни продукти",
    "Млечни десерти": "Млечни продукти",
    "Прясно месо": "Месо, риба и колбаси",
    "Птиче месо": "Месо, риба и колбаси",
    "Риба и морски дарове": "Месо, риба и колбаси",
    "Колбаси и наденица": "Месо, риба и колбаси",
    "Готови месни продукти": "Месо, риба и колбаси",
    "Плодове": "Плодове и зеленчуци",
    "Зеленчуци": "Плодове и зеленчуци",
    "Гъби и маслини": "Плодове и зеленчуци",
    "Хляб и питки": "Хляб, тестени и зърнени",
    "Тестени изделия": "Хляб, тестени и зърнени",
    "Брашно и зърнени": "Хляб, тестени и зърнени",
    "Ориз и бобови": "Хляб, тестени и зърнени",
    "Шоколад и бонбони": "Сладкиши и снаксове",
    "Бисквити и вафли": "Сладкиши и снаксове",
    "Торти и кексове": "Сладкиши и снаксове",
    "Сладолед": "Сладкиши и снаксове",
    "Чипс и солени снаксове": "Сладкиши и снаксове",
    "Вода и минерална вода": "Напитки",
    "Сокове и безалкохолни": "Напитки",
    "Кафе": "Напитки",
    "Чай и какао": "Напитки",
    "Бира": "Напитки",
    "Вино": "Напитки",
    "Спиртни напитки": "Напитки",
    "Олио и мазнини": "Подправки и консерви",
    "Подправки и сосове": "Подправки и консерви",
    "Консерви и буркани": "Подправки и консерви",
    "Захар, сол и подсладители": "Подправки и консерви",
    "Замразени храни": "Подправки и консерви",
    "Детски храни": "Специални",
    "Диетични и здравословни": "Специални",
    "Домашни любимци": "Домашни любимци",
    "Почистващи препарати": "Дом и хигиена",
    "Хигиенни продукти": "Дом и хигиена",
    "Козметика и грижа за тяло": "Дом и хигиена",
    "Домакински стоки": "Дом и хигиена",
    "Електроника": "Нехранителни стоки",
    "Дрехи и обувки": "Нехранителни стоки",
    "Спорт и свободно време": "Нехранителни стоки",
    "Цветя и растения": "Нехранителни стоки",
    "Друго": "Друго",
}

_CATEGORIES_STR = "\n".join(f"  - {c}" for c in GROCERY_CATEGORIES)

_SYSTEM_PROMPT = f"""\
You are a precise grocery price extraction assistant.
Your task: read the grocery store brochure page image and extract ALL product offers.

Return ONLY valid JSON — no markdown fences, no explanation:
{{
  "items": [
    {{
      "name": "specific product type/variant name WITHOUT brand (e.g. 'Класик кафе', 'Кока-Кола', 'Олио'). Use the most specific name printed. NOT the brand name itself.",
      "is_product": true,
      "brand": "brand name if printed separately, else null",
      "product_type": "product type/variant printed below brand name, e.g. 'Олио' / 'Класик кафе' / 'Кока-Кола', else null",
      "category": "one value from the CATEGORY LIST below",
      "description": "extra visible text: variant, flavour, origin, promo condition, else null",
      "price": 2.99,
      "original_price": 5.49,
      "discount_percent": 45,
      "currency": "EUR",
      "unit": "unit symbol used in price-per-unit label (кг / л / бр / г / мл / пак) — null for fixed-price items",
      "pack_info": "size/quantity AND packaging type when visible (e.g. '500 мл кенче', '330 мл стъклена бутилка', '1 л картонена кутия', '400 г пакет', '2 л пластмасова бутилка'). For plain size with no packaging type: '2 л', '500 г', '6 x 100 г'. null only if no size or quantity is visible.",
      "additional_info": "product specs, dimensions, technical details, or conditions printed near the product that don't fit elsewhere. Examples: '20 V, безжична, без батерия и зарядно', '42 x 29 x 4 cm или 41 x 26.5 x 6 cm', 'Ø20/24/28 cm', 'с карта KAUFLAND'. null if nothing extra.",
      "valid_from": "YYYY-MM-DD or null",
      "valid_to": "YYYY-MM-DD or null"
    }}
  ]
}}

━━━ CATEGORY LIST — pick the single best match ━━━
{_CATEGORIES_STR}

━━━ QUALITY FILTER ━━━
- is_product: true if this is a genuine product offer with a real name and price.
- Set is_product: false for: page headers/footers, legal disclaimers, promotional banners
  with no specific product (e.g. "Топ цена тази седмица"), size labels, navigation elements,
  garbled/repeated text, loyalty card messages, currency conversion notes.
- When is_product is false, still include the item in the array so it can be filtered.

━━━ NAME / BRAND / PRODUCT TYPE ━━━
- Brochures show brand in large text (e.g. "VITA D'ORO") with product type/variant below (e.g. "Олио").
- name = the MOST SPECIFIC product name/variant visible — NEVER the brand name itself.
  Use the product type text printed in the brochure, not a generic category label.
- brand = the brand name (e.g. "VITA D'ORO", "NESCAFE", "Coca-Cola").
- product_type = same as name when a brand is present.
- For unbranded items (fresh produce, generic foods), name = the descriptive item name.
- CRITICAL: If only a brand name is visible with no product type text, you MUST infer the
  product type from context — use the surrounding category, nearby products on the page, or
  your general knowledge of what that brand sells.
  NEVER output a Cyrillic transliteration of the brand as the product name
  (e.g. "Милка" for brand "Milka", "Хайнекен" for brand "Heineken" are just transliterations,
  NOT product type names). Ask yourself: "What kind of product does this brand make?" and use
  that Bulgarian product type word as name.
  NEVER use a brand name as the product name (name ≠ brand).
- Examples:
    "NESCAFE" + "Класик кафе"          → name="Класик кафе",         brand="NESCAFE",    product_type="Класик кафе",         pack_info="200 г"
    "NESCAFE" + "Голд"                 → name="Голд",                brand="NESCAFE",    product_type="Голд",                pack_info="200 г"
    "VITA D'ORO" + "Олио"              → name="Олио",                brand="VITA D'ORO", product_type="Олио",                pack_info="1 л"
    "Coca-Cola" + "Кока-Кола"          → name="Кока-Кола",           brand="Coca-Cola",  product_type="Кока-Кола",           pack_info="2 л"
    "Coca-Cola" + "Фанта Портокал"     → name="Фанта Портокал",      brand="Fanta",      product_type="Фанта Портокал",      pack_info="1.5 л"
    "PEPSI" + "Кола"                   → name="Кола",                brand="PEPSI",      product_type="Кола",                pack_info="2 л"
    "Ferrero" + "Шоколадови бонбони"   → name="Шоколадови бонбони",  brand="Ferrero",    product_type="Шоколадови бонбони",  pack_info="200 г"
    "Milka" + "Шоколадови бонбони"     → name="Шоколадови бонбони",  brand="Milka",      product_type="Шоколадови бонбони",  pack_info="100 г"
    "Coca-Cola" (only brand visible)   → name="Кока-Кола",           brand="Coca-Cola",  product_type="Кока-Кола"           (signature drink)
    "Heineken" (only brand visible)    → name="Бира",                brand="Heineken",   product_type="Бира"                (beer brand)
    "Jameson" (only brand visible)     → name="Уиски",               brand="Jameson",    product_type="Уиски"               (whisky brand)
    "Milka" (only brand visible)       → name="Шоколад",             brand="Milka",      product_type="Шоколад"             (chocolate brand)
    "Nutella" (only brand visible)     → name="Шоколадов крем",      brand="Nutella",    product_type="Шоколадов крем"      (spread brand)
    "Pringles" (only brand visible)    → name="Чипс",                brand="Pringles",   product_type="Чипс"                (crisps brand)
    "Activia" (only brand visible)     → name="Кисело мляко",        brand="Activia",    product_type="Кисело мляко"        (yoghurt brand)
    single line "Краставици"           → name="Краставици",          brand=null,         product_type=null,                  pack_info="1 кг"
    single line "Ябълки"               → name="Ябълки",              brand=null,         product_type=null
    single line "Агнешка плешка"       → name="Агнешка плешка",      brand=null,         product_type=null
    "Яйца" "10 бр."                    → name="Яйца",                brand=null,         product_type=null,                  pack_info="10 бр."

━━━ DESCRIPTION ━━━
- Extra text near the product: variant ("различни видове"), flavour, origin ("БГ"),
  promo condition ("от понеделник"), etc.
- null if nothing extra is visible beyond name + price.

━━━ PRICES ━━━
- price: the final promotional price shown prominently.
- original_price: crossed-out / "was" price. null if not visible.
- discount_percent: the "-45%" badge number only (integer). null if not shown.
- Currency: лв / BGN → treat as EUR (Bulgaria adopted EUR Jan 2025).
- "1,99" and "1.99" both output as 1.99.

━━━ UNIT / PACK ━━━
- unit: the unit symbol used in a price-per-unit label ONLY (e.g. "/кг", "/л" next to the price).
  Use "кг", "л", "г", "мл", "бр". null for fixed-price items sold as a whole unit.
- pack_info: capture the SIZE or QUANTITY plus PACKAGING TYPE when visible:
  * With packaging type: "500 мл кенче", "330 мл стъклена бутилка", "1 л картонена кутия",
    "400 г пакет", "2 л пластмасова бутилка", "750 мл стъкло", "330 мл кен"
  * Size only (no packaging type visible): "2 л", "0.5 л", "500 г", "1 кг", "330 мл"
  * Multi-pack: "6 x 100 г кенче", "2 x 1 л", "промопакет 3 бр."
  * Count pack: "10 бр.", "12 бр."
  null only if absolutely no size or quantity is mentioned.

━━━ DATES ━━━
- valid_from / valid_to: ISO date if a promotional date range is visible on this page.

NEVER invent data not visible in the image.
"""

_USER_PROMPT = (
    "Extract all product price offers from this grocery brochure page. "
    "Output JSON only."
)

_DISCOVERY_SYSTEM_PROMPT = """\
You are a web scraping assistant.
Given links extracted from a grocery store's brochure listing page,
identify ALL current brochure URLs on the page. There may be more than one.

Return ONLY valid JSON — no markdown fences, no explanation:
{"brochure_urls": ["https://...", "https://..."], "confidence": "high"}

Rules:
- brochure_urls: include ALL direct .pdf links AND interactive viewer links —
  every brochure thumbnail/link on the page, not just the first one
- Recognised viewer URL patterns: publitas.com, view.publitas.com,
  flippingbook.com, issuu.com, lidl.bg/l/*/broshura/, etc.
- Prefer links labelled "current", "weekly", "брошура", "свали", "изтегли", "PDF", "виж"
- Ignore navigation menus, social media, and unrelated links
- If multiple brochures appear on the page, return ALL of their URLs
- If nothing found: {"brochure_urls": [], "confidence": "low"}
"""

_DISCOVERY_VISION_PROMPT = """\
This is a screenshot of a grocery store's brochure listing page.
Find any brochure link, PDF download button, or interactive flipbook viewer link.
Return ONLY valid JSON — no markdown fences:
{"brochure_urls": ["https://..."], "confidence": "high"}
If nothing visible: {"brochure_urls": [], "confidence": "low"}
"""


# ---------------------------------------------------------------------------
# Data class — mirrors BrochureItem from pdf_parser
# ---------------------------------------------------------------------------


@dataclass
class LLMBrochureItem:
    """A single product offer extracted by the LLM from a brochure image.

    Attributes:
        name: Product display name as read from the image.
        price: Promotional price as a fixed-point decimal.
        currency: ISO 4217 code (EUR after Bulgaria's 2025 adoption).
        unit: Unit descriptor if visible (e.g. "кг", "л", "бр").
        valid_from: Start of promotional period, or None.
        valid_to: End of promotional period, or None.
        page: 1-based page number in the source PDF (1 for screenshots).
        source: Always "llm_brochure".
        raw: Raw JSON dict from the LLM for debugging.
    """

    name: str
    price: Decimal
    currency: str = "EUR"
    brand: str | None = None
    product_type: str | None = None   # text below brand name (e.g. "Олио", "Класик кафе")
    category: str | None = None       # standardised taxonomy value from GROCERY_CATEGORIES
    top_category: str | None = None   # parent category derived from CATEGORY_HIERARCHY
    description: str | None = None
    original_price: Decimal | None = None
    discount_percent: int | None = None
    unit: str | None = None
    pack_info: str | None = None
    additional_info: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    # Base64-encoded product image from PDF-native extraction
    image_b64: str | None = None
    page: int = 1
    source: str = "llm_brochure"
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _image_to_b64(image_bytes: bytes) -> str:
    """Base64-encode image bytes for Ollama's multimodal API."""
    return base64.b64encode(image_bytes).decode()


def _pil_to_jpeg_bytes(img: Any, quality: int = 85) -> bytes:
    """Encode a PIL Image to JPEG bytes.

    Args:
        img: PIL Image instance.
        quality: JPEG quality (1-95).

    Returns:
        JPEG bytes.
    """
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _render_page(page: Any, dpi: int) -> tuple[bytes, Any, list[bytes]]:
    """Render page to JPEG and extract embedded product images.

    Args:
        page: A ``pdfplumber.Page`` instance.
        dpi: Render resolution in dots-per-inch.

    Returns:
        A ``(jpeg_bytes, pil_image, embedded_images)`` tuple.
    """
    pil_img = page.to_image(resolution=dpi).original  # PIL.Image
    embedded = _extract_page_images(page)
    return _pil_to_jpeg_bytes(pil_img), pil_img, embedded


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO date string, returning None on failure.

    Args:
        value: ISO 8601 date string (``"YYYY-MM-DD"``) or None.

    Returns:
        A :class:`~datetime.date`, or ``None`` if parsing fails.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_decimal(value: Any) -> Decimal | None:
    """Safely parse a numeric value to Decimal, returning None on failure."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _extract_page_images(page: Any) -> list[bytes]:
    """Extract all embedded raster images from a pdfplumber page.

    Images are returned in document order (top-to-bottom, left-to-right),
    which matches the reading order of product cards in brochure grids.

    Args:
        page: A pdfplumber.Page instance.

    Returns:
        List of raw image bytes (JPEG or PNG), in document order.
    """
    images: list[bytes] = []
    # pdfplumber exposes images sorted by their position on the page
    page_images = sorted(
        page.images,
        key=lambda img: (round(img["y0"] / 50) * 50, img["x0"]),  # row-major order
    )
    for img_dict in page_images:
        try:
            stream = img_dict.get("stream")
            if stream is None:
                continue
            raw = stream.get_data() if hasattr(stream, "get_data") else bytes(stream)
            if len(raw) < 500:  # skip tiny icons/decorations
                continue
            images.append(raw)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Failed to extract page image: %s", exc)
    return images


_RE_HAS_LATIN = re.compile(r"[A-Za-z]")
_RE_HAS_CYRILLIC = re.compile(r"[\u0400-\u04ff]")

# Latin food/packaging terms that the LLM sometimes writes in Latin script
# inside an otherwise Cyrillic product name.  Map to their Bulgarian equivalents.
_LATIN_TO_BG: dict[str, str] = {
    "filet": "Филе",
    "fillet": "Филе",
    "schnitzel": "Шницел",
    "steak": "Стейк",
    "grill": "Грил",
    "burger": "Бургер",
    "nuggets": "Нъгетс",
    "salami": "Салами",
    "bacon": "Бекон",
    "pizza": "Пица",
    "pasta": "Паста",
    "yogurt": "Йогурт",
    "yoghurt": "Йогурт",
    "cheese": "Сирене",
    "butter": "Масло",
    "cream": "Крем",
    "milk": "Мляко",
    "juice": "Сок",
    "water": "Вода",
    "beer": "Бира",
    "wine": "Вино",
}


def _is_likely_brand_transliteration(name: str, brand: str) -> bool:
    """Return True if *name* looks like a Cyrillic phonetic copy of a Latin brand name.

    Uses a structural heuristic rather than a hardcoded brand list so it
    generalises to any brand: if the name is a single all-Cyrillic word and
    the brand is a single all-Latin word of similar length, the LLM most likely
    just transliterated the brand instead of inferring a product type.

    Args:
        name: Extracted product name.
        brand: Extracted brand name.

    Returns:
        True when the name appears to be a bare transliteration of the brand.
    """
    # Only flag single-word values — multi-word names are unlikely transliterations
    if " " in name.strip() or " " in brand.strip():
        return False
    name_all_cyrillic = bool(re.fullmatch(r"[\u0400-\u04ff]+", name))
    brand_all_latin = bool(re.fullmatch(r"[A-Za-z'\-]+", brand))
    # Length similarity: transliterations are usually within ±3 characters
    return name_all_cyrillic and brand_all_latin and abs(len(name) - len(brand)) <= 3


def _clean_mixed_script_name(name: str) -> str | None:
    """Attempt to fix a product name that mixes Latin and Cyrillic characters.

    The LLM occasionally writes fragments of a Bulgarian word in Latin
    (e.g. "Свинскоfilet" instead of "Свинско Филе").  This function tries
    to replace known Latin food-term fragments with their Cyrillic equivalents.

    Returns the cleaned name, or ``None`` if the name cannot be salvaged
    (caller should drop the item and log a warning).

    Args:
        name: Product name that contains both Latin and Cyrillic characters.

    Returns:
        Cleaned name with Latin fragments replaced, or ``None`` if unfixable.
    """
    result = name
    for latin, cyrillic in _LATIN_TO_BG.items():
        # Match the Latin term whether it appears as a standalone word OR
        # directly attached to a Cyrillic character (e.g. "Свинскоfilet").
        # Prepend a space to the replacement so that "Свинскоfilet" becomes
        # "Свинско Филе"; the trailing re.sub below collapses any double-space
        # that results when the Latin term was already preceded by a space.
        result = re.sub(
            rf"(?<![A-Za-z]){re.escape(latin)}(?![A-Za-z])",
            " " + cyrillic,
            result,
            flags=re.IGNORECASE,
        )
    # Check if Latin letters remain after substitution
    if _RE_HAS_LATIN.search(result):
        # Still mixed — could not fully clean; return None to signal drop
        return None
    # Normalise spacing that may have been left from the replacement
    return re.sub(r"\s+", " ", result).strip()


def _parse_llm_response(
    text: str,
    page_num: int,
    embedded_images: list[bytes] | None = None,
) -> list[LLMBrochureItem]:
    """Parse JSON from Gemma 4 into LLMBrochureItem objects.

    If ``embedded_images`` is provided, assigns PDF-native images to items
    by document order (top-to-bottom, left-to-right).

    Args:
        text: Raw LLM response string.
        page_num: Page number embedded in returned items.
        embedded_images: Optional list of raw image bytes extracted from the PDF page.

    Returns:
        A list of :class:`LLMBrochureItem` objects (may be empty on failure).
    """
    text = text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Page %d: JSON decode error — %s", page_num, exc)
        logger.debug("Raw LLM output: %.500s", text)
        return []

    if not isinstance(data, dict):
        logger.warning("Page %d: LLM returned non-object JSON (%s) — skipping", page_num, type(data).__name__)
        return []

    items: list[LLMBrochureItem] = []
    for raw in data.get("items", []):
        if not isinstance(raw, dict):
            continue
        if not raw.get("is_product", True):
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue

        # Reject items where the LLM used the brand name as the product name,
        # including cross-script cases where it output a Cyrillic transliteration
        # of a Latin brand (e.g. name="Милка", brand="Milka").
        item_brand_raw = str(raw.get("brand", "") or "").strip()
        if item_brand_raw and (
            name.lower() == item_brand_raw.lower()
            or _is_likely_brand_transliteration(name, item_brand_raw)
        ):
            logger.warning(
                "Page %d: name is brand or its transliteration (%r) — LLM failed to infer product type; dropping item",
                page_num, name,
            )
            continue

        # Reject / repair names that mix Latin and Cyrillic characters —
        # these are LLM transliteration errors (e.g. "Свинскоfilet").
        if _RE_HAS_LATIN.search(name) and _RE_HAS_CYRILLIC.search(name):
            fixed = _clean_mixed_script_name(name)
            if fixed:
                logger.debug(
                    "Page %d: mixed-script name fixed: %r → %r", page_num, name, fixed
                )
                name = fixed
            else:
                logger.warning(
                    "Page %d: dropping item with unfixable mixed-script name: %r",
                    page_num, name,
                )
                continue

        price = _parse_decimal(raw.get("price"))
        if price is None:
            logger.debug("Page %d: skipping item with invalid price: %s", page_num, raw)
            continue

        raw_cat = raw.get("category") or ""
        category = raw_cat if raw_cat in GROCERY_CATEGORIES else ("Друго" if raw_cat else None)
        top_category = CATEGORY_HIERARCHY.get(category, "Друго") if category else None

        items.append(
            LLMBrochureItem(
                name=name,
                price=price,
                currency=str(raw.get("currency", "EUR")).upper(),
                brand=raw.get("brand") or None,
                product_type=raw.get("product_type") or None,
                category=category,
                top_category=top_category,
                description=raw.get("description") or None,
                original_price=_parse_decimal(raw.get("original_price")),
                discount_percent=int(raw["discount_percent"])
                    if raw.get("discount_percent") is not None else None,
                unit=raw.get("unit") or None,
                pack_info=raw.get("pack_info") or None,
                additional_info=raw.get("additional_info") or None,
                valid_from=_parse_date(raw.get("valid_from")),
                valid_to=_parse_date(raw.get("valid_to")),
                image_b64=None,
                page=page_num,
                raw=raw,
            )
        )

    # Assign embedded images to products by document order
    if embedded_images:
        for i, item in enumerate(items):
            if i < len(embedded_images):
                item.image_b64 = _image_to_b64(embedded_images[i])

    return items


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------


class OllamaVisionClient:
    """Thin synchronous client for Ollama's /api/chat multimodal endpoint.

    Attributes:
        host: Base URL of the Ollama server.
        model: Model tag to use (e.g. "gemma4:e4b").
        temperature: Sampling temperature (low = more deterministic).
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        host: str = _OLLAMA_HOST,
        model: str = _MODEL,
        temperature: float = _TEMPERATURE,
        timeout: float = _TIMEOUT,
    ) -> None:
        self.host = host
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self._client = httpx.Client(timeout=self.timeout)

    def is_available(self) -> bool:
        """Check that Ollama is reachable and the target model is loaded.

        Returns:
            True if the model is available, False otherwise.
        """
        try:
            resp = self._client.get(f"{self.host}/api/tags", timeout=5)
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            base = self.model.split(":")[0]
            return any(base in m for m in models)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ollama availability check failed: %s", exc)
            return False

    def extract_from_image(
        self,
        image_b64: str,
        page_num: int,
        embedded_images: list[bytes] | None = None,
    ) -> list[LLMBrochureItem]:
        """Send one image to Gemma 4 and return extracted product offers.

        If ``embedded_images`` is provided, PDF-native images are assigned to
        items by document order instead of relying on bbox cropping.

        Args:
            image_b64: Base64-encoded JPEG or PNG image.
            page_num: Page number embedded in returned items.
            embedded_images: Optional list of raw image bytes extracted from the PDF page.

        Returns:
            List of :class:`LLMBrochureItem` (empty on any failure).
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_PROMPT,
                    "images": [image_b64],
                },
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": 8192,
            },
        }
        try:
            resp = self._client.post(f"{self.host}/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Page %d: Ollama request failed: %s", page_num, exc)
            return []

        body = resp.json()
        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content", "") if isinstance(message, dict) else ""
        if not content:
            logger.warning("Page %d: empty content from Ollama — body: %.200s", page_num, body)
        items = _parse_llm_response(content, page_num, embedded_images)
        logger.debug("Page %d: %d item(s) extracted via LLM", page_num, len(items))
        if not items:
            logger.debug(
                "Page %d: 0 items parsed — raw LLM content: %.500s",
                page_num, content,
            )
        return items

    def ask_text(self, system_prompt: str, user_message: str) -> str:
        """Send a text-only prompt to Gemma 4 and return the response string.

        Used for PDF URL discovery from page content (no image needed).

        Args:
            system_prompt: System instruction for the model.
            user_message: User message content.

        Returns:
            Raw response string from the model (may be JSON).
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_ctx": 8192,
            },
        }
        try:
            resp = self._client.post(f"{self.host}/api/chat", json=payload)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("Ollama text request failed: %s", exc)
            return ""
        body = resp.json()
        message = body.get("message") if isinstance(body, dict) else None
        return message.get("content", "") if isinstance(message, dict) else ""

    def close(self) -> None:
        """Release the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> OllamaVisionClient:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_default_client: OllamaVisionClient | None = None
_default_text_client: OllamaVisionClient | None = None


def _get_client() -> OllamaVisionClient:
    """Return or create the module-level vision client (lazy singleton)."""
    global _default_client  # noqa: PLW0603
    if _default_client is None:
        _default_client = OllamaVisionClient()
    return _default_client


def _get_text_client() -> OllamaVisionClient:
    """Return or create the module-level text client (lazy singleton).

    Uses ``LLM_TEXT_MODEL`` (default ``qwen3.5:9b``) for text-only tasks such
    as brochure URL discovery that do not require vision capabilities.
    """
    global _default_text_client  # noqa: PLW0603
    if _default_text_client is None:
        _default_text_client = OllamaVisionClient(model=_TEXT_MODEL)
    return _default_text_client


def parse_pdf_with_llm(
    source: str | Path,
    store_slug: str = "unknown",
    *,
    max_pages: int | None = None,
    dpi: int = _PAGE_DPI,
    client: OllamaVisionClient | None = None,
) -> list[LLMBrochureItem]:
    """Parse a PDF brochure using Gemma 4 vision.

    Accepts a local file path or an HTTP(S) URL.  For URL inputs the PDF is
    streamed into memory.  Each page is rendered to JPEG and sent to Gemma 4.

    This function is a drop-in replacement for
    :func:`app.scrapers.pdf_parser.parse_pdf_brochure`.

    Args:
        source: Local ``Path`` / path string, or an ``https://`` URL.
        store_slug: Identifying slug of the store (used in logging only).
        max_pages: Maximum number of pages to process (``None`` = all).
        dpi: Page render resolution in DPI.  150 is a good balance.
        client: Optional pre-configured :class:`OllamaVisionClient`.

    Returns:
        A list of :class:`LLMBrochureItem` objects, one per detected offer.

    Raises:
        ValueError: If *source* is a URL and the download fails.
        FileNotFoundError: If *source* is a local path that does not exist.
        RuntimeError: If Ollama is not reachable or the model is not pulled.
    """
    cl = client or _get_client()

    if not cl.is_available():
        raise RuntimeError(
            f"Ollama not available at {cl.host!r} or model {cl.model!r} not pulled. "
            f"Run: ollama pull {cl.model}"
        )

    source = str(source)

    # --- Acquire PDF bytes ---
    if source.startswith(("http://", "https://")):
        logger.info("Downloading brochure for %s from %s", store_slug, source)
        try:
            resp = httpx.get(source, follow_redirects=True, timeout=60)
            resp.raise_for_status()
            pdf_bytes: io.BytesIO = io.BytesIO(resp.content)
        except httpx.HTTPError as exc:
            raise ValueError(f"Download failed: {exc}") from exc
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        pdf_bytes = io.BytesIO(path.read_bytes())

    # --- Process pages ---
    all_items: list[LLMBrochureItem] = []
    with pdfplumber.open(pdf_bytes) as pdf:
        pages = pdf.pages if max_pages is None else pdf.pages[:max_pages]
        logger.info(
            "Processing %d page(s) for %s via %s", len(pages), store_slug, cl.model
        )
        for page in pages:
            page_num: int = page.page_number
            try:
                jpeg_bytes, _pil_img, embedded_images = _render_page(page, dpi)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Page %d: render failed — %s", page_num, exc)
                continue
            items = cl.extract_from_image(
                _image_to_b64(jpeg_bytes), page_num, embedded_images,
            )
            all_items.extend(items)

    logger.info(
        "LLM parse complete for %s — %d item(s)", store_slug, len(all_items)
    )
    return all_items


def extract_from_screenshot(
    image_bytes: bytes,
    store_slug: str = "unknown",
    *,
    client: OllamaVisionClient | None = None,
) -> list[LLMBrochureItem]:
    """Extract product offers from a single screenshot image.

    Intended for JS-rendered store pages captured via Playwright (e.g. Lidl,
    Fantastico).  The caller is responsible for capturing the screenshot and
    passing the raw JPEG or PNG bytes.

    Args:
        image_bytes: Raw JPEG or PNG image bytes.
        store_slug: Store identifier for logging.
        client: Optional pre-configured :class:`OllamaVisionClient`.

    Returns:
        A list of :class:`LLMBrochureItem` objects found in the screenshot.
    """
    cl = client or _get_client()
    if not cl.is_available():
        raise RuntimeError(
            f"Ollama not available at {cl.host!r} or model {cl.model!r} not pulled."
        )

    logger.info("Extracting from screenshot for %s via %s", store_slug, cl.model)
    items = cl.extract_from_image(_image_to_b64(image_bytes), page_num=1)
    logger.info("Screenshot extraction for %s — %d item(s)", store_slug, len(items))
    return items


def llm_items_to_scraped(items: list[LLMBrochureItem]) -> list[Any]:
    """Convert :class:`LLMBrochureItem` objects to :class:`ScrapedItem` format.

    Bridges LLM parser output to the existing scraper pipeline so items flow
    through the same normalisation and upsert path as regex-parsed items.

    Args:
        items: Output of :func:`parse_pdf_with_llm` or
            :func:`extract_from_screenshot`.

    Returns:
        A list of :class:`~app.scrapers.base.ScrapedItem` instances.
    """
    from app.scrapers.base import ScrapedItem

    result: list[ScrapedItem] = []
    for item in items:
        raw: dict[str, Any] = {
            **item.raw,
            "page": item.page,
            "brand": item.brand,
            "product_type": item.product_type,
            "category": item.category,
            "top_category": item.top_category,
            "description": item.description,
            "original_price": float(item.original_price) if item.original_price else None,
            "discount_percent": item.discount_percent,
            "pack_info": item.pack_info,
            "additional_info": item.additional_info,
            "image_b64": item.image_b64,
            "valid_from": item.valid_from.isoformat() if item.valid_from else None,
            "valid_to": item.valid_to.isoformat() if item.valid_to else None,
        }
        result.append(
            ScrapedItem(
                name=item.name,
                price=item.price,
                currency=item.currency,
                unit=item.unit,
                source="llm_brochure",
                raw=raw,
            )
        )
    return result


def discover_pdf_urls(
    page_content: str,
    *,
    client: OllamaVisionClient | None = None,
) -> list[str]:
    """Use qwen3.5:9b (text mode) to identify PDF download URLs from page content.

    Sends the link list / text extracted from a store's brochure listing page
    to the text model and returns direct PDF URLs it identifies.

    Args:
        page_content: Text content and links extracted from the rendered page DOM.
        client: Optional pre-configured :class:`OllamaVisionClient`.

    Returns:
        List of PDF URL strings (may be empty if none found or on failure).
    """
    cl = client or _get_text_client()
    if not cl.is_available():
        logger.warning(
            "Text model %r not available — skipping URL discovery. "
            "Run: ollama pull %s",
            cl.model,
            cl.model,
        )
        return []
    try:
        raw = cl.ask_text(_DISCOVERY_SYSTEM_PROMPT, page_content)
        data = json.loads(raw)
        urls = data.get("brochure_urls") or data.get("pdf_urls", [])
        confidence = data.get("confidence", "low")
        logger.info(
            "PDF URL discovery via %s: %d candidate(s) (confidence=%s)",
            cl.model,
            len(urls),
            confidence,
        )
        return [u for u in urls if isinstance(u, str) and u.startswith("http")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF URL discovery (text mode) failed: %s", exc)
        return []


def discover_pdf_urls_from_screenshot(
    image_b64: str,
    *,
    client: OllamaVisionClient | None = None,
) -> list[str]:
    """Use Gemma 4 vision to identify PDF download URLs from a page screenshot.

    Fallback for pages where text/link extraction fails.  Sends a JPEG
    screenshot to Gemma 4 and asks it to locate PDF download buttons.

    Args:
        image_b64: Base64-encoded JPEG screenshot of the brochure listing page.
        client: Optional pre-configured :class:`OllamaVisionClient`.

    Returns:
        List of PDF URL strings (may be empty if none found or on failure).
    """
    cl = client or _get_client()
    payload = {
        "model": cl.model,
        "messages": [
            {
                "role": "user",
                "content": _DISCOVERY_VISION_PROMPT,
                "images": [image_b64],
            },
        ],
        "format": "json",
        "stream": False,
        "options": {
            "temperature": cl.temperature,
            "num_ctx": 4096,
        },
    }
    try:
        resp = cl._client.post(f"{cl.host}/api/chat", json=payload)
        resp.raise_for_status()
        body = resp.json()
        message = body.get("message") if isinstance(body, dict) else None
        content = message.get("content", "") if isinstance(message, dict) else ""
        data = json.loads(content)
        urls = data.get("brochure_urls") or data.get("pdf_urls", [])
        logger.info("PDF URL discovery (vision): %d candidate(s)", len(urls))
        return [u for u in urls if isinstance(u, str) and u.startswith("http")]
    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF URL discovery (vision mode) failed: %s", exc)
        return []
