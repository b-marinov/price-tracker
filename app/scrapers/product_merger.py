"""Post-scrape LLM-powered product deduplication.

Runs daily after all scrapers complete.  Finds pairs of products with
similar names, asks Ollama to decide if they represent the same real-world
item, and merges duplicates automatically (no human approval required).

Merge operation:
- All Price records for the dropped product are reassigned to the kept product.
- The kept product's name, brand, and category are updated to the LLM-chosen
  canonical values.
- The dropped product row is deleted.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.price import Price
from app.models.product import Product
from app.scrapers.llm_parser import OllamaVisionClient
from app.scrapers.matching import normalise_name

logger = logging.getLogger(__name__)

# Minimum fuzzy-name similarity to consider a pair as a merge candidate.
_CANDIDATE_THRESHOLD: float = 80.0

_MERGE_SYSTEM_PROMPT = """\
You are a grocery product deduplication assistant for a Bulgarian price tracker.

You will be shown two product records.  Decide whether they represent the
SAME real-world product that should be merged into one record.

Merge criteria:
- Same generic product type AND same brand (or both unbranded) → merge
- Same generic product type but different brands (e.g. Milka vs Nestlé) → do NOT merge
- One is clearly a sub-type of the other (e.g. "Кафе" vs "Нескафе Класик Кафе") → use your judgement

Return ONLY valid JSON — no markdown, no explanation:
{
  "merge": true,
  "canonical_name": "the best product name to keep (Bulgarian, generic type only, no brand)",
  "canonical_brand": "brand name or null",
  "reason": "one sentence"
}

