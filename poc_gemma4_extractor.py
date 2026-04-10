"""
POC: Gemma 4 multimodal price extractor for Bulgarian grocery brochures.

Replaces regex-based PDF parsing with vision LLM extraction.
Runs locally on RTX 5070 Ti (16 GB VRAM) via Ollama.

Setup (one-time):
    1. Install Ollama  →  https://ollama.com/download
    2. Pull model      →  ollama pull gemma4:e4b        (~9.6 GB download)
    3. Install deps    →  pip install beautifulsoup4 lxml pillow pdfplumber httpx

Usage:
    python poc_gemma4_extractor.py                        # auto-resolves live Kaufland PDF
    python poc_gemma4_extractor.py path/to/brochure.pdf   # local PDF
    python poc_gemma4_extractor.py https://example.com/brochure.pdf

Outputs:
    - Console: extracted product table with all fields
    - poc_output/  directory: one JPEG crop per product (named by page + index)
    - poc_output/items.json: full structured data as JSON
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re as _re
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import httpx
import pdfplumber
from bs4 import BeautifulSoup
from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_HOST = "http://localhost:11434"
MODEL = "gemma4:e4b"       # ~9.6 GB — fits comfortably in 16 GB VRAM
# MODEL = "gemma4:26b"      # ~15 GB — higher accuracy, tighter VRAM fit
PAGE_DPI = 200             # Higher DPI → sharper crops; 200 is a good balance
MAX_PAGES = 5
OUTPUT_DIR = Path("poc_output")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_PUBLITAS_URL_RE = _re.compile(
    r"https://view\.publitas\.com/billa-bulgaria/[^\s\"'<>\\]+"
)
_PDF_URL_RE = _re.compile(
    r"https://view\.publitas\.com/\d+/\d+/pdfs/[^\"'<>\s]+\.pdf[^\"'<>\s]*"
)


# ---------------------------------------------------------------------------
# Dynamic PDF URL resolution
# ---------------------------------------------------------------------------


def resolve_kaufland_pdf() -> str | None:
    """Fetch Kaufland brochures listing page and return the current PDF URL."""
    url = "https://www.kaufland.bg/broshuri.html"
    logger.info("Resolving Kaufland PDF from %s", url)
    try:
        resp = httpx.get(url, headers={"User-Agent": _USER_AGENT},
                         follow_redirects=True, timeout=30)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Failed to fetch Kaufland brochures page: %s", exc)
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    tiles = soup.find_all("div", class_="m-flyer-tile")
    if not tiles:
        logger.error("No m-flyer-tile elements found on Kaufland page")
        return None

    chosen = next(
        (t for t in tiles if t.get("data-parameter") == "aktualna-broshura"),
        tiles[0],
    )
    pdf_url = chosen.get("data-download-url", "")
    if not pdf_url:
        logger.error("No data-download-url attribute on Kaufland tile")
        return None

    logger.info("Kaufland PDF URL: %s", pdf_url)
    return pdf_url


def resolve_billa_pdf() -> str | None:
    """Resolve the current Billa weekly brochure PDF URL via Publitas chain."""
    billa_page = "https://www.billa.bg/promocii/sedmichna-broshura"
    logger.info("Resolving Billa PDF from %s", billa_page)
    try:
        with httpx.Client(headers={"User-Agent": _USER_AGENT},
                          follow_redirects=True, timeout=30) as client:
            r1 = client.get(billa_page)
            r1.raise_for_status()
            publitas_matches = _PUBLITAS_URL_RE.findall(r1.text)
            if not publitas_matches:
                logger.error("No Publitas URL on Billa brochure page")
                return None
            publitas_url = publitas_matches[0].rstrip("\\").split("\\")[0].rstrip("/")
            r2 = client.get(publitas_url + "/")
            r2.raise_for_status()
            pdf_matches = _PDF_URL_RE.findall(r2.text)
            if not pdf_matches:
                logger.error("No PDF URL on Publitas page")
                return None
            pdf_url = pdf_matches[0]
            logger.info("Billa PDF URL: %s", pdf_url)
            return pdf_url
    except httpx.HTTPError as exc:
        logger.error("Failed to resolve Billa PDF: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Extraction schema + prompts
# ---------------------------------------------------------------------------

# Fixed grocery taxonomy — model must pick exactly one value from this list.
GROCERY_CATEGORIES = [
    "Плодове",
    "Зеленчуци",
    "Месо",
    "Птиче месо",
    "Риба и морски дарове",
    "Колбаси и деликатеси",
    "Сирена",
    "Мляко и кисело мляко",
    "Яйца",
    "Масло и маргарин",
    "Олио",
    "Хляб и тестени",
    "Ориз, бобови и зърнени",
    "Консерви и буркани",
    "Сосове и подправки",
    "Кафе",
    "Чай",
    "Вода",
    "Сокове",
    "Газирани напитки",
    "Алкохол",
    "Шоколад и сладкиши",
    "Бисквити и снаксове",
    "Замразени храни",
    "Почистващи препарати",
    "Козметика и хигиена",
    "Цветя и растения",
    "Домакински стоки",
    "Друго",
]

_CATEGORIES_STR = "\n".join(f"  - {c}" for c in GROCERY_CATEGORIES)

SYSTEM_PROMPT = f"""\
You are a precise grocery price extraction assistant.
Your task: read the grocery store brochure page image and extract ALL product offers.

