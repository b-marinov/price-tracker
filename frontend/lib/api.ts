/**
 * Typed API client for the price-tracker FastAPI backend.
 *
 * All functions use the native `fetch` API and read the base URL from the
 * `NEXT_PUBLIC_API_BASE_URL` environment variable.  Errors from the backend
 * (non-2xx responses) are thrown as `Error` instances with the detail message
 * from the JSON body so callers can display meaningful messages.
 *
 * @module lib/api
 */

import type {
  ApiError,
  BrowseResponse,
  Brochure,
  Category,
  ComparisonResponse,
  DealItem,
  DealsResponse,
  PaginatedResponse,
  PriceHistoryResponse,
  ProductDetail,
  ProductFamilyDetail,
  ProductFamilyListItem,
  ProductListItem,
  SearchCompareResponse,
  Store,
} from "@/types";

// ---------------------------------------------------------------------------
// Base configuration
// ---------------------------------------------------------------------------

// Server components run inside the Docker network and call the API
// directly via INTERNAL_API_BASE_URL.
//
// Browser-side, we route through the Next.js dev server's `/api/*`
// rewrite (see next.config.js).  Same-origin means no CORS preflight,
// which sidesteps a class of "Failed to fetch" errors caused by
// browser extensions / strict CORS handling on cross-origin DELETEs.
// In production builds, NEXT_PUBLIC_API_BASE_URL takes over.
const API_BASE =
  typeof window === "undefined"
    ? (process.env.INTERNAL_API_BASE_URL?.replace(/\/$/, "") ??
       process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
       "http://localhost:8000")
    : process.env.NODE_ENV === "development"
      ? "/api"
      : (process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
         "http://localhost:8000");

/** Supported aggregation intervals for price history. */
export type PriceInterval = "daily" | "weekly";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Core fetch wrapper.
 *
 * Appends the base URL, sets JSON content-type, and throws on non-2xx
 * responses with the backend's `detail` message.
 *
 * @param path - Relative API path (e.g. `/products`).
 * @param options - Native `RequestInit` options forwarded to `fetch`.
 * @returns Parsed JSON response body typed as `T`.
 * @throws `Error` with the backend detail message on non-2xx status.
 */
async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const method = options?.method ?? "GET";

  let response: Response;
  try {
    response = await fetch(url, {
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      ...options,
    });
  } catch (err) {
    // Network-level failure (server down, CORS rejection, DNS, offline, ...).
    // The native error here is just "Failed to fetch" with no detail — surface
    // the URL and method so the caller can show something actionable.
    const cause = err instanceof Error ? err.message : String(err);
    throw new Error(
      `Network error: ${method} ${url} — ${cause}. Provери, че бекендът работи и че URL-ът (NEXT_PUBLIC_API_BASE_URL) е правилен.`,
    );
  }

  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body: ApiError = await response.json();
      detail = body.detail ?? detail;
    } catch {
      // JSON parse failed — use the status line
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

/**
 * Build a URL query string from a plain object, omitting `undefined` values.
 *
 * @param params - Object of query parameter key-value pairs.
 * @returns Encoded query string including the leading `?`, or `""` if empty.
 */
function buildQuery(params: Record<string, string | number | undefined>): string {
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      searchParams.set(key, String(value));
    }
  }
  const qs = searchParams.toString();
  return qs ? `?${qs}` : "";
}

// ---------------------------------------------------------------------------
// Product catalogue endpoints
// ---------------------------------------------------------------------------

/** Parameters for listing / paginating product families. */
export interface ListProductsParams {
  limit?: number;
  offset?: number;
  category_id?: string;
  store_id?: string;
  /** Case-insensitive substring filter on product name. */
  q?: string;
}

/**
 * Fetch a paginated list of product families (catalog-name aggregation).
 *
 * Maps to `GET /products`.
 */
