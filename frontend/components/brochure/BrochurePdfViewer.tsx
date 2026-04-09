"use client";

/**
 * BrochurePdfViewer — renders a store brochure PDF in-browser.
 *
 * Implementation note (flagged for Boris):
 * Currently uses an <iframe> embed which requires zero extra dependencies and
 * works across all modern browsers. The alternative is `react-pdf` (npm package
 * `react-pdf` / `pdfjs-dist`) which gives page-by-page rendering, text
 * selection, and better mobile zoom control, but adds ~600 kB to the bundle.
 * Recommendation: ship iframe now; evaluate react-pdf if users request it.
 *
 * Mobile: browsers support native pinch-to-zoom inside <iframe>.
 * The outer wrapper uses `overflow-hidden` with `touch-action: manipulation`
 * so the pinch gesture is passed through to the iframe content rather than
 * triggering the page-level zoom.
 */

interface BrochurePdfViewerProps {
  /** Public URL to the PDF file. */
  pdfUrl: string;
  /** Accessible title used as the iframe title attribute. */
  title: string;
  /** Store name for screen-reader context. */
  storeName: string;
}

/**
 * Responsive PDF brochure viewer using a native browser iframe.
 *
 * On desktop the PDF fills the full content width at a fixed 800 px height.
 * On mobile the aspect ratio is 4:3 to give comfortable reading without
 * excessive scrolling; native pinch-to-zoom works inside the iframe.
 */
export function BrochurePdfViewer({
  pdfUrl,
  title,
  storeName,
}: BrochurePdfViewerProps) {
  return (
    <div
      className="overflow-hidden rounded-lg border bg-muted"
      style={{ touchAction: "manipulation" }}
    >
      {/* Desktop: fixed height; mobile: 4:3 aspect ratio via padding trick */}
      <div className="relative w-full pb-[75%] sm:pb-0 sm:h-[800px]">
        <iframe
          src={`${pdfUrl}#toolbar=1&view=FitH`}
          title={`${storeName} — ${title}`}
          aria-label={`Брошура на ${storeName}: ${title}`}
          className="absolute inset-0 h-full w-full border-0"
          loading="lazy"
        />
      </div>

      {/* Fallback message shown only when JS parses but iframe cannot load */}
      <noscript>
        <p className="p-4 text-sm text-muted-foreground">
          Браузърът ви не поддържа вградено показване на PDF.{" "}
          <a
            href={pdfUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
          >
            Изтеглете брошурата
          </a>
          .
        </p>
      </noscript>

      {/* Download link always available */}
      <div className="border-t px-4 py-2 text-right">
        <a
          href={pdfUrl}
          target="_blank"
          rel="noopener noreferrer"
          download
          className="text-xs text-muted-foreground hover:text-foreground underline"
          aria-label={`Изтегли PDF брошура на ${storeName}`}
        >
          Изтегли PDF
        </a>
      </div>
    </div>
  );
}