Return ONLY valid JSON — no markdown fences, no explanation:
{{
  "items": [
    {{
      "name": "complete product name: brand + product_type combined",
      "brand": "brand name if printed separately, else null",
      "product_type": "product type printed below brand name, e.g. 'Олио' / 'Класик кафе', else null",
      "category": "one value from the CATEGORY LIST below",
      "description": "extra visible text: variant, flavour, origin, promo condition, else null",
      "price": 2.99,
      "original_price": 5.49,
      "discount_percent": 45,
      "currency": "EUR",
      "unit": "unit near price: кг / л / бр / г / мл / пак, else null",
      "pack_info": "multi-pack string e.g. '6 x 100 г' or '2 x 1 л', else null",
      "valid_from": "YYYY-MM-DD or null",
      "valid_to": "YYYY-MM-DD or null"
    }}
  ]
}}

━━━ CATEGORY LIST — pick the single best match ━━━
{_CATEGORIES_STR}

━━━ NAME / BRAND / PRODUCT TYPE ━━━
- Brochures show brand in large text (e.g. "VITA D'ORO") with product type in smaller text below (e.g. "Олио").
- Combine into name: "VITA D'ORO Олио". Also set brand="VITA D'ORO", product_type="Олио".
- Examples:
    "NESCAFE" + "Класик кафе"  → name="NESCAFE Класик кафе",  brand="NESCAFE",    product_type="Класик кафе",   category="Кафе"
    "VITA D'ORO" + "Олио"      → name="VITA D'ORO Олио",       brand="VITA D'ORO", product_type="Олио",          category="Олио"
    "PEPSI" + "Кола"            → name="PEPSI Кола",             brand="PEPSI",      product_type="Кола",          category="Газирани напитки"
    single line "Краставици"   → name="Краставици",             brand=null,         product_type=null,            category="Зеленчуци"
    single line "Ябълки"       → name="Ябълки",                 brand=null,         product_type=null,            category="Плодове"
    single line "Агнешка плешка" → name="Агнешка плешка",       brand=null,         product_type=null,            category="Месо"
    "Козунак"                  → name="Козунак",                brand=null,         product_type=null,            category="Хляб и тестени"
    "Яйца"                     → name="Яйца",                   brand=null,         product_type=null,            category="Яйца"
    "Сагина" (plant)           → name="Сагина",                 brand=null,         product_type=null,            category="Цветя и растения"

━━━ DESCRIPTION ━━━
- Extra text near the product: variant ("различни видове"), flavour, origin ("БГ"),
  promo condition ("от понеделник"), size info, etc.
- null if nothing extra is visible beyond name + price.