export async function listProducts(
  params: ListProductsParams = {}
): Promise<PaginatedResponse<ProductFamilyListItem>> {
  const qs = buildQuery(params as Record<string, string | number | undefined>);
  return apiFetch<PaginatedResponse<ProductFamilyListItem>>(`/products${qs}`);
}

/**
 * Search product families by name substring.
 *
 * Routes through the aggregated `GET /products?q=…` endpoint so search
 * results share the same card shape as the main listing.
 */
export async function searchProducts(
  params: { q: string; limit?: number; offset?: number }
): Promise<PaginatedResponse<ProductFamilyListItem>> {
  return listProducts(params);
}

/**
 * Fetch full breakdown for a catalog product family by its URL slug.
 *
 * Maps to `GET /products/by-name/{name_slug}`.
 */
export async function getProductFamily(nameSlug: string): Promise<ProductFamilyDetail> {
  return apiFetch<ProductFamilyDetail>(`/products/by-name/${encodeURIComponent(nameSlug)}`);
}

/**
 * Fetch full product detail with current prices at all stores.
 *
 * Maps to `GET /products/{product_id}`.
 *
 * @param productId - UUID of the product.
 * @returns {@link ProductDetail} including per-store prices.
 * @throws `Error` with "Product not found" on 404.
 */
export async function getProduct(productId: string): Promise<ProductDetail> {
  return apiFetch<ProductDetail>(`/products/${productId}`);
}

// ---------------------------------------------------------------------------
// Price comparison endpoints
// ---------------------------------------------------------------------------

/**
 * Compare the current price of a product across all stores.
 *
 * Maps to `GET /products/{product_id}/compare`.
 *
 * @param productId - UUID of the product.
 * @returns {@link ComparisonResponse} sorted cheapest first.
 * @throws `Error` with "Product not found" on 404.
 */
export async function compareProductPrices(
  productId: string
): Promise<ComparisonResponse> {
  return apiFetch<ComparisonResponse>(`/products/${productId}/compare`);
}

/**
 * Search for products and return the cheapest store price for each match.
 *
 * Maps to `GET /products/compare?q=…`.
 *
 * @param q - Search query string (min 1, max 200 characters).
 * @returns {@link SearchCompareResponse} with up to 5 matching products.
 */
export async function searchCompareProducts(
  q: string
): Promise<SearchCompareResponse> {
  const qs = buildQuery({ q });
  return apiFetch<SearchCompareResponse>(`/products/compare${qs}`);
}

// ---------------------------------------------------------------------------
// Price history endpoint
// ---------------------------------------------------------------------------

/** Parameters for fetching price history. */
export interface GetPriceHistoryParams {
  /** Filter to a single store UUID. */
  store_id?: string;
  /** Start date (inclusive), ISO format e.g. "2026-01-01". */
  from_date?: string;
  /** End date (inclusive), ISO format e.g. "2026-04-06". */
  to_date?: string;
  /** Aggregation interval (default "daily"). */
  interval?: PriceInterval;
}

/**
 * Fetch price history for a product, grouped by store.
 *
 * Maps to `GET /products/{product_id}/history`.
 *
 * @param productId - UUID of the product.
 * @param params - Optional filters (store, date range, interval).
 * @returns {@link PriceHistoryResponse} with per-store time series data.
 * @throws `Error` with "Product not found" on 404.
 */
export async function getProductPrices(
  productId: string,
  params: GetPriceHistoryParams = {}
): Promise<PriceHistoryResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>);
  return apiFetch<PriceHistoryResponse>(
    `/products/${productId}/history${qs}`
  );
}

// Alias matching the acceptance criteria naming
export { getProductPrices as getPriceHistory };

// ---------------------------------------------------------------------------
// Category endpoints
// ---------------------------------------------------------------------------

/**
 * Fetch the full category tree.
 *
 * Maps to `GET /categories`.
 *
 * @returns Nested array of root {@link Category} nodes with children.
 */
