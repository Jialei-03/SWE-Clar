"""PDF report generation for the area calculator."""

from io import BytesIO

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from calculator import calculate


def _original_number(value: object) -> str:
    """Render an already validated input without changing its displayed value."""

    # repr is unambiguous for floats (including scientific notation) and str is
    # the natural representation for JSON integers.
    return repr(value) if isinstance(value, float) else str(value)


def _amount(value: float) -> str:
    """Render a backend-rounded amount with the documented two places."""

    return f"{value:.2f}"


def report_pdf(values: dict) -> bytes:
    """Return a valid PDF containing the calculation for ``values``.

    Validation and all arithmetic are delegated to ``calculate`` so a report
    cannot contain values different from the calculation endpoint.  The
    returned object is the PDF byte stream itself, not a JSON manifest.
    """

    calculated = calculate(values)
    inputs = calculated["inputs"]
    converted = calculated["converted"]
    result = calculated["result"]

    output = BytesIO()
    # Uncompressed content keeps the small report straightforward to inspect
    # while remaining a normal, valid PDF for browser/PDF-reader downloads.
    document = canvas.Canvas(output, pagesize=letter, pageCompression=0)
    document.setTitle("Area calculation report")

    _, height = letter
    left = 54
    y = height - 54
    line_height = 20

    lines = [
        ("Area calculation report", True),
        ("", False),
        ("Original inputs", True),
        (
            f"Land area (square feet): {_original_number(inputs['land_area_sqft'])}",
            False,
        ),
        (
            f"Site area (square feet): {_original_number(inputs['site_area_sqft'])}",
            False,
        ),
        (f"Plot ratio: {_original_number(inputs['plot_ratio'])}", False),
        ("", False),
        ("Calculated values", True),
        (f"Land area (square metres): {_amount(converted['land_area_sqm'])}", False),
        (f"Site area (square metres): {_amount(converted['site_area_sqm'])}", False),
        (
            f"Gross floor area (square feet): {_amount(result['gross_floor_area_sqft'])}",
            False,
        ),
    ]

    for text, heading in lines:
        if heading:
            document.setFont("Helvetica-Bold", 13)
        else:
            document.setFont("Helvetica", 11)
        document.drawString(left, y, text)
        y -= line_height

    document.showPage()
    document.save()
    return output.getvalue()
