import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge Tailwind CSS class names, resolving conflicts intelligently.
 *
 * Combines `clsx` (conditional classes) with `tailwind-merge` (deduplication).
 *
 * @param inputs - Class values to merge (strings, objects, arrays, etc.)
 * @returns Merged class string.
 *
 * @example
 * cn("px-4 py-2", isActive && "bg-primary", "px-6")
 * // => "py-2 bg-primary px-6" (px-4 is overridden by px-6)
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Format a price value with the correct currency symbol.
 *
 * @param price - Numeric price value.
 * @param currency - ISO 4217 currency code (default "EUR").
 * @returns Formatted string, e.g. "2,49 €".
 */
export function formatPrice(price: number, currency = "EUR"): string {
  return new Intl.NumberFormat("bg-BG", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
  }).format(price);
}

/**
 * Format an ISO date string into a human-readable Bulgarian locale date.
 *
 * @param isoDate - ISO 8601 date string.
 * @returns Formatted date string, e.g. "6 April 2026".
 */
export function formatDate(isoDate: string): string {
  return new Intl.DateTimeFormat("bg-BG", {
    year: "numeric",
    month: "long",
    day: "numeric",
  }).format(new Date(isoDate));
}