━━━ PRICES ━━━
- price: the final promotional price shown prominently.
- original_price: crossed-out / "was" price. null if not visible.
- discount_percent: the "-45%" badge number only (integer). null if not shown.
- Currency: лв / BGN → treat as EUR (Bulgaria adopted EUR Jan 2025).
- "1,99" and "1.99" both output as 1.99.

━━━ UNIT / PACK ━━━
- unit: per-unit measure next to price (кг, л, бр, г, мл, пак).
- pack_info: multi-pack string like "6 x 100 г", "промопакет 3 бр.".

━━━ DATES ━━━
- valid_from / valid_to: ISO date if a promotional date range is visible on this page.

NEVER invent data not visible in the image.
"""

USER_PROMPT = "Extract all product price offers from this grocery brochure page. Output JSON only."


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class LLMBrochureItem:
    """A single product offer extracted by Gemma 4 from a brochure page."""

    name: str
    price: Decimal
    currency: str = "EUR"
    brand: str | None = None
    product_type: str | None = None   # text printed below brand (e.g. "Олио", "Класик кафе")
    category: str | None = None       # standardised taxonomy value (e.g. "Кафе", "Зеленчуци")
    description: str | None = None
    original_price: Decimal | None = None
    discount_percent: int | None = None
    unit: str | None = None
    pack_info: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    # Base64-encoded product image from PDF-native extraction
    image_b64: str | None = None
    page: int = 1
    source: str = "llm_brochure"
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _image_to_b64(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode()


def _pil_to_jpeg_bytes(img: Image.Image, quality: int = 85) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
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


def _parse_llm_response(
    text: str,
    page_num: int,
    embedded_images: list[bytes] | None = None,
) -> list[LLMBrochureItem]:
    """Parse JSON from Gemma 4 into LLMBrochureItem objects.

    If embedded_images is provided, assigns PDF-native images to items
    by document order (top-to-bottom, left-to-right).
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("Page %d: JSON decode error — %s", page_num, exc)
        logger.debug("Raw: %.500s", text)
        return []

    items: list[LLMBrochureItem] = []
    for raw in data.get("items", []):
        price = _parse_decimal(raw.get("price"))
        if price is None:
            continue
        name = str(raw.get("name", "")).strip()
        if not name:
            continue

        # Validate category against taxonomy; fall back to "Друго"
        raw_cat = raw.get("category") or ""
        category = raw_cat if raw_cat in GROCERY_CATEGORIES else ("Друго" if raw_cat else None)

        items.append(
            LLMBrochureItem(
                name=name,
                price=price,
                currency=str(raw.get("currency", "EUR")).upper(),
                brand=raw.get("brand") or None,
                product_type=raw.get("product_type") or None,
                category=category,
                description=raw.get("description") or None,
                original_price=_parse_decimal(raw.get("original_price")),
                discount_percent=int(raw["discount_percent"])
                    if raw.get("discount_percent") is not None else None,
                unit=raw.get("unit") or None,
                pack_info=raw.get("pack_info") or None,
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


def _check_ollama() -> bool:
    try:
        resp = httpx.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        base_model = MODEL.split(":")[0]
        available = any(base_model in m for m in models)
        if not available:
            logger.error("Model %s not found. Run: ollama pull %s", MODEL, MODEL)
        return available
    except Exception as exc:  # noqa: BLE001
        logger.error("Ollama not reachable at %s: %s", OLLAMA_HOST, exc)
        return False


def _call_ollama(
    image_b64: str,
    page_num: int,
    embedded_images: list[bytes] | None = None,
) -> list[LLMBrochureItem]:
    """Send one page image to Gemma 4 and return extracted items."""
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT, "images": [image_b64]},
        ],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_ctx": 8192},
    }

    t0 = time.perf_counter()
    try:
        resp = httpx.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=120)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Page %d: Ollama request failed: %s", page_num, exc)
        return []

    elapsed = time.perf_counter() - t0
    content = resp.json()["message"]["content"]
    items = _parse_llm_response(content, page_num, embedded_images)
    logger.info("Page %d: %d item(s) in %.1fs", page_num, len(items), elapsed)
    return items


