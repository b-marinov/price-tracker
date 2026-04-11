import type { Metadata } from "next";
import { DealsPage } from "@/components/deals/DealsPage";

export const metadata: Metadata = {
  title: "Най-добри намаления",
  description: "Топ намаления по всички магазини, сортирани по процент отстъпка.",
};

export default function DealsRoute() {
  return <DealsPage />;
}
