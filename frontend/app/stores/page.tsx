import Link from "next/link";
import Image from "next/image";
import { BookOpen, ExternalLink, Store, CalendarDays } from "lucide-react";

import { listStores, listActiveBrochures } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Brochure, Store as StoreType } from "@/types";

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("bg-BG", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

function BrochureBadge({ brochure }: { brochure: Brochure }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="secondary" className="gap-1">
        <BookOpen className="h-3 w-3" aria-hidden="true" />
        Брошура
      </Badge>
      {brochure.valid_from && brochure.valid_to && (
        <span className="text-xs text-muted-foreground">
          {formatDate(brochure.valid_from)} – {formatDate(brochure.valid_to)}
        </span>
      )}
    </div>
  );
}

export default async function StoresPage() {
  const [stores, brochures] = await Promise.all([
    listStores().catch(() => [] as StoreType[]),
    listActiveBrochures().catch(() => [] as Brochure[]),
  ]);

  const brochureByStore = new Map<string, Brochure>(
    brochures.map((b) => [b.store_id, b])
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Магазини и брошури</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Текущи промоционални брошури от всеки магазин
        </p>
      </div>

      {stores.length === 0 ? (
        <div className="rounded-lg border border-dashed p-12 text-center">
          <Store className="mx-auto mb-3 h-10 w-10 text-muted-foreground/40" aria-hidden="true" />
          <p className="text-sm text-muted-foreground">Няма добавени магазини</p>
        </div>
      ) : (
        <ul
          className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
          aria-label="Списък с магазини"
        >
          {stores.map((store) => {
            const brochure = brochureByStore.get(store.id);

            return (
              <li key={store.id}>
                <Card className="flex h-full flex-col">
                  <CardHeader className="flex flex-row items-center gap-3 space-y-0 pb-3">
                    {store.logo_url ? (
                      <div className="relative h-10 w-10 shrink-0 overflow-hidden rounded border bg-muted">
                        <Image
                          src={store.logo_url}
                          alt={`${store.name} лого`}
                          fill
                          sizes="40px"
                          className="object-contain p-1"
                        />
                      </div>
                    ) : (
                      <div
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded border bg-muted"
                        aria-hidden="true"
                      >
                        <Store className="h-5 w-5 text-muted-foreground/50" />
                      </div>
                    )}
                    <div className="min-w-0 flex-1">
                      <CardTitle className="truncate text-base">{store.name}</CardTitle>
                      {store.website_url && (
                        <a
                          href={store.website_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
                          aria-label={`Уебсайт на ${store.name} (отваря в нов прозорец)`}
                        >
                          {store.website_url.replace(/^https?:\/\//, "").replace(/\/$/, "")}
                          <ExternalLink className="h-3 w-3" aria-hidden="true" />
                        </a>
                      )}
                    </div>
                  </CardHeader>

                  <CardContent className="flex flex-1 flex-col gap-3">
                    {brochure ? (
                      <>
                        <BrochureBadge brochure={brochure} />
                        <p className="line-clamp-2 text-sm text-foreground/80">
                          {brochure.title}
                        </p>
                        <Button asChild className="mt-auto w-full" size="sm">
                          <Link href={`/stores/${store.id}/brochure`}>
                            <BookOpen className="mr-2 h-4 w-4" aria-hidden="true" />
                            Виж брошурата
                          </Link>
                        </Button>
                      </>
                    ) : (
                      <div className="flex flex-1 items-center">
                        <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                          <CalendarDays className="h-4 w-4 shrink-0" aria-hidden="true" />
                          Няма активна брошура
                        </p>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
