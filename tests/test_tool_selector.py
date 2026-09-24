import pytest

from porter.tools.selector import select_qalculate_expression


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("what is 5+6?", "5+6"),
        ("10 * 4", "10 * 4"),
        ("1 gallon to cups", "1 gallon to cups"),
        ("2 miles in feet", "2 miles in feet"),
    ],
)
def test_selects_qalculate_requests(
    text: str,
    expected: str,
) -> None:
    assert select_qalculate_expression(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "explain ARP",
        "what day is it",
        "write me a poem",
    ],
)
def test_rejects_non_qalculate_requests(text: str) -> None:
    assert select_qalculate_expression(text) is None