If merge=false:
{
  "merge": false,
  "canonical_name": null,
  "canonical_brand": null,
  "reason": "one sentence"
}
"""


@dataclass
class MergeDecision:
    """LLM decision for a product pair."""

    should_merge: bool
    canonical_name: str | None
    canonical_brand: str | None
    reason: str


def _build_merge_prompt(a: Product, b: Product) -> str:
    """Format two products for the merge-decision prompt.

    Args:
        a: First product candidate.
        b: Second product candidate.

    Returns:
        User message string for the LLM.
    """
    def fmt(p: Product) -> str:
        parts = [f"name: {p.name!r}"]
        if p.brand:
            parts.append(f"brand: {p.brand!r}")
        return ", ".join(parts)

    return f"Product A — {fmt(a)}\nProduct B — {fmt(b)}"


def _parse_merge_response(raw: str) -> MergeDecision:
    """Parse LLM JSON into a MergeDecision.

    Strips markdown fences if present.  Falls back to ``should_merge=False``
    on any parse error so a bad response never triggers an unintended merge.

    Args:
        raw: Raw text response from the LLM.

    Returns:
        Parsed :class:`MergeDecision`.
    """
    # Strip markdown fences
    cleaned = re.sub(r"```[a-z]*\n?", "", raw).strip()
    try:
        data: dict[str, Any] = json.loads(cleaned)
        return MergeDecision(
            should_merge=bool(data.get("merge", False)),
            canonical_name=data.get("canonical_name") or None,
            canonical_brand=data.get("canonical_brand") or None,
            reason=str(data.get("reason", "")),
        )
    except (json.JSONDecodeError, AttributeError):
        logger.warning(
            "Could not parse merge response — defaulting to no-merge. Raw: %.300s", raw
        )
        return MergeDecision(
            should_merge=False,
            canonical_name=None,
            canonical_brand=None,
            reason="parse error",
        )


async def _find_candidate_pairs(
    db: AsyncSession,
) -> list[tuple[Product, Product]]:
    """Return pairs of products whose names are fuzzy-similar.

    Uses rapidfuzz token-sort ratio so word-order variations ("Кафе Нескафе"
    vs "Нескафе Кафе") are treated as similar.

    Args:
        db: Async database session.

    Returns:
        List of (Product, Product) candidate pairs, each pair ordered so the
        lower-id product is first (dedup).
    """
    result = await db.execute(select(Product))
    products: list[Product] = list(result.scalars().all())

    pairs: list[tuple[Product, Product]] = []
    seen: set[tuple[str, str]] = set()

    for i, a in enumerate(products):
        norm_a = normalise_name(a.name)
        for b in products[i + 1 :]:
            key = (str(a.id), str(b.id))
            if key in seen:
                continue
            seen.add(key)

            score = fuzz.token_sort_ratio(norm_a, normalise_name(b.name))
            if score >= _CANDIDATE_THRESHOLD:
                pairs.append((a, b))

    logger.info("Found %d candidate pairs for deduplication", len(pairs))
    return pairs


async def _merge_into(
    db: AsyncSession,
    keep_id: object,
    drop_id: object,
    keep_name: str,
    drop_name: str,
    decision: MergeDecision,
) -> None:
    """Execute a merge using pure Core SQL to avoid ORM cache conflicts.

    All Price records for *drop_id* are reassigned to *keep_id*.
    The surviving product's name and brand are updated to the LLM-chosen
    canonical values.  The duplicate product row is then deleted.

    Uses Core-level statements exclusively so the ORM identity map does not
    interfere with the batch update before deletion.

    Args:
        db: Async database session.
        keep_id: UUID of the product that survives.
        drop_id: UUID of the product to be deleted.
        keep_name: Display name of the surviving product (for logging).
        drop_name: Display name of the dropped product (for logging).
        decision: LLM canonical attribute values.
    """
    # 1. Reassign all prices from drop → keep
    await db.execute(
        update(Price)
        .where(Price.product_id == drop_id)
        .values(product_id=keep_id)
    )

    # 2. Update canonical attributes on the surviving product
    update_vals: dict[str, Any] = {}
    if decision.canonical_name:
        update_vals["name"] = decision.canonical_name
    if decision.canonical_brand is not None:
        update_vals["brand"] = decision.canonical_brand or None
    if update_vals:
        await db.execute(
            update(Product).where(Product.id == keep_id).values(**update_vals)
        )

    # 3. Delete the duplicate (Core-level; avoids ORM cascade complications)
    await db.execute(delete(Product).where(Product.id == drop_id))

    logger.info(
        "Merged %r (id=%s) into %r (id=%s) — reason: %s",
        drop_name,
        drop_id,
        decision.canonical_name or keep_name,
        keep_id,
        decision.reason,
    )


async def run_merge_pass(db: AsyncSession, llm: OllamaVisionClient) -> dict[str, int]:
    """Run one full deduplication pass over the products table.

    Finds all fuzzy-similar product pairs, asks the LLM whether each pair
    should be merged, and executes confirmed merges in a single transaction.

    Products that have already been deleted earlier in the same pass (because
    they appeared in multiple candidate pairs) are skipped gracefully.

    Args:
        db: Async database session.
        llm: Configured :class:`~app.scrapers.llm_parser.OllamaVisionClient`.

    Returns:
        Dict with keys ``candidates``, ``merged``, ``skipped``.
    """
    pairs = await _find_candidate_pairs(db)

    merged_ids: set[str] = set()   # track IDs already consumed as "drop"
    stats = {"candidates": len(pairs), "merged": 0, "skipped": 0}

    for a, b in pairs:
        # Skip if either product was already merged away in this pass
        if str(a.id) in merged_ids or str(b.id) in merged_ids:
            stats["skipped"] += 1
            continue

        prompt = _build_merge_prompt(a, b)
        try:
            raw_response = llm.ask_text(_MERGE_SYSTEM_PROMPT, prompt)
            decision = _parse_merge_response(raw_response)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "LLM merge decision failed for (%r, %r): %s", a.name, b.name, exc
            )
            stats["skipped"] += 1
            continue

        if not decision.should_merge:
            logger.debug(
                "No merge: %r vs %r — %s", a.name, b.name, decision.reason
            )
            continue

        # Keep the product with the earlier created_at to preserve history.
        # Capture all values before entering the nested transaction so we
        # never access ORM-mapped attributes from an invalidated state.
        if a.created_at <= b.created_at:
            keep_id, keep_name = a.id, a.name
            drop_id, drop_name = b.id, b.name
        else:
            keep_id, keep_name = b.id, b.name
            drop_id, drop_name = a.id, a.name

        try:
            async with db.begin_nested():
                await _merge_into(
                    db, keep_id, drop_id, keep_name, drop_name, decision
                )
            merged_ids.add(str(drop_id))
            stats["merged"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Merge failed for (%r → %r): %s", drop_name, keep_name, exc
            )
            stats["skipped"] += 1

    await db.commit()

    logger.info(
        "Deduplication pass complete — candidates=%d merged=%d skipped=%d",
        stats["candidates"],
        stats["merged"],
        stats["skipped"],
    )
    return stats
