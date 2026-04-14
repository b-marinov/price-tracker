import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, BarChart2, Store, GitCompareArrows } from "lucide-react";

import { getProduct, getProductPrices } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PriceHistoryChart } from "@/components/history/PriceHistoryChart";
import { ProductDetailImage } from "@/components/products/ProductDetailImage";

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

export default async function ProductDetailPage({ params }: Props) {
  const [product, history] = await Promise.all([
    getProduct(params.id).catch(() => null),
    getProductPrices(params.id, { interval: "daily" }).catch(() => null),
  ]);

  if (!product) notFound();

  const sortedPrices = [...(product.prices ?? [])].sort(
    (a, b) => a.price - b.price
  );
  const cheapestPrice = sortedPrices[0]?.price ?? null;

  return (
    <div className="space-y-6">
      {/* Back link */}
      <Link
        href="/products"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        aria-label="Обратно към продуктите"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Продукти
      </Link>

      {/* Product header */}
      <div className="flex flex-col gap-6 sm:flex-row">
        {/* Image */}
        <div className="w-full max-w-[240px] self-start">
          <ProductDetailImage
            imageUrl={product.image_url}
            productName={product.name}
          />
        </div>

        {/* Info */}
        <div className="flex-1 space-y-3">
          {product.brand && (
            <p className="text-sm text-muted-foreground">{product.brand}</p>
          )}
          <h1 className="text-2xl font-bold leading-tight">
            {product.name}
            {product.pack_info && (
              <span className="ml-2 text-base font-normal text-muted-foreground">{product.pack_info}</span>
            )}
          </h1>

          {product.additional_info && (
            <p className="text-sm text-muted-foreground">{product.additional_info}</p>
          )}

          {product.barcode && (
            <p className="text-xs text-muted-foreground">
              EAN: {product.barcode}
            </p>
          )}

          {cheapestPrice != null && (
            <div>
              <p className="text-xs text-muted-foreground">Най-ниска цена</p>
              <p className="text-3xl font-bold text-primary">
                {formatPrice(cheapestPrice, sortedPrices[0]?.currency)}
              </p>
              <p className="text-sm text-muted-foreground">
                от {sortedPrices.length}{" "}
                {sortedPrices.length === 1 ? "магазин" : "магазина"}
              </p>
            </div>
          )}

          {sortedPrices.length > 1 && (
            <Button asChild>
              <Link href={`/products/${product.id}/compare`}>
                <GitCompareArrows className="mr-2 h-4 w-4" aria-hidden="true" />
                Сравни цените
              </Link>
            </Button>
          )}
        </div>
      </div>

      {/* Current prices table */}
      {sortedPrices.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Store className="h-4 w-4" aria-hidden="true" />
              Текущи цени по магазини
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label="Цени по магазини">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th scope="col" className="pb-2 text-left font-medium">Магазин</th>
                    <th scope="col" className="pb-2 text-right font-medium">Цена</th>
                    <th scope="col" className="pb-2 text-right font-medium hidden sm:table-cell">Обновено</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {sortedPrices.map((p, i) => (
                    <tr key={p.store_id} className="hover:bg-muted/50">
                      <td className="py-2 pr-4">
                        <span className="font-medium">{p.store_name}</span>
                        {i === 0 && (
                          <Badge variant="secondary" className="ml-2 text-xs">
                            Най-евтин
                          </Badge>
                        )}
                      </td>
                      <td className="py-2 text-right font-semibold">
                        {formatPrice(p.price, p.currency)}
                        {p.unit && (
                          <span className="ml-1 text-xs font-normal text-muted-foreground">/ {p.unit}</span>
                        )}
                      </td>
                      <td className="py-2 text-right text-muted-foreground hidden sm:table-cell">
                        {formatDate(p.recorded_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Price history chart */}
      {history && history.store_results.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <BarChart2 className="h-4 w-4" aria-hidden="true" />
              История на цените
            </CardTitle>
          </CardHeader>
          <CardContent>
            <PriceHistoryChart
              storeResults={history.store_results}
              productName={product.name}
            />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
