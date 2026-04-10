"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, Store as StoreIcon } from "lucide-react";

import { fetchBrowse } from "@/lib/api";
import type {
  BrandEntry,
  BrowseResponse,
  ProductTypeEntry,
  SubCategoryEntry,
  TopCategoryEntry,
} from "@/types";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatPrice(value: number): string {
  return value.toFixed(2);
}

function PriceRange({ min, max }: { min: number; max: number }) {
  return (
    <span className="text-sm text-muted-foreground">
      {formatPrice(min)} &ndash; {formatPrice(max)} &euro;
    </span>
  );
}

// ---------------------------------------------------------------------------
// Brand row
// ---------------------------------------------------------------------------

function BrandRow({ brand }: { brand: BrandEntry }) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2 text-sm">
      <span className="font-medium">
        {brand.brand ?? "Собствена марка"}
      </span>

      <PriceRange min={brand.price_min} max={brand.price_max} />

      {brand.cheapest_store && (
        <Badge variant="secondary" className="text-xs">
          <StoreIcon className="mr-1 h-3 w-3" aria-hidden="true" />
          {brand.cheapest_store}
        </Badge>
      )}

      {brand.max_discount != null && brand.max_discount > 0 && (
        <Badge variant="destructive" className="text-xs font-bold">
          -{brand.max_discount}%
        </Badge>
      )}

      <span className="ml-auto text-xs text-muted-foreground">
        {brand.store_count} {brand.store_count === 1 ? "магазин" : "магазина"}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Product type row (collapsible)
// ---------------------------------------------------------------------------

function ProductTypeRow({ pt }: { pt: ProductTypeEntry }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}

        <span className="font-medium">{pt.product_type}</span>

        <PriceRange min={pt.price_min} max={pt.price_max} />

        <span className="ml-auto text-xs text-muted-foreground">
          {pt.brand_count} {pt.brand_count === 1 ? "марка" : "марки"}
        </span>
      </button>

      {open && pt.brands.length > 0 && (
        <div className="ml-6 space-y-1">
          {pt.brands.map((b, idx) => (
            <BrandRow key={b.brand ?? `own-${idx}`} brand={b} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-category row (collapsible)
// ---------------------------------------------------------------------------

function SubCategoryRow({ sub }: { sub: SubCategoryEntry }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-1">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}

        <span className="font-medium">{sub.category}</span>

        <PriceRange min={sub.price_min} max={sub.price_max} />

        <span className="ml-auto text-xs text-muted-foreground">
          {sub.product_type_count} {sub.product_type_count === 1 ? "вид" : "вида"}
        </span>
      </button>

      {open && sub.product_types.length > 0 && (
        <div className="ml-4 space-y-1">
          {sub.product_types.map((pt) => (
            <ProductTypeRow key={pt.product_type} pt={pt} />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Top-category card (collapsible)
// ---------------------------------------------------------------------------

function TopCategoryCard({ cat }: { cat: TopCategoryEntry }) {
  const [open, setOpen] = useState(false);

  return (
    <Card className="overflow-hidden transition-shadow hover:shadow-md">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-3 px-4 py-4 text-left transition-colors hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
        ) : (
          <ChevronRight className="h-5 w-5 shrink-0 text-muted-foreground" aria-hidden="true" />
        )}

        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-bold leading-tight">{cat.top_category}</h2>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <PriceRange min={cat.price_min} max={cat.price_max} />
            <span className="text-xs text-muted-foreground">
              {cat.sub_category_count} подкатегории
            </span>
          </div>
        </div>
      </button>

      {open && cat.sub_categories.length > 0 && (
        <CardContent className="space-y-1 border-t px-4 pb-4 pt-3">
          {cat.sub_categories.map((sub) => (
            <SubCategoryRow key={sub.category} sub={sub} />
          ))}
        </CardContent>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Skeleton loader
// ---------------------------------------------------------------------------

function BrowseSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <Card key={i} className="px-4 py-4">
          <Skeleton className="mb-2 h-5 w-3/4" />
          <Skeleton className="h-4 w-1/2" />
        </Card>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * Client-side browse page that fetches the category hierarchy and renders
 * expandable top-category cards with nested sub-categories, product types,
 * and brands.
 */
export function BrowsePage() {
  const [data, setData] = useState<BrowseResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchBrowse()
      .then(setData)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Грешка при зареждане");
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Разгледай по категория</h1>
        <BrowseSkeleton />
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Разгледай по категория</h1>
        <p className="text-destructive">{error}</p>
      </div>
    );
  }

  const categories = data?.top_categories ?? [];

  if (categories.length === 0) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Разгледай по категория</h1>
        <div
          role="status"
          aria-live="polite"
          className="flex flex-col items-center gap-3 py-16 text-center"
        >
          <p className="text-muted-foreground">
            Няма данни &mdash; стартирайте скрейпъра от администрацията
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Разгледай по категория</h1>
      <p className="text-sm text-muted-foreground">
        {categories.length} {categories.length === 1 ? "категория" : "категории"}
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        {categories.map((cat) => (
          <TopCategoryCard key={cat.top_category} cat={cat} />
        ))}
      </div>
    </div>
  );
}