# ---------------------------------------------------------------------------
# Main extraction
# ---------------------------------------------------------------------------


def parse_pdf_with_llm(
    source: str | Path,
    store_slug: str = "unknown",
    *,
    max_pages: int = MAX_PAGES,
    dpi: int = PAGE_DPI,
    save_crops: bool = True,
) -> list[LLMBrochureItem]:
    """Parse a PDF brochure using Gemma 4 vision.

    Renders each page, sends to Gemma 4, extracts embedded product images.

    Args:
        source: Local path or HTTPS URL.
        store_slug: Store identifier for logging and output filenames.
        max_pages: Page limit.
        dpi: Render resolution.
        save_crops: If True, save product images to OUTPUT_DIR.

    Returns:
        List of LLMBrochureItem with image_b64 populated from PDF-native images.
    """
    source = str(source)

    if source.startswith(("http://", "https://")):
        logger.info("Downloading %s brochure from %s", store_slug, source)
        try:
            resp = httpx.get(source, follow_redirects=True, timeout=60)
            resp.raise_for_status()
            pdf_bytes: bytes | io.BytesIO = io.BytesIO(resp.content)
        except httpx.HTTPError as exc:
            raise ValueError(f"Download failed: {exc}") from exc
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")
        pdf_bytes = path.read_bytes()

    if save_crops:
        OUTPUT_DIR.mkdir(exist_ok=True)

    all_items: list[LLMBrochureItem] = []

    with pdfplumber.open(pdf_bytes) as pdf:
        pages = pdf.pages[:max_pages]
        logger.info("Processing %d/%d page(s) for %s", len(pages), len(pdf.pages), store_slug)

        for page in pages:
            page_num: int = page.page_number
            try:
                pil_img: Image.Image = page.to_image(resolution=dpi).original
                embedded_images = _extract_page_images(page)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Page %d: render failed — %s", page_num, exc)
                continue

            page_jpeg = _pil_to_jpeg_bytes(pil_img)
            items = _call_ollama(_image_to_b64(page_jpeg), page_num, embedded_images)

            if save_crops:
                for idx, item in enumerate(items):
                    if item.image_b64:
                        fname = OUTPUT_DIR / f"{store_slug}_p{page_num}_{idx:02d}.jpg"
                        fname.write_bytes(base64.b64decode(item.image_b64))

            all_items.extend(items)

    logger.info("LLM parse complete — %d item(s) from %s", len(all_items), store_slug)
    return all_items


# ---------------------------------------------------------------------------
# Comparison with existing regex parser
# ---------------------------------------------------------------------------


def _run_regex_parser(pdf_source: str) -> list[Any]:
    try:
        from app.scrapers.pdf_parser import parse_pdf_brochure
        return parse_pdf_brochure(pdf_source, store_slug="poc-comparison")
    except ImportError:
        logger.warning("app.scrapers.pdf_parser not importable — skipping comparison")
        return []


def _print_items(items: list[Any], label: str) -> None:
    print(f"\n{'=' * 70}")
    print(f"  {label}  ({len(items)} items)")
    print("=" * 70)
    for it in items[:30]:
        name = getattr(it, "name", "?")
        price = getattr(it, "price", "?")
        orig  = getattr(it, "original_price", None)
        disc  = getattr(it, "discount_percent", None)
        unit  = getattr(it, "unit", None)
        pack  = getattr(it, "pack_info", None)
        desc  = getattr(it, "description", None)
        brand = getattr(it, "brand", None)
        cat   = getattr(it, "category", None)
        img   = getattr(it, "image_b64", None)
        page  = getattr(it, "page", "?")

        price_str = f"{price}"
        if orig:
            price_str += f" (was {orig}"
            if disc:
                price_str += f", -{disc}%"
            price_str += ")"

        ptype = getattr(it, "product_type", None)
        meta: list[str] = []
        if unit:
            meta.append(unit)
        if pack:
            meta.append(pack)
        if brand:
            meta.append(f"brand={brand}")
        if ptype:
            meta.append(f"type={ptype}")
        if cat:
            meta.append(f"cat={cat}")
        if desc:
            meta.append(f'desc="{desc}"')
        if img:
            meta.append("img=YES")

        meta_str = f"  [{', '.join(meta)}]" if meta else ""
        print(f"  p{page}  {price_str:<24}  {name}{meta_str}")
    if len(items) > 30:
        print(f"  ... and {len(items) - 30} more")