export async function listCategories(): Promise<Category[]> {
  return apiFetch<Category[]>("/categories");
}

/** Parameters for listing products in a category. */
export interface ListCategoryProductsParams {
  /** Maximum number of items per page (1-100, default 20). */
  limit?: number;
  /** Number of items to skip (default 0). */
  offset?: number;
}

/**
 * Fetch paginated product families in a category (including subcategories).
 *
 * Maps to `GET /categories/{category_id}/products`.  Returns the same
 * catalog-name aggregation as the main product listing.
 */
export async function listCategoryProducts(
  categoryId: string,
  params: ListCategoryProductsParams = {}
): Promise<PaginatedResponse<ProductFamilyListItem>> {
  const qs = buildQuery(params as Record<string, string | number | undefined>);
  return apiFetch<PaginatedResponse<ProductFamilyListItem>>(
    `/categories/${categoryId}/products${qs}`
  );
}

// ---------------------------------------------------------------------------
// Store and brochure endpoints
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Admin endpoints
// ---------------------------------------------------------------------------

/** Response from scraper dispatch endpoints. */
export interface ScraperRunResponse {
  dispatched: string[];
  message: string;
}

/**
 * Trigger scrapers for all active stores.
 *
 * Maps to `POST /admin/scrapers/run`.
 *
 * @param adminKey - Value for the `X-Admin-Key` header.
 * @returns List of dispatched store slugs.
 */
export async function runAllScrapers(adminKey: string): Promise<ScraperRunResponse> {
  return apiFetch<ScraperRunResponse>("/admin/scrapers/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Admin-Key": adminKey,
    },
  });
}

/**
 * Trigger scraper for a single store.
 *
 * Maps to `POST /admin/scrapers/run/{store_slug}`.
 *
 * @param storeSlug - Store slug (e.g. "kaufland").
 * @param adminKey - Value for the `X-Admin-Key` header.
 * @returns Confirmation of dispatched scraper.
 */
