import { redirect } from "next/navigation";

/** Categories page removed — category filtering is available via chips on /products. */
export default function CategoriesPage() {
  redirect("/products");
}
