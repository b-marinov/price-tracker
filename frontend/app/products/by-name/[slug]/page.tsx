import { notFound } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, Package, Store, Tag } from "lucide-react";

import { getProductFamily } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProductDetailImage } from "@/components/products/ProductDetailImage";

interface Props {
  params: { slug: string };
}

function formatPrice(price: number | null | undefined, currency = "EUR") {
  if (price == null) return "—";
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

export default async function ProductFamilyDetailPage({ params }: Props) {
  const family = await getProductFamily(params.slug).catch(() => null);
  if (!family) notFound();

  const variants = [...family.variants].sort((a, b) => a.price - b.price);

  return (
    <div className="space-y-6">
      <Link
        href="/products"
        className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        aria-label="Обратно към продуктите"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden="true" />
        Продукти
      </Link>

      <div className="flex flex-col gap-6 sm:flex-row">
        <div className="w-full max-w-[240px] self-start">
          <ProductDetailImage
            imageUrl={family.image_url}
            productName={family.name}
          />
        </div>

        <div className="flex-1 space-y-3">
          {family.category_name && (
            <p className="text-sm text-muted-foreground">{family.category_name}</p>
          )}
          <h1 className="text-2xl font-bold leading-tight">{family.name}</h1>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            {family.brand_count > 0 && (
              <span className="inline-flex items-center gap-1">
                <Tag className="h-3.5 w-3.5" aria-hidden="true" />
                {family.brand_count} {family.brand_count === 1 ? "марка" : "марки"}
              </span>
            )}
            {family.pack_count > 0 && (
              <span className="inline-flex items-center gap-1">
                <Package className="h-3.5 w-3.5" aria-hidden="true" />
                {family.pack_count} {family.pack_count === 1 ? "разфасовка" : "разфасовки"}
              </span>
            )}
            {family.store_count > 0 && (
              <span className="inline-flex items-center gap-1">
                <Store className="h-3.5 w-3.5" aria-hidden="true" />
                {family.store_count} {family.store_count === 1 ? "магазин" : "магазина"}
              </span>
            )}
          </div>

          {family.lowest_price != null && (
            <div>
              <p className="text-xs text-muted-foreground">Най-ниска цена</p>
              <p className="text-3xl font-bold text-primary">
                {formatPrice(family.lowest_price)}
              </p>
              {family.lowest_price_per_unit != null && family.per_unit_basis && (
                <p className="text-sm text-muted-foreground">
                  {formatPrice(family.lowest_price_per_unit)} / {family.per_unit_basis}
                </p>
              )}
            </div>
          )}

          {family.brands.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {family.brands.map((b) => (
                <Badge key={b} variant="secondary" className="text-xs">
                  {b}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </div>

      {variants.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <Store className="h-4 w-4" aria-hidden="true" />
              Всички разфасовки и магазини
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm" aria-label="Цени по магазини и разфасовки">
                <thead>
                  <tr className="border-b text-muted-foreground">
                    <th scope="col" className="pb-2 text-left font-medium">Магазин</th>
                    <th scope="col" className="pb-2 text-left font-medium">Марка</th>
                    <th scope="col" className="pb-2 text-left font-medium hidden sm:table-cell">Разфасовка</th>
                    <th scope="col" className="pb-2 text-right font-medium">Цена</th>
                    <th scope="col" className="pb-2 text-right font-medium hidden md:table-cell">€/ед.</th>
                    <th scope="col" className="pb-2 text-right font-medium hidden sm:table-cell">Обновено</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {variants.map((v, i) => (
                    <tr key={`${v.product_id}-${v.store_id}`} className="hover:bg-muted/50">
                      <td className="py-2 pr-4">
                        <span className="font-medium">{v.store_name}</span>
                        {i === 0 && (
                          <Badge variant="secondary" className="ml-2 text-xs">
                            Най-евтин
                          </Badge>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-sm text-muted-foreground">
                        {v.brand ?? "—"}
                      </td>
                      <td className="py-2 pr-4 text-sm text-muted-foreground hidden sm:table-cell">
                        {v.pack_info ?? "—"}
                      </td>
                      <td className="py-2 text-right font-semibold">
                        {formatPrice(v.price, v.currency)}
                      </td>
                      <td className="py-2 text-right text-sm text-muted-foreground hidden md:table-cell">
                        {v.price_per_unit != null && v.per_unit_basis
                          ? `${formatPrice(v.price_per_unit, v.currency)} / ${v.per_unit_basis}`
                          : "—"}
                      </td>
                      <td className="py-2 text-right text-muted-foreground hidden sm:table-cell">
                        {formatDate(v.recorded_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
