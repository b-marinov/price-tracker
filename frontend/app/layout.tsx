import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";

import "./globals.css";
import { Header } from "@/components/layout/Header";
import { Nav } from "@/components/layout/Nav";
import { Footer } from "@/components/layout/Footer";

const inter = Inter({ subsets: ["latin", "latin-ext"] });

export const metadata: Metadata = {
  title: {
    default: "Ценово сравнение",
    template: "%s | Ценово сравнение",
  },
  description:
    "Сравнете цените на хранителни продукти в български магазини — Kaufland, Lidl, Billa, Fantastico.",
  metadataBase: new URL(
    process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000"
  ),
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

/**
 * Root layout for the price-tracker application.
 *
 * Applies the global font, skip-nav link, persistent header/footer and the
 * responsive navigation shell that switches between a mobile bottom-bar and a
 * desktop sidebar.
 */
export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="bg" suppressHydrationWarning>
      <body className={inter.className}>
        {/* Skip-nav: WCAG 2.4.1 — visible on focus for keyboard users */}
        <a href="#main-content" className="skip-nav">
          Прескочи към съдържанието
        </a>

        <div className="flex min-h-screen flex-col">
          <Header />

          {/*
           * Layout grid:
           * - Mobile  (<md): single column, full-width content + bottom-nav
           * - Desktop (≥md): sidebar-nav on the left + main content area
           */}
          <div className="flex flex-1">
            {/* Desktop sidebar nav — hidden on mobile */}
            <Nav variant="sidebar" />

            {/* Main content area */}
            <main
              id="main-content"
              tabIndex={-1}
              className="flex-1 focus-visible:outline-none"
            >
              <div className="container py-6 md:py-8">{children}</div>
            </main>
          </div>

          <Footer />
        </div>

        {/* Mobile bottom-nav — hidden on desktop */}
        <Nav variant="bottom" />
      </body>
    </html>
  );
}
