"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Play, RefreshCw, ShieldAlert, CheckCircle2, XCircle, Loader2, Trash2, Terminal, Square } from "lucide-react";

import {
  runAllScrapers,
  runStoreScraper,
  cancelStoreScraper,
  listStores,
  getScraperStatus,
  getAllScraperStatuses,
  getScraperQueue,
  clearScraperQueue,
  getScraperLogs,
  type ScrapeRunStatus,
  type QueueStatus,
  type LogEntry,
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

  const [queue, setQueue] = useState<QueueStatus | null>(null);
  const [clearingQueue, setClearingQueue] = useState(false);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const logRef = useRef<HTMLDivElement>(null);

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
          if (status.status === "completed" || status.status === "failed" || status.status === "cancelled") {
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

  useEffect(() => {
    if (!authenticated) return;

    async function fetchQueueAndLogs() {
      try {
        const [q, l] = await Promise.all([
          getScraperQueue(adminKey),
          getScraperLogs(adminKey, 100),
        ]);
        setQueue(q);
        setLogs(l);
      } catch {
        // ignore
      }
    }

    fetchQueueAndLogs();
    const id = setInterval(fetchQueueAndLogs, 3000);
    return () => clearInterval(id);
  }, [authenticated, adminKey]);

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

  async function handleClearQueue() {
    if (!confirm("Изчисти опашката? Текущата задача продължава.")) return;
    setClearingQueue(true);
    try {
      await clearScraperQueue(adminKey);
      const q = await getScraperQueue(adminKey);
      setQueue(q);
    } catch {
      // ignore
    } finally {
      setClearingQueue(false);
    }
  }

  async function handleAuth() {
    setAuthError("");
    try {
      await getScraperQueue(adminKey);
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
      // Optimistically clear statuses for every dispatched store
      setScrapeStatuses((prev) => {
        const updated = { ...prev };
        for (const slug of res.dispatched) {
          updated[slug] = { store_slug: slug, status: "running", items_found: null, error_msg: null, started_at: null, finished_at: null };
        }
        return updated;
      });
      // Start polling for every dispatched store
      for (const slug of res.dispatched) {
        startPoll(slug, adminKey);
      }
    } catch (err: unknown) {
      setAllError(err instanceof Error ? err.message : "Грешка при стартиране");
    }
  }

  async function handleCancelStore(slug: string) {
    try {
      await cancelStoreScraper(slug, adminKey);
      // Optimistically remove from queue list (covers queued + active cases)
      setQueue((prev) =>
        prev
          ? {
              ...prev,
              pending: Math.max(0, prev.pending - 1),
              active: prev.active.filter((s) => s !== slug),
              queued: prev.queued.filter((s) => s !== slug),
            }
          : prev,
      );
      // If the store was running, polling will update its status to cancelled
    } catch {
      // ignore — status will update on next poll
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

  // Resolve a slug to a human-friendly store name
  const storeName = (slug: string) => stores.find((s) => s.slug === slug)?.name ?? slug;

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

      {/* Queue control + Live logs */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Terminal className="h-5 w-5" />
            Опашка и логове
          </CardTitle>
          <CardDescription>
            Текущо изпълнение и последни съобщения от скрейпъра.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Queue summary */}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm font-medium">В опашката:</span>
            <Badge variant={queue && queue.pending > 0 ? "destructive" : "secondary"}>
              {queue?.pending ?? "—"} задачи
            </Badge>
            <Button
              size="sm"
              variant="outline"
              className="ml-auto shrink-0 gap-1.5 text-destructive hover:text-destructive"
              onClick={handleClearQueue}
              disabled={clearingQueue || !queue || queue.pending === 0}
            >
              {clearingQueue ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Trash2 className="h-3.5 w-3.5" />
              )}
              Изчисти всички
            </Button>
          </div>

          {/* Queued stores list */}
          {queue && (queue.active.length > 0 || queue.queued.length > 0) && (
            <div className="rounded-md border divide-y text-sm">
              {queue.active.map((slug) => (
                <div key={`active-${slug}`} className="flex items-center gap-3 px-3 py-2 bg-yellow-50 dark:bg-yellow-950/20">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-yellow-600 shrink-0" />
                  <span className="flex-1 font-medium">
                    {storeName(slug)}
                    <span className="ml-1.5 text-xs font-normal text-muted-foreground">({slug})</span>
                  </span>
                  <Badge variant="outline" className="text-yellow-600 border-yellow-400 text-xs">Работи</Badge>
                  <Button
                    size="sm"
                    variant="destructive"
                    className="h-7 px-2 gap-1 text-xs"
                    onClick={() => handleCancelStore(slug)}
                  >
                    <Square className="h-3 w-3" />
                    Спри
                  </Button>
                </div>
              ))}
              {queue.queued.map((slug) => (
                <div key={`queued-${slug}`} className="flex items-center gap-3 px-3 py-2">
                  <div className="h-3.5 w-3.5 rounded-full border-2 border-muted-foreground shrink-0" />
                  <span className="flex-1">
                    {storeName(slug)}
                    <span className="ml-1.5 text-xs text-muted-foreground">({slug})</span>
                  </span>
                  <Badge variant="secondary" className="text-xs">В опашката</Badge>
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 px-2 gap-1 text-xs text-destructive hover:text-destructive"
                    onClick={() => handleCancelStore(slug)}
                  >
                    <Square className="h-3 w-3" />
                    Премахни
                  </Button>
                </div>
              ))}
            </div>
          )}
          {queue && queue.pending === 0 && (
            <p className="text-xs text-muted-foreground">Опашката е празна.</p>
          )}

          {/* Log viewer */}
          <div
            ref={logRef}
            className="h-64 overflow-y-auto rounded-md border bg-black p-3 font-mono text-xs"
            aria-label="Живи логове"
          >
            {logs.length === 0 ? (
              <p className="text-muted-foreground">Няма логове.</p>
            ) : (
              [...logs].reverse().map((entry, i) => (
                <div
                  key={i}
                  className={
                    entry.level === "ERROR"
                      ? "text-red-400"
                      : entry.level === "WARNING"
                        ? "text-yellow-400"
                        : entry.level === "DEBUG"
                          ? "text-gray-500"
                          : "text-green-400"
                  }
                >
                  <span className="text-gray-500 mr-1">
                    {new Date(entry.ts).toLocaleTimeString("bg-BG")}
                  </span>
                  <span className="text-blue-400 mr-1">[{entry.store}]</span>
                  {entry.msg}
                </div>
              ))
            )}
          </div>
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
            const isCancelled = st?.status === "cancelled";
            const isQueued = !isRunning && (queue?.queued.includes(slug) ?? false);

            return (
              <Card key={store.id}>
                <CardContent className="p-4 space-y-2">
                  <div className="flex items-center justify-between gap-4">
                    <div className="min-w-0">
                      <p className="font-medium">{store.name}</p>
                      <p className="text-xs text-muted-foreground">{slug}</p>
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      {isQueued && (
                        <Badge variant="secondary" className="gap-1 text-xs">
                          В опашката
                        </Badge>
                      )}
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
                      {isCancelled && (
                        <Badge variant="outline" className="gap-1 text-muted-foreground">
                          <Square className="h-3 w-3" />
                          Спрян
                        </Badge>
                      )}
                      {isRunning && (
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleCancelStore(slug)}
                          className="gap-1"
                          aria-label={`Спри скрейпър за ${store.name}`}
                        >
                          <Square className="h-3.5 w-3.5" />
                          Спри
                        </Button>
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
                  {isCancelled && (
                    <p className="text-xs text-muted-foreground">Скрейпърът беше спрян ръчно.</p>
                  )}
                  {!isRunning && !isCompleted && !isFailed && !isCancelled && st?.finished_at && (
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