export async function runStoreScraper(storeSlug: string, adminKey: string): Promise<ScraperRunResponse> {
  return apiFetch<ScraperRunResponse>(`/admin/scrapers/run/${storeSlug}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json",
      "X-Admin-Key": adminKey,
    },
  });
}

/**
 * Request cancellation of the running scraper for a store.
 *
 * Maps to `DELETE /admin/scrapers/run/{store_slug}`.
 *
 * @param storeSlug - Store slug (e.g. "kaufland").
 * @param adminKey - Value for the `X-Admin-Key` header.
 */
export async function cancelStoreScraper(storeSlug: string, adminKey: string): Promise<{ store_slug: string; message: string }> {
  return apiFetch<{ store_slug: string; message: string }>(`/admin/scrapers/run/${storeSlug}`, {
    method: "DELETE",
    headers: {
      Accept: "application/json",
      "X-Admin-Key": adminKey,
    },
  });
}

/** Status of the most recent scrape run for a store. */
export interface ScrapeRunStatus {
  store_slug: string;
  status: "idle" | "running" | "completed" | "failed" | "cancelled";
  items_found: number | null;
  error_msg: string | null;
  started_at: string | null;
  finished_at: string | null;
}

/**
 * Fetch the most recent scrape run status for a single store.
 *
 * Maps to `GET /admin/scrapers/status/{store_slug}`.
 *
 * @param storeSlug - Store slug (e.g. "kaufland").
 * @param adminKey - Value for the `X-Admin-Key` header.
 * @returns {@link ScrapeRunStatus} for the store, with status "idle" if never scraped.
 * @throws `Error` with "Store not found" on 404.
 */
export async function getScraperStatus(storeSlug: string, adminKey: string): Promise<ScrapeRunStatus> {
  return apiFetch<ScrapeRunStatus>(`/admin/scrapers/status/${storeSlug}`, {
    headers: { "X-Admin-Key": adminKey, Accept: "application/json" },
  });
}

/**
 * Fetch the most recent scrape run status for all active stores.
 *
 * Maps to `GET /admin/scrapers/status`.
 *
 * @param adminKey - Value for the `X-Admin-Key` header.
 * @returns Array of {@link ScrapeRunStatus}, one entry per active store.
 */
export async function getAllScraperStatuses(adminKey: string): Promise<ScrapeRunStatus[]> {
  return apiFetch<ScrapeRunStatus[]>(`/admin/scrapers/status`, {
    headers: { "X-Admin-Key": adminKey, Accept: "application/json" },
  });
}

/** A product pending admin review. */
export interface PendingProduct {
  id: string;
  name: string;
  brand: string | null;
  barcode: string | null;
  created_at: string;
  matched_store_names: string[];
  latest_price: number | null;
  category: string | null;
  discount_percent: number | null;
}

export interface PaginatedPendingProducts {
  items: PendingProduct[];
  total: number;
  page: number;
  page_size: number;
}

export interface ProductActionResponse {
  id: string;
  status: string;
  message: string;
}

export async function listPendingProducts(
  adminKey: string,
  page = 1,
  pageSize = 50,
): Promise<PaginatedPendingProducts> {
  return apiFetch<PaginatedPendingProducts>(
    `/admin/products/pending?page=${page}&page_size=${pageSize}`,
    { headers: { "X-Admin-Key": adminKey, Accept: "application/json" } },
  );
}

export async function approveProduct(id: string, adminKey: string): Promise<ProductActionResponse> {
  return apiFetch<ProductActionResponse>(`/admin/products/${id}/approve`, {
    method: "PATCH",
    headers: { "X-Admin-Key": adminKey, Accept: "application/json" },
  });
}

export async function rejectProduct(id: string, adminKey: string): Promise<ProductActionResponse> {
  return apiFetch<ProductActionResponse>(`/admin/products/${id}/reject`, {
    method: "PATCH",
    headers: { "X-Admin-Key": adminKey, Accept: "application/json" },
  });
}

export async function updateProduct(
  id: string,
  adminKey: string,
  updates: { name?: string; brand?: string; barcode?: string },
): Promise<ProductActionResponse> {
  return apiFetch<ProductActionResponse>(`/admin/products/${id}`, {
    method: "PATCH",
    headers: {
      "X-Admin-Key": adminKey,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify(updates),
  });
}

export async function deleteProduct(id: string, adminKey: string): Promise<ProductActionResponse> {
  return apiFetch<ProductActionResponse>(`/admin/products/${id}`, {
    method: "DELETE",
    headers: { "X-Admin-Key": adminKey, Accept: "application/json" },
  });
}

export interface BatchDeleteResponse {
  deleted: number;
  not_found: string[];
}

export async function batchDeleteProducts(
  ids: string[],
  adminKey: string,
): Promise<BatchDeleteResponse> {
  return apiFetch<BatchDeleteResponse>("/admin/products", {
    method: "DELETE",
    headers: {
      "X-Admin-Key": adminKey,
      "Content-Type": "application/json",
      Accept: "application/json",
    },
    body: JSON.stringify({ ids }),
  });
}

/** An active catalogue product returned by the admin catalogue endpoint. */
export interface ActiveProduct {
  id: string;
  name: string;
  brand: string | null;
  barcode: string | null;
  slug: string;
  created_at: string;
  matched_store_names: string[];
  latest_price: number | null;
  category: string | null;
  discount_percent: number | null;
}

export interface PaginatedActiveProducts {
  items: ActiveProduct[];
  total: number;
  page: number;
  page_size: number;
}

export async function listActiveProducts(
  adminKey: string,
  page = 1,
  pageSize = 50,
  q?: string,
): Promise<PaginatedActiveProducts> {
  const qs = buildQuery({ page, page_size: pageSize, q });
  return apiFetch<PaginatedActiveProducts>(
    `/admin/products${qs}`,
    { headers: { "X-Admin-Key": adminKey, Accept: "application/json" } },
  );
}

// ---------------------------------------------------------------------------
// Store and brochure endpoints
// ---------------------------------------------------------------------------

/**
 * Fetch all active tracked stores.
 *
 * Maps to `GET /stores`.
 *
 * @returns Array of {@link Store} objects.
 */
export async function listStores(): Promise<Store[]> {
  return apiFetch<Store[]>("/stores");
}

/**
 * Fetch all brochures for a specific store, most recent first.
 *
 * Maps to `GET /stores/{store_id}/brochures`.
 *
 * @param storeId - UUID of the store.
 * @returns Array of {@link Brochure} objects.
 * @throws `Error` with "Store not found" on 404.
 */
export async function listStoreBrochures(storeId: string): Promise<Brochure[]> {
  return apiFetch<Brochure[]>(`/stores/${storeId}/brochures`);
}

/**
 * Fetch the current active brochure for a store.
 *
 * Maps to `GET /stores/{store_id}/brochures/current`.
 *
 * @param storeId - UUID of the store.
 * @returns The current {@link Brochure} for the store.
 * @throws `Error` with "Store not found" or "No current brochure" on 404.
 */
export async function getCurrentBrochure(storeId: string): Promise<Brochure> {
  return apiFetch<Brochure>(`/stores/${storeId}/brochures/current`);
}

/**
 * Fetch all currently active brochures across all stores.
 *
 * Maps to `GET /stores/brochures/active`.
 *
 * @returns Array of {@link Brochure} objects (one per store with active brochure).
 */
export async function listActiveBrochures(): Promise<Brochure[]> {
  return apiFetch<Brochure[]>("/stores/brochures/active");
}

// ---------------------------------------------------------------------------
// Deals endpoint
// ---------------------------------------------------------------------------

/** Parameters for fetching the best deals list. */
export interface FetchDealsParams {
  /** Maximum number of deal rows to return (1-200, default 50). */
  limit?: number;
  /** Filter deals to a single top-level category. */
  top_category?: string;
}

/**
 * Fetch products currently on sale, ordered by discount percentage descending.
 *
 * Maps to `GET /browse/deals`.
 *
 * @param params - Optional limit and top_category filter.
 * @returns {@link DealsResponse} with deal items and total matching count.
 */
export async function fetchDeals(params: FetchDealsParams = {}): Promise<DealsResponse> {
  const qs = buildQuery(params as Record<string, string | number | undefined>);
  return apiFetch<DealsResponse>(`/browse/deals${qs}`);
}

// Re-export deal types so consumers can import from api.ts if preferred
export type { DealItem, DealsResponse };

// ---------------------------------------------------------------------------
// Scraper queue + logs
// ---------------------------------------------------------------------------

export interface QueueStatus {
  pending: number;
  active: string[];   // store slugs currently running
  queued: string[];   // store slugs waiting in queue (not yet started)
}

export interface LogEntry {
  ts: string;
  store: string;
  level: string;
  msg: string;
}

export async function getScraperQueue(adminKey: string): Promise<QueueStatus> {
  return apiFetch<QueueStatus>("/admin/scrapers/queue", {
    headers: { "X-Admin-Key": adminKey, Accept: "application/json" },
  });
}

export async function clearScraperQueue(adminKey: string): Promise<{ cleared: number }> {
  return apiFetch<{ cleared: number }>("/admin/scrapers/queue", {
    method: "DELETE",
    headers: { "X-Admin-Key": adminKey, Accept: "application/json" },
  });
}

export async function getScraperLogs(adminKey: string, limit = 100): Promise<LogEntry[]> {
  return apiFetch<LogEntry[]>(`/admin/scrapers/logs?limit=${limit}`, {
    headers: { "X-Admin-Key": adminKey, Accept: "application/json" },
  });
}
