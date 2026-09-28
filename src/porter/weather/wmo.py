from __future__ import annotations


def condition_from_wmo_code(
    code: object,
    *,
    unknown: str | None = None,
    mixed: str = "Mixed conditions",
) -> str | None:
    if not isinstance(code, int | float):
        return unknown

    value = int(code)
    if value == 0:
        return "Clear"
    if value in {1, 2, 3}:
        return "Partly cloudy"
    if value in {45, 48}:
        return "Fog"
    if value in {51, 53, 55, 56, 57}:
        return "Drizzle"
    if value in {61, 63, 65, 66, 67}:
        return "Rain"
    if value in {71, 73, 75, 77}:
        return "Snow"
    if value in {80, 81, 82}:
        return "Rain showers"
    if value in {85, 86}:
        return "Snow showers"
    if value in {95, 96, 99}:
        return "Thunderstorms"
    return mixed
