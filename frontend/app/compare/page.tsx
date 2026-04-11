import { redirect } from "next/navigation";

/** Global compare page removed — use the product detail page to compare prices across stores. */
export default function ComparePage() {
  redirect("/products");
}
