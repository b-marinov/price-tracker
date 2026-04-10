"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Tag, ChevronRight, Package } from "lucide-react";

import { listCategories } from "@/lib/api";
import { Card, CardContent } from "@/components/ui/card";
import type { Category } from "@/types";

function flattenCategories(categories: Category[], depth = 0): Array<{ cat: Category; depth: number }> {
  const result: Array<{ cat: Category; depth: number }> = [];
  for (const cat of categories) {
    result.push({ cat, depth });
    if (cat.children?.length) {
      result.push(...flattenCategories(cat.children, depth + 1));
    }
  }
  return result;
}

export default function CategoriesPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listCategories()
      .catch(() => [] as Category[])
      .then((cats) => {
        setCategories(cats);
        setLoading(false);
      });
  }, []);

  const flat = flattenCategories(categories);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold">
          <Tag className="h-6 w-6" aria-hidden="true" />
          Категории
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {loading
            ? "Зарежда се…"
            : flat.length > 0
              ? `${flat.length} ${flat.length === 1 ? "категория" : "категории"}`
              : "Все още няма категории"}
        </p>
      </div>

      {loading ? (
        <div className="space-y-1">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-lg bg-muted" />
          ))}
        </div>
      ) : flat.length === 0 ? (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <Package className="h-10 w-10 text-muted-foreground opacity-40" aria-hidden="true" />
          <p className="text-sm text-muted-foreground">Категориите ще се появят след първото сканиране на магазините.</p>
        </div>
      ) : (
        <ul className="space-y-1" aria-label="Списък с категории">
          {flat.map(({ cat, depth }) => (
            <li key={cat.id}>
              <Card className="hover:bg-accent/50 transition-colors">
                <CardContent className="p-0">
                  <Link
                    href={`/products?category_id=${cat.id}`}
                    className="flex items-center gap-3 px-4 py-3 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring rounded-lg"
                    aria-label={`Виж продукти в категория ${cat.name}`}
                  >
                    <span
                      className="shrink-0 text-muted-foreground"
                      style={{ marginLeft: `${depth * 16}px` }}
                      aria-hidden="true"
                    >
                      {depth === 0
                        ? <Tag className="h-4 w-4" />
                        : <ChevronRight className="h-4 w-4" />}
                    </span>
                    <span className={depth === 0 ? "font-medium" : "text-sm text-foreground/80"}>
                      {cat.name}
                    </span>
                  </Link>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