def _save_json(items: list[LLMBrochureItem], path: Path) -> None:
    """Serialize items to JSON, converting Decimal/date to strings."""
    def _default(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        return str(obj)

    records = []
    for it in items:
        d = asdict(it)
        # Trim base64 in JSON output to keep file readable (reference only)
        if d.get("image_b64"):
            d["image_b64"] = f"<base64 {len(d['image_b64'])} chars>"
        records.append(d)

    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=_default), encoding="utf-8")
    logger.info("Saved %d items to %s", len(records), path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    if len(sys.argv) > 1:
        pdf_source: str | None = sys.argv[1]
        store_slug = "custom"
    else:
        print("\nResolving live Kaufland brochure URL...")
        pdf_source = resolve_kaufland_pdf()
        store_slug = "kaufland"
        if pdf_source is None:
            print("Kaufland resolution failed. Trying Billa...")
            pdf_source = resolve_billa_pdf()
            store_slug = "billa"
        if pdf_source is None:
            print("\n[ERROR] Could not resolve any live brochure PDF URL.")
            print("  Pass a local path or URL: python poc_gemma4_extractor.py /path/to/brochure.pdf")
            sys.exit(1)

    print("\n" + "=" * 70)
    print("  Gemma 4 Vision Price Extractor — POC")
    print(f"  Model   : {MODEL}")
    print(f"  Store   : {store_slug}")
    print(f"  Source  : {pdf_source}")
    print(f"  Pages   : up to {MAX_PAGES} @ {PAGE_DPI} DPI")
    print(f"  Output  : {OUTPUT_DIR}/")
    print("=" * 70)

    if not _check_ollama():
        print("\n[ERROR] Ollama is not running or model not pulled.")
        print("  Start:   ollama serve")
        print(f"  Pull:    ollama pull {MODEL}")
        sys.exit(1)

    # --- LLM extraction ---
    t0 = time.perf_counter()
    llm_items = parse_pdf_with_llm(pdf_source, store_slug=store_slug,
                                    max_pages=MAX_PAGES, dpi=PAGE_DPI, save_crops=True)
    llm_time = time.perf_counter() - t0

    _print_items(llm_items, f"Gemma 4  ({llm_time:.1f}s total)")

    # Save full JSON
    OUTPUT_DIR.mkdir(exist_ok=True)
    _save_json(llm_items, OUTPUT_DIR / "items.json")

    crops_saved = sum(1 for it in llm_items if it.image_b64)
    print(f"\n  Images saved: {crops_saved}/{len(llm_items)} items had images → {OUTPUT_DIR}/")
    print(f"  JSON saved  : {OUTPUT_DIR}/items.json")

    # --- Regex comparison ---
    t0 = time.perf_counter()
    regex_items = _run_regex_parser(pdf_source)
    regex_time = time.perf_counter() - t0

    if regex_items:
        filtered = [i for i in regex_items if getattr(i, "page", 1) <= MAX_PAGES]
        _print_items(filtered, f"Regex parser  ({regex_time:.1f}s, pages 1-{MAX_PAGES})")

    print(f"\n{'=' * 70}")
    print("  Summary")
    print("=" * 70)
    print(f"  LLM   : {len(llm_items):>4} items  in {llm_time:.1f}s  (images: {crops_saved})")
    if regex_items:
        print(f"  Regex : {len(regex_items):>4} items  in {regex_time:.1f}s  (all pages)")
    print()


if __name__ == "__main__":
    main()
