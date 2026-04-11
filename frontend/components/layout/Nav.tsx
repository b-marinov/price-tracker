"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Home, Search, Store, LayoutGrid, Percent, Settings } from "lucide-react";

import { cn } from "@/lib/utils";

/** Navigation item definition. */
interface NavItem {
  /** Route path. */
  href: string;
  /** Display label (Bulgarian). */
  label: string;
  /** Lucide icon component. */
  icon: React.ElementType;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "Начало", icon: Home },
  { href: "/products", label: "Продукти", icon: Search },
  { href: "/stores", label: "Магазини", icon: Store },
  { href: "/browse", label: "Разгледай", icon: LayoutGrid },
  { href: "/deals", label: "Намаления", icon: Percent },
  { href: "/admin", label: "Админ", icon: Settings },
];

/** Props for the {@link Nav} component. */
export interface NavProps {
  /**
   * Render mode:
   * - `"sidebar"` — vertical left-hand sidebar, visible on desktop (≥ md).
   * - `"bottom"`  — fixed bottom bar, visible on mobile (< md).
   */
  variant: "sidebar" | "bottom";
}

/**
 * Responsive navigation component.
 *
 * Renders either a desktop sidebar or a mobile bottom navigation bar
 * depending on the `variant` prop. Both variants share the same nav items
 * and active-state logic.
 *
 * Accessibility: uses `<nav>` with a unique `aria-label`, and marks the
 * current page link with `aria-current="page"`.
 */
export function Nav({ variant }: NavProps) {
  const pathname = usePathname();

  if (variant === "sidebar") {
    return (
      <nav
        aria-label="Странично меню"
        className="hidden w-56 shrink-0 border-r bg-background md:block"
      >
        <ul className="flex flex-col gap-1 px-3 py-4" role="list">
          {NAV_ITEMS.map((item) => {
            const isActive =
              item.href === "/"
                ? pathname === "/"
                : pathname.startsWith(item.href);
            const Icon = item.icon;

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    "hover:bg-accent hover:text-accent-foreground",
                    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-foreground/70"
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
                  {item.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    );
  }

  // Bottom navigation (mobile)
  return (
    <nav
      aria-label="Долно меню"
      className="fixed inset-x-0 bottom-0 z-40 border-t bg-background md:hidden"
    >
      <ul
        className="flex items-stretch justify-around"
        role="list"
      >
        {NAV_ITEMS.slice(0, 4).map((item) => {
          // Show only 4 items in the bottom bar to avoid crowding
          const isActive =
            item.href === "/"
              ? pathname === "/"
              : pathname.startsWith(item.href);
          const Icon = item.icon;

          return (
            <li key={item.href} className="flex-1">
              <Link
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex flex-col items-center gap-1 py-2 text-xs font-medium transition-colors",
                  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
                  isActive ? "text-primary" : "text-foreground/60"
                )}
              >
                <Icon className="h-5 w-5" aria-hidden="true" />
                <span>{item.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
