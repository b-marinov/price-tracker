"""Helper script to generate minimal PDF fixtures for testing.

Run once:  python tests/scrapers/fixtures/pdf/make_fixtures.py

Requires reportlab:  pip install reportlab
The generated PDFs are committed to the repo so CI does not need reportlab.
"""

from pathlib import Path

HERE = Path(__file__).parent


def make_text_pdf() -> None:
    """Create a simple text-based brochure PDF with known products."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError:
        print("reportlab not installed — skipping fixture generation")
        return

    path = HERE / "brochure_text.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4

    # Page 1 — products with a date range header
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 50, "СЕДМИЧНА БРОШУРА  01.04 - 07.04.2026")
    c.setFont("Helvetica", 10)

    products = [
        ("Мляко Верея 3.5%", "1.89 лв.", "1 л"),
        ("Сирене краве 400г", "3.49 лв.", "400 г"),
        ("Масло Рама 250г", "2.19 лв.", "250 г"),
        ("Кисело мляко Данон", "0.99 лв.", "400 г"),
        ("Хляб Добруджа", "1.29 лв.", "650 г"),
    ]

    y = height - 100
    for name, price, unit in products:
        c.drawString(50, y, name)
        c.drawString(250, y, unit)
        c.drawString(350, y, price)
        y -= 25

    c.showPage()

    # Page 2 — second set of products
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 50, "01.04 - 07.04.2026")
    c.setFont("Helvetica", 10)

    products2 = [
        ("Яйца М 10бр.", "2.49 лв.", "10 бр"),
        ("Портокали 1кг", "1.99 лв.", "1 кг"),
        ("Банани", "1.49 лв.", "1 кг"),
    ]

    y = height - 100
    for name, price, unit in products2:
        c.drawString(50, y, name)
        c.drawString(250, y, unit)
        c.drawString(350, y, price)
        y -= 25

    c.showPage()
    c.save()
    print(f"Created {path}")


if __name__ == "__main__":
    make_text_pdf()
