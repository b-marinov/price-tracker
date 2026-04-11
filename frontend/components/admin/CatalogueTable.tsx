"use client";

import { useState, useCallback } from "react";
import {
  Pencil,
  Trash2,
  Loader2,
  ChevronLeft,
  ChevronRight,
  Search,
} from "lucide-react";

import {
  listActiveProducts,
  updateProduct,
  deleteProduct,
  batchDeleteProducts,
  type ActiveProduct,
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

interface EditState {
  name: string;
  brand: string;
  barcode: string;
}

interface Props {
  adminKey: string;
}

export default function CatalogueTable({ adminKey }: Props) {
  const [products, setProducts] = useState<ActiveProduct[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});

  // Batch selection state
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [batchDeleteOpen, setBatchDeleteOpen] = useState(false);
  const [batchDeleteLoading, setBatchDeleteLoading] = useState(false);

  // Edit modal state
  const [editProduct, setEditProduct] = useState<ActiveProduct | null>(null);
  const [editState, setEditState] = useState<EditState>({ name: "", brand: "", barcode: "" });
  const [editSaving, setEditSaving] = useState(false);

  // Delete confirm modal state
  const [deleteTarget, setDeleteTarget] = useState<ActiveProduct | null>(null);
  const [deleteLoading, setDeleteLoading] = useState(false);

  const PAGE_SIZE = 50;

  const load = useCallback(
    async (p = 1, q = search) => {
      setLoading(true);
      setSelected(new Set());
      try {
        const res = await listActiveProducts(adminKey, p, PAGE_SIZE, q || undefined);
        setProducts(res.items);
        setTotal(res.total);
        setPage(p);
        setLoaded(true);
      } finally {
        setLoading(false);
      }
    },
    [adminKey, search],
  );

  function handleSearch() {
    setSearch(searchInput);
    load(1, searchInput);
  }

  // ---------------------------------------------------------------------------
  // Selection helpers
  // ---------------------------------------------------------------------------

  const allOnPageSelected =
    products.length > 0 && products.every((p) => selected.has(p.id));

  function toggleSelectAll() {
    if (allOnPageSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(products.map((p) => p.id)));
    }
  }

  function toggleSelect(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  // ---------------------------------------------------------------------------
  // Batch delete
  // ---------------------------------------------------------------------------

  async function handleBatchDelete() {
    setBatchDeleteLoading(true);
    try {
      const ids = [...selected];
      await batchDeleteProducts(ids, adminKey);
      setProducts((prev) => prev.filter((p) => !selected.has(p.id)));
      setTotal((t) => t - selected.size);
      setSelected(new Set());
      setBatchDeleteOpen(false);
    } finally {
      setBatchDeleteLoading(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Edit
  // ---------------------------------------------------------------------------

  function openEdit(product: ActiveProduct) {
    setEditProduct(product);
    setEditState({
      name: product.name,
      brand: product.brand ?? "",
      barcode: product.barcode ?? "",
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
        setProducts((prev) =>
          prev.map((p) =>
            p.id === editProduct.id
              ? {
                  ...p,
                  name: updates.name ?? p.name,
                  brand: updates.brand !== undefined ? (updates.brand || null) : p.brand,
                  barcode: updates.barcode !== undefined ? (updates.barcode || null) : p.barcode,
                }
              : p,
          ),
        );
      }
      setEditProduct(null);
    } finally {
      setEditSaving(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Single delete
  // ---------------------------------------------------------------------------

  async function handleDelete() {
    if (!deleteTarget) return;
    setDeleteLoading(true);
    try {
      await deleteProduct(deleteTarget.id, adminKey);
      setProducts((prev) => prev.filter((p) => p.id !== deleteTarget.id));
      setTotal((t) => t - 1);
      setSelected((prev) => {
        const next = new Set(prev);
        next.delete(deleteTarget.id);
        return next;
      });
      setDeleteTarget(null);
    } finally {
      setDeleteLoading(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (!loaded) {
    return (
      <div className="flex items-center gap-3">
        <Button variant="outline" onClick={() => load(1)} disabled={loading}>
          {loading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
          Зареди каталога
        </Button>
      </div>
    );
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="space-y-4">
      {/* Search + stats row */}
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-muted-foreground">{total} активни продукта</p>

        {/* Batch delete button — shown when items are selected */}
        {selected.size > 0 && (
          <Button
            size="sm"
            variant="destructive"
            onClick={() => setBatchDeleteOpen(true)}
            className="flex items-center gap-1.5"
          >
            <Trash2 className="h-3.5 w-3.5" />
            Изтрий {selected.size} избрани
          </Button>
        )}

        <div className="flex gap-2 ml-auto">
          <Input
            className="h-8 w-56 text-sm"
            placeholder="Търси по име или марка…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          />
          <Button size="sm" variant="outline" onClick={handleSearch} disabled={loading}>
            <Search className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {products.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Няма намерени продукти.
        </div>
      ) : (
        <>
          {/* Table */}
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b bg-muted/50 text-xs text-muted-foreground">
                  {/* Select-all checkbox */}
                  <th className="w-8 px-3 py-2">
                    <input
                      type="checkbox"
                      checked={allOnPageSelected}
                      onChange={toggleSelectAll}
                      aria-label="Избери всички на страницата"
                      className="cursor-pointer"
                    />
                  </th>
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
                  const isSelected = selected.has(product.id);
                  return (
                    <tr
                      key={product.id}
                      className={isSelected ? "bg-muted/50" : "hover:bg-muted/30"}
                    >
                      <td className="w-8 px-3 py-2">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelect(product.id)}
                          aria-label={`Избери ${product.name}`}
                          className="cursor-pointer"
                        />
                      </td>
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
                            disabled={busy}
                          >
                            <Pencil className="h-3.5 w-3.5" />
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 w-7 p-0 text-destructive hover:text-destructive"
                            onClick={() => setDeleteTarget(product)}
                            title="Изтрий"
                            aria-label="Изтрий продукт"
                            disabled={busy}
                          >
                            <Trash2 className="h-3.5 w-3.5" />
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
        </>
      )}

      {/* Batch delete confirm modal */}
      <Dialog open={batchDeleteOpen} onOpenChange={(open) => !open && setBatchDeleteOpen(false)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Изтрий избраните продукти</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-2">
            Сигурен ли си, че искаш да изтриеш{" "}
            <span className="font-semibold text-foreground">{selected.size}</span>{" "}
            {selected.size === 1 ? "продукт" : "продукта"}?
            Това действие е необратимо и ще изтрие и всички цени за тях.
          </p>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setBatchDeleteOpen(false)}>
              Отказ
            </Button>
            <Button variant="destructive" onClick={handleBatchDelete} disabled={batchDeleteLoading}>
              {batchDeleteLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Изтрий {selected.size}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

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
              Запази
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Single delete confirm modal */}
      <Dialog open={deleteTarget !== null} onOpenChange={(open) => !open && setDeleteTarget(null)}>
        <DialogContent className="sm:max-w-sm">
          <DialogHeader>
            <DialogTitle>Изтрий продукт</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-2">
            Сигурен ли си, че искаш да изтриеш{" "}
            <span className="font-medium text-foreground">{deleteTarget?.name}</span>?
            Това действие е необратимо и ще изтрие и всички цени за продукта.
          </p>
          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              Отказ
            </Button>
            <Button variant="destructive" onClick={handleDelete} disabled={deleteLoading}>
              {deleteLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              Изтрий
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
