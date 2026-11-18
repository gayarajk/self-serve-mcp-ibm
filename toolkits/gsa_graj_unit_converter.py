from ibm_watsonx_orchestrate.agent_builder.tools import tool

# Conversion table: (from_unit, to_unit) -> callable(value) -> float
_CONVERSIONS: dict = {
    ("km", "miles"): lambda v: v * 0.621371,
    ("miles", "km"): lambda v: v * 1.60934,
    ("kg", "lbs"): lambda v: v * 2.20462,
    ("lbs", "kg"): lambda v: v * 0.453592,
    ("celsius", "fahrenheit"): lambda v: v * 9 / 5 + 32,
    ("fahrenheit", "celsius"): lambda v: (v - 32) * 5 / 9,
    ("liters", "gallons"): lambda v: v * 0.264172,
    ("gallons", "liters"): lambda v: v * 3.78541,
    ("meters", "feet"): lambda v: v * 3.28084,
    ("feet", "meters"): lambda v: v * 0.3048,
}


@tool()
def gsa_graj_unit_converter(value: float, from_unit: str, to_unit: str) -> str:
    """Convert a numeric value from one unit to another using local logic.

    Supported unit pairs (case-insensitive):
      km <-> miles, kg <-> lbs, celsius <-> fahrenheit,
      liters <-> gallons, meters <-> feet.

    Args:
        value (float): The numeric value to convert.
        from_unit (str): The source unit (e.g. 'km', 'kg', 'celsius').
        to_unit (str): The target unit (e.g. 'miles', 'lbs', 'fahrenheit').

    Returns:
        str: The converted value with source and target units clearly labelled.
    """
    key = (from_unit.lower().strip(), to_unit.lower().strip())

    if key not in _CONVERSIONS:
        supported = ", ".join(f"{f} -> {t}" for f, t in _CONVERSIONS)
        return (
            f"Unsupported conversion: '{from_unit}' to '{to_unit}'. "
            f"Supported pairs: {supported}."
        )

    result = _CONVERSIONS[key](value)
    return f"{value} {from_unit} = {result:.4f} {to_unit}"
