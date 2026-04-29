"use client";

import { useState } from "react";
import Link from "next/link";
import { Store, ImageIcon, Package, Tag } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { resolveImageUrl } from "@/lib/utils";
import type { ProductFamilyListItem } from "@/types";

interface ProductCardProps {
  product: ProductFamilyListItem;
}

function formatPrice(price: number | null | undefined, currency = "EUR"): string {
  if (price == null) return "—";
  return new Intl.NumberFormat("bg-BG", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(price);
}

function formatPerUnit(price: number | null | undefined, basis: string | null | undefined): string | null {
  if (price == null || !basis) return null;
  return `${new Intl.NumberFormat("bg-BG", {
    style: "currency",
    currency: "EUR",
    minimumFractionDigits: 2,
  }).format(price)} / ${basis}`;
}

export function ProductCard({ product }: ProductCardProps) {
  const [imgError, setImgError] = useState(false);
  const showPlaceholder = !product.image_url || imgError;
  const perUnit = formatPerUnit(product.lowest_price_per_unit, product.per_unit_basis);

  return (
    <Card className="group flex flex-col overflow-hidden transition-shadow hover:shadow-md focus-within:ring-2 focus-within:ring-primary focus-within:ring-offset-2">
      <div className="relative w-full overflow-hidden bg-muted">
        {showPlaceholder ? (
          <div
            className="bg-muted h-32 w-full flex items-center justify-center text-muted-foreground"
            aria-hidden="true"
          >
            <ImageIcon className="h-10 w-10 opacity-30" />
          </div>
        ) : (
          <div className="w-full h-32">
            <img
              src={resolveImageUrl(product.image_url) ?? ""}
              alt={product.name}
              loading="lazy"
              className="w-full h-32 object-contain"
              onError={() => setImgError(true)}
            />
          </div>
        )}
      </div>

      <CardContent className="flex flex-1 flex-col gap-2 p-3">
        {product.category_name && (
          <p className="truncate text-xs text-muted-foreground">{product.category_name}</p>
        )}

        <Link
          href={`/products/by-name/${product.name_slug}`}
          className="line-clamp-2 text-sm font-semibold leading-snug text-foreground hover:text-primary focus:outline-none"
          aria-label={`${product.name} — ${product.brand_count} марки, ${product.store_count} магазина`}
        >
          {product.name}
        </Link>

        <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {product.brand_count > 0 && (
            <span className="inline-flex items-center gap-1">
              <Tag className="h-3 w-3" aria-hidden="true" />
              {product.brand_count} {product.brand_count === 1 ? "марка" : "марки"}
            </span>
          )}
          {product.pack_count > 0 && (
            <span className="inline-flex items-center gap-1">
              <Package className="h-3 w-3" aria-hidden="true" />
              {product.pack_count} {product.pack_count === 1 ? "разфасовка" : "разфасовки"}
            </span>
          )}
          {product.store_count > 0 && (
            <span className="inline-flex items-center gap-1">
              <Store className="h-3 w-3" aria-hidden="true" />
              {product.store_count} {product.store_count === 1 ? "магазин" : "магазина"}
            </span>
          )}
        </div>

        <div className="mt-auto">
          {product.lowest_price != null ? (
            <>
              <p className="text-xs text-muted-foreground">от</p>
              <p className="text-lg font-bold text-primary">
                {formatPrice(product.lowest_price)}
              </p>
              {perUnit && (
                <p className="text-xs text-muted-foreground">{perUnit}</p>
              )}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Няма цена</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
