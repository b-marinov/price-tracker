"use client";

import { useEffect, useState } from "react";
import { Store as StoreIcon } from "lucide-react";

import { fetchDeals } from "@/lib/api";
import type { DealItem, DealsResponse } from "@/types";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(value: number): string {
  return value.toFixed(2);
}

// ---------------------------------------------------------------------------
// Skeleton loader
// ---------------------------------------------------------------------------

function DealsSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3">
      {Array.from({ length: 4 }).map((_, i) => (
        <Card key={i} className="overflow-hidden">
          <Skeleton className="h-40 w-full rounded-none" />
          <CardContent className="space-y-2 p-4">
            <Skeleton className="h-4 w-3/4" />
            <Skeleton className="h-4 w-1/2" />
            <Skeleton className="h-4 w-1/3" />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Deal card
// ---------------------------------------------------------------------------

interface DealCardProps {
  item: DealItem;
}

function DealCard({ item }: DealCardProps) {
  const [imgError, setImgError] = useState(false);

  return (
    <Card className="overflow-hidden transition-shadow hover:shadow-md">
      {/* Product image */}
      {item.image_url && !imgError ? (
        <img
          src={item.image_url}
          alt={item.product_name}
          loading="lazy"
          onError={() => setImgError(true)}
          className="h-40 w-full object-contain bg-muted"
        />
      ) : (
        <div
          className="h-40 w-full bg-muted"
          aria-hidden="true"
        />
      )}

      <CardContent className="space-y-2 p-4">
        {/* Discount badge */}
        <Badge variant="destructive" className="text-sm font-bold">
          &minus;{item.discount_percent}%
        </Badge>

        {/* Product name */}
        <p className="font-semibold leading-tight line-clamp-2">
          {item.product_name}
        </p>

        {/* Brand */}
        {item.brand !== null && (
          <p className="text-sm text-muted-foreground">{item.brand}</p>
        )}

        {/* Store badge */}
        <Badge variant="secondary" className="text-xs">
          <StoreIcon className="mr-1 h-3 w-3" aria-hidden="true" />
          {item.store}
        </Badge>

        {/* Prices */}
        <div className="flex items-baseline gap-2">
          <span className="text-lg font-bold">
            {formatPrice(item.price)}&nbsp;&euro;
          </span>
          {item.original_price !== null && (
            <span className="text-sm text-muted-foreground line-through">
              {formatPrice(item.original_price)}&nbsp;&euro;
            </span>
          )}
        </div>

        {/* Category breadcrumb */}
        {(item.top_category !== null || item.category !== null) && (
          <p className="text-xs text-muted-foreground">
            {[item.top_category, item.category]
              .filter(Boolean)
              .join(" \u203a ")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * Client-side deals page that fetches active discounts and renders them as a
 * filterable grid of deal cards sorted by discount percentage descending.
 */
export function DealsPage() {
  const [data, setData] = useState<DealsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [topCategory, setTopCategory] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    fetchDeals(topCategory !== null ? { top_category: topCategory } : {})
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Грешка при зареждане");
      })
      .finally(() => setLoading(false));
  }, [topCategory]);

  // Derive unique top categories from current full data for the filter dropdown.
  // We fetch without a category filter first so the dropdown is always populated.
  const [allData, setAllData] = useState<DealsResponse | null>(null);

  useEffect(() => {
    fetchDeals({})
      .then(setAllData)
      .catch(() => {
        // Non-fatal: filter dropdown will be empty
      });
  }, []);

  const topCategories: string[] = allData
    ? Array.from(
        new Set(
          allData.items
            .map((item: DealItem) => item.top_category)
            .filter((c): c is string => c !== null)
        )
      ).sort()
    : [];

  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Най-добри намаления</h1>
        <DealsSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Най-добри намаления</h1>
        <p className="text-destructive">{error}</p>
      </div>
    );
  }

  const items = data?.items ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Най-добри намаления</h1>

      {/* Filter bar */}
      <div className="flex items-center gap-3">
        <label
          htmlFor="top-category-filter"
          className="text-sm font-medium shrink-0"
        >
          Категория:
        </label>
        <select
          id="top-category-filter"
          value={topCategory ?? ""}
          onChange={(e) =>
            setTopCategory(e.target.value === "" ? null : e.target.value)
          }
          className="rounded-md border bg-background px-3 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          <option value="">Всички категории</option>
          {topCategories.map((cat) => (
            <option key={cat} value={cat}>
              {cat}
            </option>
          ))}
        </select>

        <span className="text-sm text-muted-foreground">
          {data?.total ?? 0} намаления
        </span>
      </div>

      {/* Empty state */}
      {items.length === 0 ? (
        <div
          role="status"
          aria-live="polite"
          className="flex flex-col items-center gap-3 py-16 text-center"
        >
          <p className="text-muted-foreground">Няма активни намаления</p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-3">
          {items.map((item, idx) => (
            <DealCard key={`${item.product_name}-${item.store}-${idx}`} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}
