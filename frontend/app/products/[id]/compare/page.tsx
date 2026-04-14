import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, TrendingDown } from "lucide-react";

import { compareProductPrices } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { ShareButton } from "@/components/comparison/ShareButton";

interface Props {
  params: { id: string };
}

function formatPrice(price: number, currency = "EUR") {
  const safeCurrency = /^[A-Z]{3}$/.test(currency ?? "") ? currency : "EUR";
  return new Intl.NumberFormat("bg-BG", {
    style: "currency",
    currency: safeCurrency,
    minimumFractionDigits: 2,
  }).format(price);
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("bg-BG", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export default async function ComparePage({ params }: Props) {
  const comparison = await compareProductPrices(params.id).catch(() => null);
  if (!comparison) notFound();

  const { comparisons } = comparison;

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href={`/products/${params.id}`}
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        aria-label={`Обратно към ${comparison.product_name}`}
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        {comparison.product_name}
      </Link>

      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">{comparison.product_name}</h1>
          <p className="text-sm text-muted-foreground">
            Сравнение на цени в {comparisons.length}{" "}
            {comparisons.length === 1 ? "магазин" : "магазина"}
          </p>
        </div>
        <ShareButton />
      </div>

      {comparisons.length === 0 ? (
        <p className="text-muted-foreground" role="status">
          Няма налични цени за сравнение.
        </p>
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden overflow-hidden rounded-lg border sm:block">
            <table
              className="w-full text-sm"
              aria-label={`Сравнение на цени за ${comparison.product_name}`}
            >
              <thead className="bg-muted/50">
                <tr>
                  <th scope="col" className="px-4 py-3 text-left font-medium">Магазин</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">Цена</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">Разлика</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">Обновено</th>
                </tr>
              </thead>
              <tbody className="divide-y bg-background">
                {comparisons.map((row, i) => (
                  <tr
                    key={row.store_id}
                    className={i === 0 ? "bg-green-50 dark:bg-green-950/20" : "hover:bg-muted/30"}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{row.store_name}</span>
                        {i === 0 && (
                          <Badge className="bg-green-600 text-xs text-white hover:bg-green-700">
                            <TrendingDown className="mr-1 h-3 w-3" aria-hidden="true" />
                            Най-евтин
                          </Badge>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <span className={i === 0 ? "font-bold text-green-700 dark:text-green-400" : "font-semibold"}>
                        {formatPrice(row.price, row.currency)}
                      </span>
                      {row.unit && (
                        <span className="ml-1 text-xs text-muted-foreground">/ {row.unit}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {i === 0 ? (
                        <span className="text-green-600 dark:text-green-400 text-xs font-medium">—</span>
                      ) : (
                        <span className="text-red-500 text-xs font-medium">
                          +{row.price_diff_pct.toFixed(1)}%
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-muted-foreground">
                      {formatDate(row.last_scraped_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="space-y-3 sm:hidden" aria-label="Сравнение по магазини">
            {comparisons.map((row, i) => (
              <Card
                key={row.store_id}
                className={i === 0 ? "border-green-400 dark:border-green-700" : ""}
              >
                <CardContent className="flex items-center justify-between p-4">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold">{row.store_name}</span>
                      {i === 0 && (
                        <Badge className="bg-green-600 text-xs text-white hover:bg-green-700">
                          <TrendingDown className="mr-1 h-3 w-3" aria-hidden="true" />
                          Най-евтин
                        </Badge>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">
                      {formatDate(row.last_scraped_at)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className={`text-lg font-bold ${i === 0 ? "text-green-700 dark:text-green-400" : ""}`}>
                      {formatPrice(row.price, row.currency)}
                      {row.unit && (
                        <span className="ml-1 text-xs font-normal text-muted-foreground">/ {row.unit}</span>
                      )}
                    </p>
                    {i > 0 && (
                      <p className="text-xs text-red-500 font-medium">
                        +{row.price_diff_pct.toFixed(1)}%
                      </p>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
