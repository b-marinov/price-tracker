/**
 * Site-wide footer.
 *
 * Provides supplementary navigation links and copyright information.
 * Marked with `<footer>` and `role="contentinfo"` for WCAG landmark compliance.
 */
export function Footer() {
  const currentYear = new Date().getFullYear();

  return (
    <footer
      role="contentinfo"
      className="border-t bg-background pb-16 md:pb-0"
    >
      <div className="container py-8 md:py-10">
        <div className="grid gap-8 sm:grid-cols-2 md:grid-cols-3">
          {/* Brand */}
          <div>
            <p className="mb-2 font-semibold">Ценово сравнение</p>
            <p className="text-sm text-muted-foreground">
              Сравняване на цени от български хранителни вериги в реално
              време.
            </p>
          </div>

          {/* Navigation links */}
          <nav aria-label="Допълнителни връзки">
            <p className="mb-2 text-sm font-semibold">Навигация</p>
            <ul className="space-y-1 text-sm text-muted-foreground" role="list">
              <li>
                <a
                  href="/products"
                  className="transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  Продукти
                </a>
              </li>
              <li>
                <a
                  href="/compare"
                  className="transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  Сравни цени
                </a>
              </li>
              <li>
                <a
                  href="/categories"
                  className="transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  Категории
                </a>
              </li>
              <li>
                <a
                  href="/stores"
                  className="transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                >
                  Магазини
                </a>
              </li>
            </ul>
          </nav>

          {/* Stores */}
          <div>
            <p className="mb-2 text-sm font-semibold">Следени магазини</p>
            <ul className="space-y-1 text-sm text-muted-foreground" role="list">
              <li>Kaufland България</li>
              <li>Lidl България</li>
              <li>Billa България</li>
              <li>Fantastico</li>
            </ul>
          </div>
        </div>

        <div className="mt-8 border-t pt-6 text-center text-sm text-muted-foreground">
          <p>
            &copy; {currentYear} Ценово сравнение. Цените се актуализират
            ежедневно.
          </p>
        </div>
      </div>
    </footer>
  );
}
