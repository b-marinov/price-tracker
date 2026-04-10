"use client";

import { useState } from "react";
import Link from "next/link";
import { Search, GitCompareArrows, TrendingDown } from "lucide-react";

import { searchCompareProducts } from "@/lib/api";
import type { SearchCompareItem } from "@/types";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

function formatPrice(price: number, currency = "EUR") {
  return new Intl.NumberFormat("bg-BG", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(price);
}

export default function ComparePage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchCompareItem[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [searched, setSearched] = useState("");

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setSearched(q);
    try {
      const res = await searchCompareProducts(q);
      setResults(res.results);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <GitCompareArrows className="h-6 w-6" aria-hidden="true" />
          Сравни цени
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Търси продукт и виж най-ниската цена от всеки магазин
        </p>
      </div>

      {/* Search form */}
      <form
        role="search"
        aria-label="Сравни цени"
        className="flex gap-2"
        onSubmit={handleSearch}
      >
        <div className="relative flex-1">
          <Search
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden="true"
          />
          <Input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="напр. мляко, кафе, хляб…"
            className="pl-9"
            aria-label="Търсене за сравнение"
          />
        </div>
        <Button type="submit" disabled={loading || !query.trim()}>
          {loading ? "Търся…" : "Сравни"}
        </Button>
      </form>

      {/* Results */}
      {results !== null && (
        <div aria-live="polite">
          {results.length === 0 ? (
            <div className="flex flex-col items-center gap-3 py-16 text-center">
              <Search className="h-10 w-10 text-muted-foreground opacity-40" aria-hidden="true" />
              <p className="text-muted-foreground">
                Няма резултати за „{searched}"
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                {results.length} {results.length === 1 ? "продукт" : "продукта"} за „{searched}"
              </p>
              {results.map((item) => (
                <Card key={item.product_id}>
                  <CardContent className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{item.product_name}</span>
                        {item.brand && (
                          <span className="text-xs text-muted-foreground">{item.brand}</span>
                        )}
                      </div>
                      <div className="flex items-center gap-1.5 text-sm">
                        <TrendingDown className="h-3.5 w-3.5 text-green-600" aria-hidden="true" />
                        <span className="font-bold text-green-700 dark:text-green-400">
                          {formatPrice(item.cheapest_price, item.currency)}
                        </span>
                        <span className="text-muted-foreground">в {item.cheapest_store_name}</span>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        {item.store_count} {item.store_count === 1 ? "магазин" : "магазина"}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <Button asChild variant="outline" size="sm">
                        <Link href={`/products/${item.product_id}`}>
                          Детайли
                        </Link>
                      </Button>
                      {item.store_count > 1 && (
                        <Button asChild size="sm">
                          <Link href={`/products/${item.product_id}/compare`}>
                            <GitCompareArrows className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                            Сравни
                          </Link>
                        </Button>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Empty state before first search */}
      {results === null && !loading && (
        <div className="flex flex-col items-center gap-3 py-16 text-center text-muted-foreground">
          <GitCompareArrows className="h-12 w-12 opacity-20" aria-hidden="true" />
          <p className="text-sm">Въведи продукт, за да видиш цените от всички магазини</p>
          <div className="flex flex-wrap justify-center gap-2 text-xs">
            {["мляко", "кафе", "хляб", "олио", "яйца"].map((hint) => (
              <Badge
                key={hint}
                variant="secondary"
                className="cursor-pointer"
                onClick={() => { setQuery(hint); }}
              >
                {hint}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
