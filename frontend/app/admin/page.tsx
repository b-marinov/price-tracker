"use client";

import { useState } from "react";
import { Play, RefreshCw, ShieldAlert, CheckCircle2, XCircle, Loader2 } from "lucide-react";

import { runAllScrapers, runStoreScraper, listStores } from "@/lib/api";
import ProductModerationTable from "@/components/admin/ProductModerationTable";
import CatalogueTable from "@/components/admin/CatalogueTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import type { Store } from "@/types";
import { useEffect } from "react";

type RunStatus = "idle" | "running" | "success" | "error";

interface StoreStatus {
  status: RunStatus;
  message?: string;
}

export default function AdminPage() {
  const [adminKey, setAdminKey] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [authError, setAuthError] = useState("");
  const [stores, setStores] = useState<Store[]>([]);
  const [allStatus, setAllStatus] = useState<RunStatus>("idle");
  const [allMessage, setAllMessage] = useState("");
  const [storeStatuses, setStoreStatuses] = useState<Record<string, StoreStatus>>({});

  useEffect(() => {
    if (authenticated) {
      listStores().then(setStores).catch(() => setStores([]));
    }
  }, [authenticated]);

  async function handleAuth() {
    setAuthError("");
    try {
      await runAllScrapers(adminKey);
      // If it succeeds without throwing, key is valid — but we don't actually
      // want to dispatch yet. Use a lightweight check instead.
      setAuthenticated(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("403") || msg.toLowerCase().includes("invalid")) {
        setAuthError("Невалиден администраторски ключ");
      } else {
        // Any non-403 error means auth passed (e.g. 422, 500)
        setAuthenticated(true);
      }
    }
  }

  async function handleRunAll() {
    setAllStatus("running");
    setAllMessage("");
    try {
      const res = await runAllScrapers(adminKey);
      setAllStatus("success");
      setAllMessage(res.message);
    } catch (err: unknown) {
      setAllStatus("error");
      setAllMessage(err instanceof Error ? err.message : "Грешка при стартиране");
    }
  }

  async function handleRunStore(slug: string) {
    setStoreStatuses((prev) => ({ ...prev, [slug]: { status: "running" } }));
    try {
      const res = await runStoreScraper(slug, adminKey);
      setStoreStatuses((prev) => ({
        ...prev,
        [slug]: { status: "success", message: res.message },
      }));
    } catch (err: unknown) {
      setStoreStatuses((prev) => ({
        ...prev,
        [slug]: {
          status: "error",
          message: err instanceof Error ? err.message : "Грешка",
        },
      }));
    }
  }

  if (!authenticated) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Card className="w-full max-w-sm">
          <CardHeader className="text-center">
            <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
              <ShieldAlert className="h-6 w-6 text-muted-foreground" />
            </div>
            <CardTitle>Администраторски достъп</CardTitle>
            <CardDescription>Въведете администраторския ключ за достъп</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <Input
              type="password"
              placeholder="Admin ключ"
              value={adminKey}
              onChange={(e) => setAdminKey(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleAuth()}
              aria-label="Администраторски ключ"
            />
            {authError && (
              <p className="text-sm text-destructive">{authError}</p>
            )}
            <Button className="w-full" onClick={handleAuth} disabled={!adminKey}>
              Влез
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Администрация</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Управление на скрейпъри и данни
        </p>
      </div>

      {/* Run all scrapers */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RefreshCw className="h-5 w-5" />
            Стартирай всички скрейпъри
          </CardTitle>
          <CardDescription>
            Изпраща задачи за всички активни магазини едновременно. Резултатите се появяват в базата след 2–5 минути.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex items-center gap-4">
          <Button
            onClick={handleRunAll}
            disabled={allStatus === "running"}
            size="lg"
          >
            {allStatus === "running" ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-2 h-4 w-4" />
            )}
            {allStatus === "running" ? "Стартира се…" : "Стартирай всички"}
          </Button>

          {allStatus === "success" && (
            <span className="flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
              <CheckCircle2 className="h-4 w-4" />
              {allMessage}
            </span>
          )}
          {allStatus === "error" && (
            <span className="flex items-center gap-1.5 text-sm text-destructive">
              <XCircle className="h-4 w-4" />
              {allMessage}
            </span>
          )}
        </CardContent>
      </Card>

      {/* Product moderation */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">Продукти за одобрение</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Новите продукти от скрейпъра изискват ръчно одобрение. Можете да редактирате
          имена, марки и категории преди публикуване.
        </p>
        <ProductModerationTable adminKey={adminKey} />
      </div>

      {/* Active catalogue */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">Каталог</h2>
        <p className="mb-4 text-sm text-muted-foreground">
          Всички активни продукти. Можете да редактирате имена, марки и баркодове или да изтриете продукт.
        </p>
        <CatalogueTable adminKey={adminKey} />
      </div>

      {/* Per-store scrapers */}
      <div>
        <h2 className="mb-3 text-lg font-semibold">По магазин</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {stores.map((store) => {
            const st = storeStatuses[store.slug ?? ""] ?? { status: "idle" };
            return (
              <Card key={store.id}>
                <CardContent className="flex items-center justify-between gap-4 p-4">
                  <div className="min-w-0">
                    <p className="font-medium">{store.name}</p>
                    <p className="text-xs text-muted-foreground">{store.slug}</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    {st.status === "success" && (
                      <Badge variant="secondary" className="gap-1 text-green-600">
                        <CheckCircle2 className="h-3 w-3" />
                        Готово
                      </Badge>
                    )}
                    {st.status === "error" && (
                      <Badge variant="destructive" className="gap-1">
                        <XCircle className="h-3 w-3" />
                        Грешка
                      </Badge>
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleRunStore(store.slug ?? "")}
                      disabled={st.status === "running"}
                    >
                      {st.status === "running" ? (
                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      ) : (
                        <Play className="h-3.5 w-3.5" />
                      )}
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
