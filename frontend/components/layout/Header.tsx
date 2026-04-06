import Link from "next/link";
import { ShoppingCart } from "lucide-react";

/**
 * Site-wide header.
 *
 * Contains the logo / site name ("Ценово сравнение") and a skip-nav target.
 * The header is `sticky` so it remains visible when scrolling on all devices.
 */
export function Header() {
  return (
    <header className="sticky top-0 z-40 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center gap-4 md:h-16">
        {/* Logo / site name */}
        <Link
          href="/"
          className="flex items-center gap-2 font-bold text-primary focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring"
          aria-label="Ценово сравнение — начало"
        >
          <ShoppingCart className="h-5 w-5" aria-hidden="true" />
          <span className="text-lg">Ценово сравнение</span>
        </Link>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Top-level nav links — desktop only (mobile uses bottom-nav) */}
        <nav
          aria-label="Главно меню"
          className="hidden items-center gap-6 text-sm font-medium md:flex"
        >
          <Link
            href="/products"
            className="text-foreground/70 transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Продукти
          </Link>
          <Link
            href="/compare"
            className="text-foreground/70 transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Сравни
          </Link>
          <Link
            href="/stores"
            className="text-foreground/70 transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            Магазини
          </Link>
        </nav>
      </div>
    </header>
  );
}
