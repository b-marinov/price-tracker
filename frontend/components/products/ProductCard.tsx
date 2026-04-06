import Link from "next/link";
import Image from "next/image";
import { Store, ArrowRight } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
  return (
    <Card className="group flex flex-col overflow-hidden transition-shadow hover:shadow-md focus-within:ring-2 focus-within:ring-primary focus-within:ring-offset-2">
      {/* Product image */}
      <div className="relative aspect-square w-full overflow-hidden bg-muted">
        {product.image_url ? (
          <Image
            src={product.image_url}
            alt={product.name}
            fill
            sizes="(max-width: 640px) 50vw, (max-width: 1024px) 33vw, 25vw"
            className="object-contain p-2 transition-transform group-hover:scale-105"
          />
        ) : (
          <div
            className="flex h-full items-center justify-center text-muted-foreground"
            aria-hidden="true"
          >
            <Store className="h-12 w-12 opacity-30" />
          </div>
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
          aria-label={`${product.name}${product.brand ? ` — ${product.brand}` : ""}`}
        >
          {product.name}
        </Link>

        {/* Price + store count */}
        <div className="mt-auto flex items-end justify-between gap-2">
          <div>
            {product.lowest_price != null ? (
              <p className="text-base font-semibold text-primary">
                {formatPrice(product.lowest_price)}
              </p>
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

          {product.store_count > 1 && (
            <Button
              asChild
              variant="outline"
              size="sm"
              className="shrink-0 text-xs"
            >
              <Link href={`/products/${product.id}/compare`} aria-label={`Сравни цените за ${product.name}`}>
                Сравни
                <ArrowRight className="ml-1 h-3 w-3" aria-hidden="true" />
              </Link>
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
