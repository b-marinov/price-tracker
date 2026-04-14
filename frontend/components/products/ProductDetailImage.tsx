"use client";

import { useState } from "react";
import { ImageIcon } from "lucide-react";
import { resolveImageUrl } from "@/lib/utils";

interface ProductDetailImageProps {
  imageUrl: string | null | undefined;
  productName: string;
}

/**
 * Client component for rendering a product image with graceful error fallback.
 * Used on the product detail page where the parent is a server component.
 */
export function ProductDetailImage({ imageUrl, productName }: ProductDetailImageProps) {
  const [imgError, setImgError] = useState(false);

  const resolvedUrl = resolveImageUrl(imageUrl);
  const showPlaceholder = !resolvedUrl || imgError;

  if (showPlaceholder) {
    return (
      <div
        className="bg-muted max-h-48 w-full flex items-center justify-center rounded-lg border aspect-[4/3]"
        aria-hidden="true"
      >
        <ImageIcon className="h-12 w-12 opacity-30 text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="max-h-48 w-full overflow-hidden rounded-lg border bg-muted">
      <img
        src={resolvedUrl!}
        alt={productName}
        loading="lazy"
        className="max-h-48 w-full object-contain"
        onError={() => setImgError(true)}
      />
    </div>
  );
}
