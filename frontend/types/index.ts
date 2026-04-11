/**
 * Shared TypeScript types for the price-tracker frontend.
 *
 * These mirror the backend Pydantic schemas so that API responses can be
 * typed end-to-end without a code-generation step.
 */

// ---------------------------------------------------------------------------
// Core domain entities
// ---------------------------------------------------------------------------

/** A grocery store tracked by the platform. */
export interface Store {
  id: string;
  name: string;
  slug: string;
  website_url?: string | null;
  logo_url?: string | null;
  active: boolean;
}

/** A store brochure (PDF flyer) with validity period. */
export interface Brochure {
  id: string;
  store_id: string;
  store_name: string;
  store_slug: string;
  title: string;
  pdf_url: string;
  valid_from?: string | null;
  valid_to?: string | null;
  is_current: boolean;
  created_at: string;
}

/** A product category (may be nested). */
export interface Category {
  id: string;
  name: string;
  slug: string;
  parent_id?: string | null;
  children?: Category[];
}

/** A product in the catalogue. */
export interface Product {
  id: string;
  name: string;
  slug: string;
  brand?: string | null;
  category_id: string;
  image_url?: string | null;
  barcode?: string | null;
  status: "active" | "inactive" | "pending";
}

// ---------------------------------------------------------------------------
// Catalogue list / detail
// ---------------------------------------------------------------------------

/**
 * Product list item with price summary fields.
 * Returned by `GET /products` and `GET /products/search`.
 */
export interface ProductListItem extends Product {
  lowest_price?: number | null;
  /** Original (non-discounted) price, if a discount is active. */
  original_price?: number | null;
  /** Percentage discount (0-100), e.g. 49 means -49%. */
  discount_percent?: number | null;
  store_count: number;
  last_updated?: string | null;
}

/** Per-store price summary used inside ProductDetail. */
export interface StorePriceSummary {
  store_id: string;
  store_name: string;
  store_slug: string;
  price: number;
  currency: string;
  recorded_at: string;
}

/**
 * Full product detail with per-store prices.
 * Returned by `GET /products/{product_id}`.
 */
export interface ProductDetail extends ProductListItem {
  prices: StorePriceSummary[];
}

// ---------------------------------------------------------------------------
// Price comparison
// ---------------------------------------------------------------------------

/** Per-store comparison entry (cheapest first). */
export interface StoreComparison {
  store_id: string;
  store_name: string;
  store_slug: string;
  logo_url?: string | null;
  price: number;
  currency: string;
  unit?: string | null;
  last_scraped_at: string;
  source: string;
  price_diff_pct: number;
}

/**
 * Full comparison response for a single product.
 * Returned by `GET /products/{product_id}/compare`.
 */
export interface ComparisonResponse {
  product_id: string;
  product_name: string;
  product_slug: string;
  comparisons: StoreComparison[];
}

/** A single product match in a search-driven comparison. */
export interface SearchCompareItem {
  product_id: string;
  product_name: string;
  product_slug: string;
  brand?: string | null;
  cheapest_store_name: string;
  cheapest_store_slug: string;
  cheapest_price: number;
  currency: string;
  store_count: number;
}

/**
 * Search-driven price comparison response.
 * Returned by `GET /products/compare?q=…`.
 */
export interface SearchCompareResponse {
  query: string;
  results: SearchCompareItem[];
}

// ---------------------------------------------------------------------------
// Price history
// ---------------------------------------------------------------------------

/** A single (date, price) data point in a price history series. */
export interface PricePoint {
  date: string;
  price: number;
}

/** Price history series for one store. */
export interface StoreResult {
  store_id: string;
  store_name: string;
  data: PricePoint[];
}

/**
 * Price history response for a product.
 * Returned by `GET /products/{product_id}/history`.
 */
export interface PriceHistoryResponse {
  product_id: string;
  store_results: StoreResult[];
}

// ---------------------------------------------------------------------------
// Pagination wrapper
// ---------------------------------------------------------------------------

/**
 * Generic paginated response envelope used by list endpoints.
 *
 * @template T - The item type inside the `items` array.
 */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ---------------------------------------------------------------------------
// API error
// ---------------------------------------------------------------------------

/** Standard error shape returned by the FastAPI backend. */
export interface ApiError {
  detail: string;
}

// ---------------------------------------------------------------------------
// Browse (category hierarchy)
// ---------------------------------------------------------------------------

/** A brand entry within a product type in the browse hierarchy. */
export interface BrandEntry {
  brand: string | null;
  price_min: number;
  price_max: number;
  cheapest_store: string | null;
  max_discount: number | null;
  store_count: number;
}

/** A product type entry within a sub-category in the browse hierarchy. */
export interface ProductTypeEntry {
  product_type: string;
  price_min: number;
  price_max: number;
  brand_count: number;
  brands: BrandEntry[];
}

/** A sub-category entry within a top category in the browse hierarchy. */
export interface SubCategoryEntry {
  category: string;
  price_min: number;
  price_max: number;
  product_type_count: number;
  product_types: ProductTypeEntry[];
}

/** A top-level category entry in the browse hierarchy. */
export interface TopCategoryEntry {
  top_category: string;
  price_min: number;
  price_max: number;
  sub_category_count: number;
  sub_categories: SubCategoryEntry[];
}

/** Response from `GET /browse`. */
export interface BrowseResponse {
  top_categories: TopCategoryEntry[];
}

// ---------------------------------------------------------------------------
// Deals
// ---------------------------------------------------------------------------

/** A single deal item returned by `GET /browse/deals`. */
export interface DealItem {
  product_name: string;
  brand: string | null;
  store: string;
  price: number;
  original_price: number | null;
  discount_percent: number;
  top_category: string | null;
  category: string | null;
  image_url: string | null;
}

/** Response from `GET /browse/deals`. */
export interface DealsResponse {
  items: DealItem[];
  total: number;
}
