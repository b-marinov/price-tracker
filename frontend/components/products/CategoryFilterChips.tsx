"use client";

import { useRef, useCallback } from "react";
import { cn } from "@/lib/utils";
import type { Category } from "@/types";

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
 * Flatten a nested category tree into a flat array.
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
 * Horizontally-scrollable row of pill/chip filter buttons built directly
 * from backend categories. On mobile the row scrolls horizontally; on
 * desktop it wraps.
 */
export function CategoryFilterChips({
  categories,
  selectedId,
  onSelect,
}: CategoryFilterChipsProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const flat = flattenCategories(categories);

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

        {flat.map((cat) => {
          const isActive = selectedId === cat.id;
          return (
            <button
              key={cat.id}
              type="button"
              role="listitem"
              onClick={() => handleSelect(isActive ? null : cat.id)}
              className={cn(
                "inline-flex shrink-0 items-center rounded-full border px-3 py-1.5 text-sm font-medium transition-colors",
                "focus:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                isActive
                  ? "border-transparent bg-primary text-primary-foreground"
                  : "border-input bg-background text-foreground hover:bg-accent hover:text-accent-foreground"
              )}
              aria-pressed={isActive}
              aria-label={`Категория ${cat.name}`}
            >
              {cat.name}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
