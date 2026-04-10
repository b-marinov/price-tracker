"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, SlidersHorizontal, X } from "lucide-react";

import { listProducts, listCategories, listCategoryProducts, searchProducts } from "@/lib/api";
import type { Category, ProductListItem } from "@/types";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ProductCard } from "@/components/products/ProductCard";
import { ProductGridSkeleton } from "@/components/products/ProductCardSkeleton";
import { CategorySidebar } from "@/components/products/CategorySidebar";
import { CategoryFilterChips } from "@/components/products/CategoryFilterChips";

const PAGE_SIZE = 20;

export default function ProductsPage() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const initialQ = searchParams.get("q") ?? "";
  const initialCategory = searchParams.get("category_id") ?? null;

  const [query, setQuery] = useState(initialQ);
  const [debouncedQuery, setDebouncedQuery] = useState(initialQ);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(initialCategory);
  const [products, setProducts] = useState<ProductListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [categories, setCategories] = useState<Category[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Debounce search query by 350ms
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleQueryChange = useCallback((value: string) => {
    setQuery(value);
    setOffset(0);
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    debounceTimer.current = setTimeout(() => {
      setDebouncedQuery(value);
    }, 350);
  }, []);

  // Load categories once
  useEffect(() => {
    listCategories().then(setCategories).catch(() => setCategories([]));
  }, []);

  // Update URL params when filters change
  useEffect(() => {
    const params = new URLSearchParams();
    if (debouncedQuery) params.set("q", debouncedQuery);
    if (selectedCategory) params.set("category_id", selectedCategory);
    router.replace(`/products${params.toString() ? `?${params.toString()}` : ""}`, { scroll: false });
  }, [debouncedQuery, selectedCategory, router]);

  // Fetch products when filters / offset change
  useEffect(() => {
    setLoading(true);
    const req = debouncedQuery.trim()
      ? searchProducts({ q: debouncedQuery.trim(), limit: PAGE_SIZE, offset })
      : selectedCategory
        ? listCategoryProducts(selectedCategory, { limit: PAGE_SIZE, offset })
        : listProducts({ limit: PAGE_SIZE, offset });

    req
      .then((res) => {
        setProducts(res.items);
        setTotal(res.total);
      })
      .catch(() => {
        setProducts([]);
        setTotal(0);
      })
      .finally(() => setLoading(false));
  }, [debouncedQuery, selectedCategory, offset]);

  // Reset offset when filters change
  const handleCategorySelect = useCallback((id: string | null) => {
    setSelectedCategory(id);
    setOffset(0);
  }, []);

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1;

  return (
    <div className="space-y-4">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold">Продукти</h1>
        {total > 0 && !loading && (
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {total} {total === 1 ? "продукт" : "продукта"}
            {debouncedQuery && ` за „${debouncedQuery}"`}
          </p>
        )}
      </div>

      {/* Search bar */}
      <form
        role="search"
        aria-label="Търсене на продукти"
        className="flex gap-2"
        onSubmit={(e) => e.preventDefault()}
      >
        <div className="relative flex-1">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={query}
            onChange={(e) => handleQueryChange(e.target.value)}
            placeholder="Търси продукт…"
            className="pl-9 pr-9"
            aria-label="Търсене на продукти"
          />
          {query && (
            <button
              type="button"
              onClick={() => { setQuery(""); setDebouncedQuery(""); setOffset(0); }}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              aria-label="Изчисти търсенето"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </div>

        {/* Mobile: toggle category sidebar */}
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => setSidebarOpen((v) => !v)}
          className="md:hidden"
          aria-expanded={sidebarOpen}
          aria-controls="category-sidebar"
          aria-label="Филтрирай по категория"
        >
          <SlidersHorizontal className="h-4 w-4" aria-hidden="true" />
        </Button>
      </form>

      {/* Category filter chips — horizontal scrollable row */}
      <CategoryFilterChips
        categories={categories}
        selectedId={selectedCategory}
        onSelect={handleCategorySelect}
      />

      <div className="flex gap-6">
        {/* Category sidebar — always visible on md+, toggled on mobile */}
        <aside
          id="category-sidebar"
          className={`
            w-52 flex-shrink-0
            ${sidebarOpen ? "block" : "hidden"} md:block
          `}
          aria-label="Филтриране по категория"
        >
          <CategorySidebar
            categories={categories}
            selectedId={selectedCategory}
            onSelect={handleCategorySelect}
          />
        </aside>

        {/* Product grid */}
        <main className="min-w-0 flex-1 space-y-4">
          {loading ? (
            <ProductGridSkeleton count={PAGE_SIZE} />
          ) : products.length === 0 ? (
            <div
              role="status"
              aria-live="polite"
              className="flex flex-col items-center gap-3 py-16 text-center"
            >
              <Search className="h-10 w-10 text-muted-foreground opacity-40" aria-hidden="true" />
              <p className="text-muted-foreground">
                {debouncedQuery
                  ? `Няма резултати за „${debouncedQuery}"`
                  : "Няма намерени продукти"}
              </p>
              {(debouncedQuery || selectedCategory) && (
                <Button
                  variant="outline"
                  onClick={() => { setQuery(""); setDebouncedQuery(""); setSelectedCategory(null); setOffset(0); }}
                >
                  Изчисти филтрите
                </Button>
              )}
            </div>
          ) : (
            <>
              <div
                className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4"
                aria-label="Списък с продукти"
              >
                {products.map((p) => (
                  <ProductCard key={p.id} product={p} />
                ))}
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <nav
                  aria-label="Навигация между страниците"
                  className="flex items-center justify-center gap-2"
                >
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                    disabled={currentPage === 1}
                    aria-label="Предишна страница"
                  >
                    ←
                  </Button>
                  <span className="text-sm text-muted-foreground" aria-current="page">
                    {currentPage} / {totalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setOffset(offset + PAGE_SIZE)}
                    disabled={currentPage === totalPages}
                    aria-label="Следваща страница"
                  >
                    →
                  </Button>
                </nav>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
