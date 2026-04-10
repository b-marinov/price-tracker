"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Play, RefreshCw, ShieldAlert, CheckCircle2, XCircle, Loader2 } from "lucide-react";

import {
  runAllScrapers,
  runStoreScraper,
  listStores,
  getScraperStatus,
  getAllScraperStatuses,
  type ScrapeRunStatus,
} from "@/lib/api";
import ProductModerationTable from "@/components/admin/ProductModerationTable";
import CatalogueTable from "@/components/admin/CatalogueTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { Store } from "@/types";

const POLL_INTERVAL_MS = 2000;

export default function AdminPage() {
  const [adminKey, setAdminKey] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [authError, setAuthError] = useState("");
  const [stores, setStores] = useState<Store[]>([]);

  // Per-store run status from API
  const [scrapeStatuses, setScrapeStatuses] = useState<Record<string, ScrapeRunStatus>>({});

  // "Run all" summary state
  const [allDispatched, setAllDispatched] = useState(false);
  const [allMessage, setAllMessage] = useState("");
  const [allError, setAllError] = useState("");

  // Polling intervals keyed by slug
  const pollRefs = useRef<Record<string, ReturnType<typeof setInterval>>>({});

  // Stop polling for a slug
  const stopPoll = useCallback((slug: string) => {
    if (pollRefs.current[slug]) {
      clearInterval(pollRefs.current[slug]);
      delete pollRefs.current[slug];
    }
  }, []);

  // Start polling for a slug every 2s
  const startPoll = useCallback(
    (slug: string, key: string) => {
      stopPoll(slug);
      const id = setInterval(async () => {
        try {
          const status = await getScraperStatus(slug, key);
          setScrapeStatuses((prev) => ({ ...prev, [slug]: status }));
          if (status.status === "completed" || status.status === "failed") {
            stopPoll(slug);
          }
        } catch {
          stopPoll(slug);
        }
      }, POLL_INTERVAL_MS);
      pollRefs.current[slug] = id;
    },
    [stopPoll],
  );

  // Cleanup all polls on unmount
  useEffect(() => {
    return () => {
      Object.keys(pollRefs.current).forEach(stopPoll);
    };
  }, [stopPoll]);

  // Load stores + initial statuses once authenticated
  useEffect(() => {
    if (!authenticated) return;
    listStores().then(setStores).catch(() => setStores([]));
    getAllScraperStatuses(adminKey)
      .then((statuses) => {
        const map: Record<string, ScrapeRunStatus> = {};
        for (const s of statuses) map[s.store_slug] = s;
        setScrapeStatuses(map);
        // Resume polling for any that are still running
        for (const s of statuses) {
          if (s.status === "running") startPoll(s.store_slug, adminKey);
        }
      })
      .catch(() => {});
  }, [authenticated, adminKey, startPoll]);

  async function handleAuth() {
    setAuthError("");
    try {
      await runAllScrapers(adminKey);
      setAuthenticated(true);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes("403") || msg.toLowerCase().includes("invalid")) {
        setAuthError("Невалиден администраторски ключ");
      } else {
        setAuthenticated(true);
      }
    }
  }

  async function handleRunAll() {
    setAllDispatched(false);
    setAllMessage("");
    setAllError("");
    try {
      const res = await runAllScrapers(adminKey);
      setAllDispatched(true);
      setAllMessage(res.message);
      // Start polling for every dispatched store
      for (const slug of res.dispatched) {
        startPoll(slug, adminKey);
      }
    } catch (err: unknown) {
      setAllError(err instanceof Error ? err.message : "Грешка при стартиране");
    }
  }

  async function handleRunStore(slug: string) {
    setScrapeStatuses((prev) => ({
      ...prev,
      [slug]: { store_slug: slug, status: "running", items_found: null, error_msg: null, started_at: null, finished_at: null },
    }));
    try {
      await runStoreScraper(slug, adminKey);
      startPoll(slug, adminKey);
    } catch (err: unknown) {
      setScrapeStatuses((prev) => ({
        ...prev,
        [slug]: {
          store_slug: slug,
          status: "failed",
          items_found: null,
          error_msg: err instanceof Error ? err.message : "Грешка",
          started_at: null,
          finished_at: null,
        },
      }));
    }
  }

  // Count running stores for the "run all" aggregate
  const runningCount = Object.values(scrapeStatuses).filter((s) => s.status === "running").length;
  const allRunning = allDispatched && runningCount > 0;

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
            {authError && <p className="text-sm text-destructive">{authError}</p>}
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
        <p className="mt-1 text-sm text-muted-foreground">Управление на скрейпъри и данни</p>
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
          <Button onClick={handleRunAll} disabled={allRunning} size="lg">
            {allRunning ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Play className="mr-2 h-4 w-4" />
            )}
            {allRunning ? `Работи (${runningCount} магазина)…` : "Стартирай всички"}
          </Button>

          {allDispatched && !allRunning && allMessage && (
            <span className="flex items-center gap-1.5 text-sm text-green-600 dark:text-green-400">
              <CheckCircle2 className="h-4 w-4" />
              {allMessage}
            </span>
          )}
          {allError && (
            <span className="flex items-center gap-1.5 text-sm text-destructive">
              <XCircle className="h-4 w-4" />
              {allError}
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
            const slug = store.slug ?? "";
            const st = scrapeStatuses[slug];
            const isRunning = st?.status === "running";
            const isCompleted = st?.status === "completed";
            const isFailed = st?.status === "failed";

            return (
              <Card key={store.id}>
                <CardContent className="p-4 space-y-2">
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="font-medium">{store.name}</p>
                      <p className="text-xs text-muted-foreground">{slug}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {isCompleted && (
                        <Badge variant="secondary" className="gap-1 text-green-600">
                          <CheckCircle2 className="h-3 w-3" />
                          Готово
                        </Badge>
                      )}
                      {isFailed && (
                        <Badge variant="destructive" className="gap-1">
                          <XCircle className="h-3 w-3" />
                          Грешка
                        </Badge>
                      )}
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleRunStore(slug)}
                        disabled={isRunning}
                        aria-label={`Стартирай скрейпър за ${store.name}`}
                      >
                        {isRunning ? (
                          <Loader2 className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Play className="h-3.5 w-3.5" />
                        )}
                      </Button>
                    </div>
                  </div>

                  {/* Progress bar */}
                  {isRunning && (
                    <Progress value={undefined} className="h-1.5" aria-label="Работи…" />
                  )}

                  {/* Result row */}
                  {isCompleted && st.items_found != null && (
                    <p className="text-xs text-muted-foreground">
                      {st.items_found} {st.items_found === 1 ? "продукт" : "продукта"} намерени
                    </p>
                  )}
                  {isFailed && st.error_msg && (
                    <p className="text-xs text-destructive truncate" title={st.error_msg}>
                      {st.error_msg}
                    </p>
                  )}
                  {!isRunning && !isCompleted && !isFailed && st?.finished_at && (
                    <p className="text-xs text-muted-foreground">
                      Последно: {new Date(st.finished_at).toLocaleString("bg-BG")}
                    </p>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </div>
  );
}
