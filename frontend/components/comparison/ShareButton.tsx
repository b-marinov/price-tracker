"use client";

import { useState } from "react";
import { Share2, Check } from "lucide-react";
import { Button } from "@/components/ui/button";

export function ShareButton() {
  const [copied, setCopied] = useState(false);

  const handleShare = async () => {
    const url = window.location.href;
    try {
      if (navigator.share) {
        await navigator.share({ url });
      } else {
        await navigator.clipboard.writeText(url);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }
    } catch {
      // User cancelled share or clipboard unavailable
    }
  };

  return (
    <Button variant="outline" size="sm" onClick={handleShare} aria-live="polite">
      {copied ? (
        <>
          <Check className="mr-2 h-4 w-4 text-green-600" aria-hidden="true" />
          Копирано!
        </>
      ) : (
        <>
          <Share2 className="mr-2 h-4 w-4" aria-hidden="true" />
          Сподели
        </>
      )}
    </Button>
  );
}
