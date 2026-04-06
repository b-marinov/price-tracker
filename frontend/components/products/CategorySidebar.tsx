"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Tag } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import type { Category } from "@/types";

interface CategorySidebarProps {
  categories: Category[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
}

interface CategoryNodeProps {
  category: Category;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  depth?: number;
}

function CategoryNode({
  category,
  selectedId,
  onSelect,
  depth = 0,
}: CategoryNodeProps) {
  const hasChildren = (category.children?.length ?? 0) > 0;
  const [expanded, setExpanded] = useState(false);
  const isSelected = selectedId === category.id;

  return (
    <li>
      <div className="flex items-center gap-1">
        {hasChildren ? (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="flex-shrink-0 p-1 text-muted-foreground hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-primary"
            aria-label={expanded ? "Скрий подкатегории" : "Покажи подкатегории"}
          >
            {expanded ? (
              <ChevronDown className="h-3 w-3" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-3 w-3" aria-hidden="true" />
            )}
          </button>
        ) : (
          <span className="w-5 flex-shrink-0" aria-hidden="true" />
        )}

        <button
          type="button"
          onClick={() => onSelect(isSelected ? null : category.id)}
          className={cn(
            "flex-1 truncate rounded px-2 py-1 text-left text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-primary",
            isSelected
              ? "bg-primary text-primary-foreground font-medium"
              : "hover:bg-accent hover:text-accent-foreground text-foreground"
          )}
          aria-pressed={isSelected}
          aria-label={`Категория ${category.name}`}
          style={{ paddingLeft: `${depth * 8 + 8}px` }}
        >
          {category.name}
        </button>
      </div>

      {hasChildren && expanded && (
        <ul className="mt-0.5 space-y-0.5" role="list">
          {category.children!.map((child) => (
            <CategoryNode
              key={child.id}
              category={child}
              selectedId={selectedId}
              onSelect={onSelect}
              depth={depth + 1}
            />
          ))}
        </ul>
      )}
    </li>
  );
}

export function CategorySidebar({
  categories,
  selectedId,
  onSelect,
}: CategorySidebarProps) {
  return (
    <nav aria-label="Категории" className="w-full">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Tag className="h-4 w-4" aria-hidden="true" />
          Категории
        </h2>
        {selectedId && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onSelect(null)}
            className="h-6 px-2 text-xs text-muted-foreground"
          >
            Изчисти
          </Button>
        )}
      </div>

      {categories.length === 0 ? (
        <p className="text-xs text-muted-foreground">Няма категории</p>
      ) : (
        <ul className="space-y-0.5" role="list">
          {categories.map((cat) => (
            <CategoryNode
              key={cat.id}
              category={cat}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ))}
        </ul>
      )}
    </nav>
  );
}
