"use client";

import { useState } from "react";
import Link from "next/link";
import { Store, ImageIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { resolveImageUrl } from "@/lib/utils";
import type { ProductListItem } from "@/types";

interface ProductCardProps {
  product: ProductListItem;
}

function formatPrice(price: number | null | undefined, currency = "EUR"): string {
  if (price == null) return "—";
  return new Intl.NumberFormat("bg-BG", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(price);
}

export function ProductCard({ product }: ProductCardProps) {
  const [imgError, setImgError] = useState(false);

  const showPlaceholder = !product.image_url || imgError;

  return (
    <Card className="group flex flex-col overflow-hidden transition-shadow hover:shadow-md focus-within:ring-2 focus-within:ring-primary focus-within:ring-offset-2">
      {/* Product image */}
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

        {/* Discount badge */}
        {product.discount_percent != null && product.discount_percent > 0 && (
          <Badge
            variant="destructive"
            className="absolute right-2 top-2 text-xs font-bold"
            aria-label={`Отстъпка ${product.discount_percent} процента`}
          >
            -{product.discount_percent}%
          </Badge>
        )}
      </div>

      <CardContent className="flex flex-1 flex-col gap-2 p-3">
        {/* Brand */}
        {product.brand && (
          <p className="truncate text-xs text-muted-foreground">{product.brand}</p>
        )}

        {/* Name */}
        <Link
          href={`/products/${product.id}`}
          className="line-clamp-2 text-sm font-medium leading-snug text-foreground hover:text-primary focus:outline-none"
          aria-label={`${product.name}${product.pack_info ? ` ${product.pack_info}` : ""}${product.brand ? ` — ${product.brand}` : ""}`}
        >
          {product.name}
          {product.pack_info && (
            <span className="ml-1 text-xs font-normal text-muted-foreground">{product.pack_info}</span>
          )}
        </Link>

        {/* Price + store count */}
        <div className="mt-auto flex items-end justify-between gap-2">
          <div>
            {product.lowest_price != null ? (
              <div>
                <p className="text-base font-semibold text-primary">
                  {formatPrice(product.lowest_price)}
                </p>
                {product.original_price != null && product.original_price > (product.lowest_price ?? 0) && (
                  <p className="text-xs text-muted-foreground line-through" aria-label={`Стара цена ${formatPrice(product.original_price)}`}>
                    {formatPrice(product.original_price)}
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Няма цена</p>
            )}
            {product.store_count > 0 && (
              <p className="flex items-center gap-1 text-xs text-muted-foreground">
                <Store className="h-3 w-3" aria-hidden="true" />
                <span>{product.store_count} {product.store_count === 1 ? "магазин" : "магазина"}</span>
              </p>
            )}
          </div>

        </div>
      </CardContent>
    </Card>
  );
}
