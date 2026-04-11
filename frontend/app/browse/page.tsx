import type { Metadata } from "next";

import { BrowsePage } from "@/components/browse/BrowsePage";

export const metadata: Metadata = {
  title: "Разгледай по категория",
  description:
    "Разгледайте хранителни продукти по категория с ценови диапазони и марки.",
};

/**
 * Server wrapper for the browse page.
 *
 * Renders the client-side {@link BrowsePage} component which fetches the
 * `/browse` endpoint on mount and displays the category hierarchy.
 */
export default function BrowseRoute() {
  return <BrowsePage />;
}
