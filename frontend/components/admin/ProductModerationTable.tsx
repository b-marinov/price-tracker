"use client";

import { useState, useCallback } from "react";
import {
  CheckCircle2,
  XCircle,
  Pencil,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

import {
  listPendingProducts,
  approveProduct,
  rejectProduct,
  updateProduct,
  type PendingProduct,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// 29-value Bulgarian grocery taxonomy (mirrors GROCERY_CATEGORIES in llm_parser.py)
const GROCERY_CATEGORIES = [
  "Плодове",
  "Зеленчуци",
  "Месо",
  "Риба и морски дарове",
  "Млечни продукти",
  "Яйца",
  "Хляб и тестени изделия",
  "Зърнени храни и бобови",
  "Захарни изделия",
  "Бисквити и снаксове",
  "Шоколад и сладкиши",
  "Замразени храни",
  "Консерви и буркани",
  "Подправки и сосове",
  "Олио и мазнини",
  "Напитки без алкохол",
  "Алкохолни напитки",
  "Кафе",
  "Чай",
  "Детски храни",
  "Домашни любимци",
  "Хигиена и красота",
  "Козметика и хигиена",
  "Почистващи препарати",
  "Домакинство",
  "Дрехи и обувки",
  "Електроника",
  "Спорт и свободно време",
  "Друго",
];

interface EditState {
  name: string;
  brand: string;
  barcode: string;
  category: string;
}

interface Props {
  adminKey: string;
}

export default function ProductModerationTable({ adminKey }: Props) {
  const [products, setProducts] = useState<PendingProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});
  const [bulkLoading, setBulkLoading] = useState(false);

  // Edit modal state
  const [editProduct, setEditProduct] = useState<PendingProduct | null>(null);
  const [editState, setEditState] = useState<EditState>({ name: "", brand: "", barcode: "", category: "" });
  const [editSaving, setEditSaving] = useState(false);

  const PAGE_SIZE = 20;

  const load = useCallback(
    async (p = 1) => {
      setLoading(true);
      try {
        const res = await listPendingProducts(adminKey, p, PAGE_SIZE);
        setProducts(res.items);
        setTotal(res.total);
        setPage(p);
        setLoaded(true);
      } finally {
        setLoading(false);
      }
    },
    [adminKey],
  );

  async function handleApprove(id: string) {
    setActionLoading((s) => ({ ...s, [id]: true }));
    try {
      await approveProduct(id, adminKey);
      setProducts((prev) => prev.filter((p) => p.id !== id));
      setTotal((t) => t - 1);
    } finally {
      setActionLoading((s) => ({ ...s, [id]: false }));
    }
  }

  async function handleReject(id: string) {
    setActionLoading((s) => ({ ...s, [id]: true }));
    try {
      await rejectProduct(id, adminKey);
      setProducts((prev) => prev.filter((p) => p.id !== id));
      setTotal((t) => t - 1);
    } finally {
      setActionLoading((s) => ({ ...s, [id]: false }));
    }
  }

  async function handleBulkApprove() {
    setBulkLoading(true);
    try {
      await Promise.all(products.map((p) => approveProduct(p.id, adminKey)));
      await load(1);
    } finally {
      setBulkLoading(false);
    }
  }

  function openEdit(product: PendingProduct) {
    setEditProduct(product);
    setEditState({
      name: product.name,
      brand: product.brand ?? "",
      barcode: product.barcode ?? "",
      category: product.category ?? "",
    });
  }

  async function handleSaveEdit() {
    if (!editProduct) return;
    setEditSaving(true);
    try {
      const updates: { name?: string; brand?: string; barcode?: string } = {};
      if (editState.name !== editProduct.name) updates.name = editState.name;
      if (editState.brand !== (editProduct.brand ?? "")) updates.brand = editState.brand || undefined;
      if (editState.barcode !== (editProduct.barcode ?? "")) updates.barcode = editState.barcode || undefined;

      if (Object.keys(updates).length > 0) {
        await updateProduct(editProduct.id, adminKey, updates);
      }
      // Approve after saving
      await approveProduct(editProduct.id, adminKey);
      setProducts((prev) => prev.filter((p) => p.id !== editProduct.id));
      setTotal((t) => t - 1);
      setEditProduct(null);
    } finally {
      setEditSaving(false);
    }
  }

  if (!loaded) {
    return (
      <div className="flex items-center gap-3">
        <Button variant="outline" onClick={() => load(1)} disabled={loading}>
          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Зареди продукти за проверка
        </Button>
        {total > 0 && (
          <span className="text-sm text-muted-foreground">{total} чакащи</span>
        )}
      </div>
    );
  }

  if (products.length === 0 && total === 0) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
        Няма продукти, чакащи одобрение.
      </div>
    );
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <p className="text-sm text-muted-foreground">
          {total} продукта чакат одобрение
        </p>
        <Button
          size="sm"
          onClick={handleBulkApprove}
          disabled={bulkLoading || products.length === 0}
          className="gap-1.5"
        >
          {bulkLoading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5" />
          )}
          Одобри всички на страницата ({products.length})
        </Button>
      </div>

      {/* Table */}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b bg-muted/50 text-xs text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium">Продукт</th>
              <th className="px-3 py-2 text-left font-medium">Марка</th>
              <th className="px-3 py-2 text-left font-medium">Категория</th>
              <th className="px-3 py-2 text-left font-medium">Цена</th>
              <th className="px-3 py-2 text-left font-medium">Магазин</th>
              <th className="px-3 py-2 text-right font-medium">Действия</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {products.map((product) => {
              const busy = actionLoading[product.id];
              return (
                <tr key={product.id} className="hover:bg-muted/30">
                  <td className="px-3 py-2 font-medium max-w-[200px] truncate" title={product.name}>
                    {product.name}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {product.brand ?? <span className="italic text-xs">—</span>}
                  </td>
                  <td className="px-3 py-2">
                    {product.category ? (
                      <Badge variant="secondary" className="text-xs font-normal">
                        {product.category}
                      </Badge>
                    ) : (
                      <span className="italic text-xs text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {product.latest_price != null ? (
                      <span>
                        {product.latest_price.toFixed(2)} €
                        {product.discount_percent != null && (
                          <Badge variant="destructive" className="ml-1.5 text-xs">
                            -{product.discount_percent}%
                          </Badge>
                        )}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground max-w-[140px] truncate">
                    {product.matched_store_names.join(", ")}
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0"
                        onClick={() => openEdit(product)}
                        title="Редактирай"
                        aria-label="Редактирай продукт"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 text-green-600 hover:text-green-700"
                        onClick={() => handleApprove(product.id)}
                        disabled={busy}
                        title="Одобри"
                        aria-label="Одобри продукт"
                      >
                        {busy ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <CheckCircle2 className="h-3.5 w-3.5" />
                        )}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                        onClick={() => handleReject(product.id)}
                        disabled={busy}
                        title="Откажи"
                        aria-label="Откажи продукт"
                      >
                        <XCircle className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <Button
            size="sm"
            variant="outline"
            onClick={() => load(page - 1)}
            disabled={page <= 1 || loading}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="text-muted-foreground">
            {page} / {totalPages}
          </span>
          <Button
            size="sm"
            variant="outline"
            onClick={() => load(page + 1)}
            disabled={page >= totalPages || loading}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* Edit modal */}
      <Dialog open={editProduct !== null} onOpenChange={(open) => !open && setEditProduct(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Редактирай продукт</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Име</label>
              <Input
                value={editState.name}
                onChange={(e) => setEditState((s) => ({ ...s, name: e.target.value }))}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Марка</label>
              <Input
                value={editState.brand}
                onChange={(e) => setEditState((s) => ({ ...s, brand: e.target.value }))}
                placeholder="напр. Nestle, Kaufland Bio…"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Категория</label>
              <Select
                value={editState.category}
                onValueChange={(v) => setEditState((s) => ({ ...s, category: v }))}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Избери категория" />
                </SelectTrigger>
                <SelectContent className="max-h-64">
                  {GROCERY_CATEGORIES.map((cat) => (
                    <SelectItem key={cat} value={cat}>
                      {cat}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">Баркод</label>
              <Input
                value={editState.barcode}
                onChange={(e) => setEditState((s) => ({ ...s, barcode: e.target.value }))}
                placeholder="EAN-13…"
              />
            </div>
          </div>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setEditProduct(null)}>
              Отказ
            </Button>
            <Button onClick={handleSaveEdit} disabled={editSaving || !editState.name.trim()}>
              {editSaving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Запази и одобри
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
