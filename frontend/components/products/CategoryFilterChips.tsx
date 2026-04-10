"use client";

import { useRef, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { Category } from "@/types";

/**
 * Fixed taxonomy of product categories used as filter chips.
 * These are displayed even if no backend categories are loaded,
 * providing a consistent UX.
 */
const CATEGORY_TAXONOMY = [
  "Плодове",
  "Зеленчуци",
  "Месо",
  "Птиче месо",
  "Риба и морски дарове",
  "Колбаси и деликатеси",
  "Сирена",
  "Мляко и кисело мляко",
  "Яйца",
  "Масло и маргарин",
  "Олио",
  "Хляб и тестени",
  "Ориз бобови и зърнени",
  "Консерви и буркани",
  "Сосове и подправки",
  "Кафе",
  "Чай",
  "Вода",
  "Сокове",
  "Газирани напитки",
  "Алкохол",
  "Шоколад и сладкиши",
  "Бисквити и снаксове",
  "Замразени храни",
  "Почистващи препарати",
  "Козметика и хигиена",
  "Цветя и растения",
  "Домакински стоки",
  "Друго",
] as const;

/** Props for the {@link CategoryFilterChips} component. */
interface CategoryFilterChipsProps {
  /** Backend categories with id/name mappings. */
  categories: Category[];
  /** Currently selected category ID, or `null` for "All". */
  selectedId: string | null;
  /** Called when the user selects a category (or `null` for "All"). */
  onSelect: (id: string | null) => void;
}

/**
 * Flatten a nested category tree into a flat array for lookup.
 */
function flattenCategories(cats: Category[]): Category[] {
  const result: Category[] = [];
  for (const cat of cats) {
    result.push(cat);
    if (cat.children?.length) {
      result.push(...flattenCategories(cat.children));
    }
  }
  return result;
}

/**
 * Horizontally-scrollable row of pill/chip filter buttons for product
 * categories. Renders the fixed taxonomy list, mapping each name to its
 * backend category ID when available. On mobile the row scrolls
 * horizontally; on desktop it wraps.
 */
export function CategoryFilterChips({
  categories,
  selectedId,
  onSelect,
}: CategoryFilterChipsProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  // Build a name -> id lookup from the (possibly nested) backend categories
  const flat = flattenCategories(categories);
  const nameToId = new Map<string, string>();
  for (const cat of flat) {
    nameToId.set(cat.name, cat.id);
  }

  const handleSelect = useCallback(
    (id: string | null) => {
      onSelect(id);
    },
    [onSelect]
  );

  return (
    <nav
      aria-label="Филтриране по категория"
      className="w-full"
    >
      <div
        ref={scrollRef}
        className="flex gap-2 overflow-x-auto pb-2 scrollbar-thin md:flex-wrap md:overflow-x-visible"
        role="list"
      >
        {/* "All" chip */}
        <button
          type="button"
          role="listitem"
          onClick={() => handleSelect(null)}
          className={cn(
            "inline-flex shrink-0 items-center rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
            "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
            selectedId === null
              ? "border-transparent bg-primary text-primary-foreground"
              : "border-input bg-background text-foreground hover:bg-accent hover:text-accent-foreground"
          )}
          aria-pressed={selectedId === null}
          aria-label="Всички категории"
        >
          Всички
        </button>

        {CATEGORY_TAXONOMY.map((name) => {
          const id = nameToId.get(name) ?? null;
          const isActive = id != null && selectedId === id;

          return (
            <button
              key={name}
              type="button"
              role="listitem"
              onClick={() => handleSelect(isActive ? null : id)}
              disabled={id == null}
              className={cn(
                "inline-flex shrink-0 items-center rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                id == null
                  ? "cursor-not-allowed border-input bg-muted/50 text-muted-foreground opacity-50"
                  : isActive
                    ? "border-transparent bg-primary text-primary-foreground"
                    : "border-input bg-background text-foreground hover:bg-accent hover:text-accent-foreground"
              )}
              aria-pressed={isActive}
              aria-label={`Категория ${name}`}
            >
              {name}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
