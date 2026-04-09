import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, BookOpen, CalendarDays, Search } from "lucide-react";

import { getCurrentBrochure, listStoreBrochures } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BrochurePdfViewer } from "@/components/brochure/BrochurePdfViewer";
import type { Brochure } from "@/types";

interface Props {
  params: { id: string };
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("bg-BG", {
    day: "2-digit",
    month: "long",
    year: "numeric",
  });
}

function ValidityBadge({ brochure }: { brochure: Brochure }) {
  if (!brochure.valid_from || !brochure.valid_to) return null;
  return (
    <Badge variant="secondary" className="gap-1 text-xs">
      <CalendarDays className="h-3 w-3" aria-hidden="true" />
      {formatDate(brochure.valid_from)} – {formatDate(brochure.valid_to)}
    </Badge>
  );
}

export default async function BrochureViewerPage({ params }: Props) {
  const [current, allBrochures] = await Promise.all([
    getCurrentBrochure(params.id).catch(() => null),
    listStoreBrochures(params.id).catch(() => [] as Brochure[]),
  ]);

  if (!current) notFound();

  const pastBrochures = allBrochures.filter((b) => !b.is_current);

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href="/stores"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        aria-label="Обратно към магазините"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Магазини
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <h1 className="flex items-center gap-2 text-2xl font-bold">
            <BookOpen className="h-6 w-6 shrink-0" aria-hidden="true" />
            {current.store_name}
          </h1>
          <p className="text-sm text-muted-foreground">{current.title}</p>
          <ValidityBadge brochure={current} />
        </div>

        {/* Search products from this store */}
        <Button asChild variant="outline" size="sm">
          <Link href={`/products?q=${encodeURIComponent(current.store_slug)}`}>
            <Search className="mr-2 h-4 w-4" aria-hidden="true" />
            Търси продукти от {current.store_name}
          </Link>
        </Button>
      </div>

      {/* PDF viewer */}
      <BrochurePdfViewer
        pdfUrl={current.pdf_url}
        title={current.title}
        storeName={current.store_name}
      />

      {/* Past brochures */}
      {pastBrochures.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-base">Предишни брошури</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="divide-y text-sm" aria-label="Предишни брошури">
              {pastBrochures.map((b) => (
                <li key={b.id} className="flex items-center justify-between py-2">
                  <span className="text-foreground/80">{b.title}</span>
                  {b.valid_from && b.valid_to && (
                    <span className="ml-4 shrink-0 text-xs text-muted-foreground">
                      {formatDate(b.valid_from)} – {formatDate(b.valid_to)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
