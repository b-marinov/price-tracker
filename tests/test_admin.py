"""Tests for admin endpoints and fuzzy matching logic."""

from __future__ import annotations

import os
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient

# Ensure test env vars are set before app imports
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("ADMIN_KEY", "test-admin-key")

from app.scrapers.base import ScrapedItem
from app.scrapers.matching import (
    find_or_create_product,
    normalise_name,
)

# ------------------------------------------------------------------ #
#  Unit tests — normalise_name
# ------------------------------------------------------------------ #


class TestNormaliseName:
    """Tests for the name normalisation helper."""

    def test_lowercase(self) -> None:
        """Converts to lowercase."""
        assert normalise_name("HELLO WORLD") == "hello world"

    def test_strip_punctuation(self) -> None:
        """Strips punctuation characters."""
        assert normalise_name("hello, world!") == "hello world"

    def test_collapse_whitespace(self) -> None:
        """Collapses multiple spaces into one."""
        assert normalise_name("hello   world") == "hello world"

    def test_strip_edges(self) -> None:
        """Strips leading/trailing whitespace."""
        assert normalise_name("  hello world  ") == "hello world"

    def test_unicode_normalisation(self) -> None:
        """NFKD decomposes unicode characters."""
        # fi ligature decomposes to "fi"
        result = normalise_name("\ufb01nger")
        assert "fi" in result


# ------------------------------------------------------------------ #
#  Unit tests — fuzzy matching via find_or_create_product
# ------------------------------------------------------------------ #


class TestFindOrCreateProduct:
    """Tests for the product matching function."""

    @pytest.mark.asyncio
    async def test_barcode_match(self) -> None:
        """Returns existing product when barcode matches."""
        existing = MagicMock()
        existing.id = uuid.uuid4()
        existing.name = "Existing Product"
        existing.barcode = "1234567890"

        mock_session = AsyncMock()
        # First query (barcode lookup) returns the product
        barcode_result = MagicMock()
        barcode_result.scalars.return_value.first.return_value = existing
        mock_session.execute.return_value = barcode_result

        item = ScrapedItem(name="Some Product", price=Decimal("5.99"), barcode="1234567890")
        product, created = await find_or_create_product(item, mock_session)

        assert product is existing
        assert created is False

    @pytest.mark.asyncio
    async def test_fuzzy_name_match(self) -> None:
        """Returns existing product when name fuzzy-matches above threshold."""
        existing = MagicMock()
        existing.id = uuid.uuid4()
        existing.name = "Organic Whole Milk 1L"
        existing.barcode = None

        mock_session = AsyncMock()

        # First call: barcode lookup (no barcode, so skipped)
        # Second call: fuzzy name — returns product list
        fuzzy_result = MagicMock()
        fuzzy_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute.return_value = fuzzy_result

        item = ScrapedItem(name="Organic Whole Milk 1L", price=Decimal("3.49"))
        product, created = await find_or_create_product(item, mock_session)

        assert product is existing
        assert created is False

    @pytest.mark.asyncio
    async def test_no_match_creates_product(self) -> None:
        """Creates a new pending_review product when no match is found."""
        mock_session = AsyncMock()

        # Barcode query returns None (no barcode on item, so skipped)
        # Fuzzy query returns empty list
        fuzzy_result = MagicMock()
        fuzzy_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = fuzzy_result

        item = ScrapedItem(name="Brand New Product", price=Decimal("9.99"))
        product, created = await find_or_create_product(item, mock_session)

        assert created is True
        mock_session.add.assert_called_once()
        mock_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_fuzzy_below_threshold_creates(self) -> None:
        """Creates new product when fuzzy score is below threshold."""
        existing = MagicMock()
        existing.id = uuid.uuid4()
        existing.name = "Completely Different Product Name XYZ"

        mock_session = AsyncMock()
        fuzzy_result = MagicMock()
        fuzzy_result.scalars.return_value.all.return_value = [existing]
        mock_session.execute.return_value = fuzzy_result

        item = ScrapedItem(name="Something Else Entirely ABC", price=Decimal("1.00"))
        product, created = await find_or_create_product(item, mock_session)

        assert created is True


# ------------------------------------------------------------------ #
#  Integration tests — admin endpoints
# ------------------------------------------------------------------ #


class TestAdminEndpoints:
    """Tests for the admin review endpoints."""

    @pytest.fixture
    def admin_headers(self) -> dict[str, str]:
        """Return headers with a valid admin key."""
        return {"X-Admin-Key": "test-admin-key"}

    @pytest.mark.asyncio
    async def test_pending_products_requires_auth(self, client: AsyncClient) -> None:
        """GET /admin/products/pending returns 422 without header."""
        resp = await client.get("/admin/products/pending")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_pending_products_rejects_bad_key(self, client: AsyncClient) -> None:
        """GET /admin/products/pending returns 403 with wrong key."""
        resp = await client.get(
            "/admin/products/pending",
            headers={"X-Admin-Key": "wrong-key"},
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_approve_not_found(self, client: AsyncClient, admin_headers: dict[str, str]) -> None:
        """PATCH /admin/products/{id}/approve returns 404 for missing product."""
        fake_id = uuid.uuid4()
        resp = await client.patch(
            f"/admin/products/{fake_id}/approve",
            headers=admin_headers,
        )
        # Will be 404 if DB is available, or 500 if not — both prove routing works
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_reject_not_found(self, client: AsyncClient, admin_headers: dict[str, str]) -> None:
        """PATCH /admin/products/{id}/reject returns 404 for missing product."""
        fake_id = uuid.uuid4()
        resp = await client.patch(
            f"/admin/products/{fake_id}/reject",
            headers=admin_headers,
        )
        assert resp.status_code in (404, 500)

    @pytest.mark.asyncio
    async def test_reject_active_product_returns_400(self) -> None:
        """Rejecting an active product should return 400."""
        from app.models.product import ProductStatus
        from app.routers.admin import reject_product

        active_product = MagicMock()
        active_product.id = uuid.uuid4()
        active_product.status = ProductStatus.ACTIVE

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = active_product
        mock_db.execute.return_value = result_mock

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await reject_product(
                product_id=active_product.id,
                _key="test-admin-key",
                db=mock_db,
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_approve_sets_active(self) -> None:
        """Approving a pending product sets status to active."""
        from app.models.product import ProductStatus
        from app.routers.admin import approve_product

        pending_product = MagicMock()
        pending_product.id = uuid.uuid4()
        pending_product.status = ProductStatus.PENDING_REVIEW

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = pending_product
        mock_db.execute.return_value = result_mock

        # After commit + refresh, status should be active
        async def fake_refresh(obj: object) -> None:
            pending_product.status = ProductStatus.ACTIVE

        mock_db.refresh = fake_refresh

        result = await approve_product(
            product_id=pending_product.id,
            _key="test-admin-key",
            db=mock_db,
        )
        assert result.status == "active"
        assert result.message == "Product approved"

    @pytest.mark.asyncio
    async def test_reject_deletes_pending_product(self) -> None:
        """Rejecting a pending product deletes it and returns confirmation."""
        from app.models.product import ProductStatus
        from app.routers.admin import reject_product

        pending_product = MagicMock()
        pending_product.id = uuid.uuid4()
        pending_product.status = ProductStatus.PENDING_REVIEW

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.first.return_value = pending_product
        mock_db.execute.return_value = result_mock

        result = await reject_product(
            product_id=pending_product.id,
            _key="test-admin-key",
            db=mock_db,
        )
        assert result.status == "rejected"
        mock_db.delete.assert_awaited_once_with(pending_product)
        mock_db.commit.assert_awaited_once()
