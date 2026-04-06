import Link from "next/link";
import { Search, TrendingDown, Store, BarChart2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

/**
 * Home page — hero section with search placeholder and feature highlights.
 *
 * The search bar is a placeholder for now; actual search functionality
 * will be wired to the catalogue API in a subsequent feature issue.
 */
export default function HomePage() {
  return (
    <div className="space-y-12">
      {/* ------------------------------------------------------------------ */}
      {/* Hero                                                                */}
      {/* ------------------------------------------------------------------ */}
      <section
        aria-labelledby="hero-heading"
        className="flex flex-col items-center gap-6 py-10 text-center md:py-16"
      >
        <Badge variant="secondary" className="text-sm">
          Kaufland · Lidl · Billa · Fantastico
        </Badge>

        <h1
          id="hero-heading"
          className="max-w-2xl text-3xl font-bold tracking-tight md:text-5xl"
        >
          Намерете най-ниската цена на всеки продукт
        </h1>

        <p className="max-w-xl text-muted-foreground md:text-lg">
          Сравняваме цени от водещите български хранителни вериги в реално
          време, за да можете да пазарувате по-умно.
        </p>

        {/* Search bar — routes to /products?q=… */}
        <form
          role="search"
          aria-label="Търсене на продукти"
          className="flex w-full max-w-md gap-2"
          action="/products"
          method="get"
        >
          <label htmlFor="search-input" className="sr-only">
            Търси продукт
          </label>
          <Input
            id="search-input"
            name="q"
            type="search"
            placeholder="Търси продукт…"
            className="flex-1"
            aria-label="Въведете продукт за търсене"
          />
          <Button type="submit" aria-label="Търси">
            <Search className="mr-2 h-4 w-4" aria-hidden="true" />
            Търси
          </Button>
        </form>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* Feature highlights                                                  */}
      {/* ------------------------------------------------------------------ */}
      <section aria-labelledby="features-heading">
        <h2 id="features-heading" className="sr-only">
          Функции
        </h2>

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center gap-3 space-y-0 pb-2">
              <TrendingDown
                className="h-5 w-5 text-primary"
                aria-hidden="true"
              />
              <CardTitle className="text-base">Сравнение на цени</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Вижте цената на един и същи продукт в различни магазини и
                изберете най-изгодната оферта.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center gap-3 space-y-0 pb-2">
              <BarChart2 className="h-5 w-5 text-primary" aria-hidden="true" />
              <CardTitle className="text-base">История на цените</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Проследете как се е променяла цената с времето и разберете дали
                промоцията е наистина изгодна.
              </p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center gap-3 space-y-0 pb-2">
              <Store className="h-5 w-5 text-primary" aria-hidden="true" />
              <CardTitle className="text-base">Всички магазини</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">
                Kaufland, Lidl, Billa и Fantastico — всичко на едно място,
                актуализирано ежедневно.
              </p>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* ------------------------------------------------------------------ */}
      {/* CTA                                                                 */}
      {/* ------------------------------------------------------------------ */}
      <section
        aria-labelledby="cta-heading"
        className="rounded-lg bg-muted p-6 text-center md:p-10"
      >
        <h2 id="cta-heading" className="mb-2 text-xl font-semibold md:text-2xl">
          Разгледайте каталога
        </h2>
        <p className="mb-6 text-muted-foreground">
          Над 10 000 продукта от 4 вериги — намерете точно това, което търсите.
        </p>
        <Button asChild size="lg">
          <Link href="/products">Към продуктите</Link>
        </Button>
      </section>
    </div>
  );
}
