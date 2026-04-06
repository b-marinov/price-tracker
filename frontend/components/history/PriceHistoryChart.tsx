"use client";

import { useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

import type { StoreResult } from "@/types";
import { Button } from "@/components/ui/button";

/** Preset date ranges shown as quick-pick buttons. */
const DATE_RANGES = [
  { label: "1С", days: 7 },
  { label: "1М", days: 30 },
  { label: "3М", days: 90 },
  { label: "1Г", days: 365 },
] as const;

/** One colour per store (up to 8 stores). */
const STORE_COLORS = [
  "#2563eb", // blue
  "#16a34a", // green
  "#dc2626", // red
  "#d97706", // amber
  "#7c3aed", // violet
  "#0891b2", // cyan
  "#be185d", // pink
  "#78716c", // stone
];

interface TooltipPayloadItem {
  name: string;
  value: number;
  color: string;
  dataKey: string;
}

interface CustomTooltipProps {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}

function CustomTooltip({ active, payload, label }: CustomTooltipProps) {
  if (!active || !payload?.length) return null;

  return (
    <div
      role="tooltip"
      className="rounded-lg border bg-background p-3 shadow-lg text-sm"
    >
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((entry) => (
        <p key={entry.dataKey} style={{ color: entry.color }}>
          {entry.name}:{" "}
          <span className="font-semibold">
            {new Intl.NumberFormat("bg-BG", {
              style: "currency",
              currency: "EUR",
              minimumFractionDigits: 2,
            }).format(entry.value)}
          </span>
        </p>
      ))}
    </div>
  );
}

interface PriceHistoryChartProps {
  storeResults: StoreResult[];
  productName: string;
}

/**
 * Interactive line chart showing price history per store.
 *
 * - Multi-store: each store is a separate coloured line
 * - Date range picker: 1W, 1M, 3M, 1Y (filters visible data client-side)
 * - Tooltip shows exact price + store on hover
 * - Screen-reader description of the trend direction
 */
export function PriceHistoryChart({
  storeResults,
  productName,
}: PriceHistoryChartProps) {
  const [rangeDays, setRangeDays] = useState<number>(30);

  if (storeResults.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" role="status">
        Няма данни за ценова история.
      </p>
    );
  }

  // Collect all dates, filter to range, sort
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - rangeDays);

  const allDates = Array.from(
    new Set(
      storeResults.flatMap((s) =>
        s.data.map((d) => d.date).filter((d) => new Date(d) >= cutoff)
      )
    )
  ).sort();

  // Build rows: { date, [storeName]: price }
  type ChartRow = { date: string } & Record<string, number>;
  const rows: ChartRow[] = allDates.map((date) => {
    const row: ChartRow = { date };
    for (const store of storeResults) {
      const point = store.data.find((d) => d.date === date);
      if (point) {
        row[store.store_name] = point.price;
      }
    }
    return row;
  });

  // Accessible trend description
  const trendSummary = storeResults
    .map((s) => {
      const inRange = s.data.filter((d) => new Date(d.date) >= cutoff);
      if (inRange.length < 2) return null;
      const first = inRange[0].price;
      const last = inRange[inRange.length - 1].price;
      const diff = ((last - first) / first) * 100;
      const direction = diff > 1 ? "нагоре" : diff < -1 ? "надолу" : "стабилна";
      return `${s.store_name}: ${direction} с ${Math.abs(diff).toFixed(1)}%`;
    })
    .filter(Boolean)
    .join("; ");

  return (
    <div className="space-y-3">
      {/* Screen-reader summary */}
      <p className="sr-only" aria-live="polite">
        Ценова история за {productName}. {trendSummary}
      </p>

      {/* Date range picker */}
      <div
        className="flex gap-1"
        role="group"
        aria-label="Избор на период"
      >
        {DATE_RANGES.map(({ label, days }) => (
          <Button
            key={days}
            variant={rangeDays === days ? "default" : "outline"}
            size="sm"
            onClick={() => setRangeDays(days)}
            aria-pressed={rangeDays === days}
            className="h-7 px-3 text-xs"
          >
            {label}
          </Button>
        ))}
      </div>

      {/* Chart */}
      <div
        role="img"
        aria-label={`Линейна графика на ценовата история за ${productName} за последните ${rangeDays} дни`}
        className="h-64 w-full"
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-border" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 11 }}
              tickLine={false}
              tickFormatter={(v: string) => {
                const d = new Date(v);
                return `${d.getDate()}.${d.getMonth() + 1}`;
              }}
            />
            <YAxis
              tick={{ fontSize: 11 }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => `${v.toFixed(2)}`}
              width={52}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: "12px", paddingTop: "8px" }}
              iconType="line"
            />
            {storeResults.map((store, i) => (
              <Line
                key={store.store_id}
                type="monotone"
                dataKey={store.store_name}
                stroke={STORE_COLORS[i % STORE_COLORS.length]}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
