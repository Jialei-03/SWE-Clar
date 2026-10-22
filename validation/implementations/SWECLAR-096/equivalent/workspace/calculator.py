"""Backend calculations for the area calculator.

The browser-facing service deliberately keeps the calculation here.  The
numbers are converted to :class:`~decimal.Decimal` values before arithmetic so
that the documented half-up rounding rule does not depend on binary floating
point rounding.
"""

from decimal import Decimal, DecimalException, ROUND_HALF_UP, localcontext
import math


FIELDS = ("land_area_sqft", "site_area_sqft", "plot_ratio")
_AREA_CONVERSION = Decimal("0.092903")
_TWO_DECIMAL_PLACES = Decimal("0.01")


def _invalid_input() -> ValueError:
    return ValueError("invalid_input")


def _to_decimal(value: object) -> Decimal:
    """Validate a JSON-style number and return its exact decimal spelling.

    ``bool`` is an ``int`` subclass in Python, so it has to be rejected before
    the normal integer/float check.  Using ``str`` for floats gives the decimal
    representation supplied by a JSON client rather than introducing the
    binary representation of the float into the benchmark calculation.
    """

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid_input()

    if isinstance(value, float):
        if not math.isfinite(value):
            raise _invalid_input()
        decimal_value = Decimal(str(value))
    else:
        # Decimal(int) is exact and does not use math.isfinite(), which can
        # overflow while coercing a very large Python integer to a float.
        decimal_value = Decimal(value)

    if not decimal_value.is_finite() or decimal_value < 0:
        raise _invalid_input()
    return decimal_value


def _precision_for(numbers: tuple[Decimal, Decimal, Decimal]) -> int:
    """Choose enough decimal context precision for the requested operations.

    Normal form values need only a small context, but JSON/Python integers and
    finite scientific-notation floats can have many digits.  A dynamic context
    avoids rounding an intermediate value merely because the process-wide
    Decimal precision is small.  The final conversion to a JSON float still
    rejects an output that cannot be represented finitely.
    """

    land, site, ratio = numbers
    values = (land, site, ratio)

    # The coefficient lengths cover significant digits.  The adjusted
    # exponents cover values such as Decimal("1e308") whose coefficient is only
    # one digit but whose quantized form has many integer places.
    coefficient_budget = sum(len(value.as_tuple().digits) for value in values) + 32
    adjusted_values = [value.adjusted() if not value.is_zero() else 0 for value in values]

    # The largest possible adjusted exponent of the addition and multiplication
    # intermediates, with a little room for carries and the two decimal places
    # added by quantize().
    sum_adjusted = max(adjusted_values[0], adjusted_values[1]) + 2
    gross_adjusted = adjusted_values[0] + adjusted_values[2] + 2
    converted_adjusted = max(adjusted_values[0], adjusted_values[1]) + 2
    integer_place_budget = max(1, sum_adjusted, gross_adjusted, converted_adjusted) + 8

    return max(64, coefficient_budget, integer_place_budget)


def _rounded_float(value: Decimal) -> float:
    """Round a Decimal half-up to two places and require a finite JSON number."""

    rounded = value.quantize(_TWO_DECIMAL_PLACES, rounding=ROUND_HALF_UP)
    number = float(rounded)
    if not math.isfinite(number):
        raise _invalid_input()
    # Avoid exposing negative zero for a mathematically zero result.
    return 0.0 if rounded.is_zero() else number


def calculate(values: dict) -> dict:
    """Calculate the area summary for one request.

    A fresh result tree is returned for every call.  Only the three documented
    fields are read from ``values``; no input object is modified.

    Raises:
        ValueError: with ``"invalid_input"`` for missing, invalid, non-finite,
            or unrepresentable input/output values.
    """

    if not isinstance(values, dict):
        raise _invalid_input()

    try:
        if any(field not in values for field in FIELDS):
            raise _invalid_input()

        numbers = tuple(_to_decimal(values[field]) for field in FIELDS)
        land_area, site_area, plot_ratio = numbers

        with localcontext() as context:
            context.prec = _precision_for(numbers)
            converted = {
                "land_area_sqm": _rounded_float(land_area * _AREA_CONVERSION),
                "site_area_sqm": _rounded_float(site_area * _AREA_CONVERSION),
            }
            gross_floor_area = _rounded_float(land_area * plot_ratio + site_area * plot_ratio)

        result = {"gross_floor_area_sqft": gross_floor_area}
        # Rebuild every mapping rather than returning a reference to a caller's
        # mapping.  The values are JSON-compatible primitive numbers.
        inputs = {field: values[field] for field in FIELDS}
        summary = {**converted, **result}
        return {
            "inputs": inputs,
            "converted": converted,
            "result": result,
            "summary": summary,
        }
    except (DecimalException, OverflowError, ValueError):
        # Keep the public validation error stable even when Decimal reports an
        # invalid operation or float conversion overflow.
        raise _invalid_input() from None
