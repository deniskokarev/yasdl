import pytest
from yasdl.sexp import dumps, parse, Sym


@pytest.mark.parametrize(
    "text",
    [
        "",
        " \t\n",
        "(",
        "(root",
        "(root ",
        "((root)",
        '"text',
        '"text\\',
        '(root "text',
        '(root "text\\',
        '(root "text"',
    ],
)
def test_truncated_input_raises_value_error(text: str) -> None:
    with pytest.raises(ValueError, match="unexpected end of input"):
        parse(text)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("atom", Sym("atom")),
        ('"quoted"', "quoted"),
        ("()", []),
        (
            '(root (at 1 2) "a \\"quote\\" and \\\\ slash")',
            [Sym("root"), [Sym("at"), Sym("1"), Sym("2")], 'a "quote" and \\ slash'],
        ),
    ],
)
def test_complete_input(text: str, expected: object) -> None:
    assert parse(text) == expected


def test_escaped_string_roundtrip() -> None:
    value = [Sym("property"), 'a "quote" and \\ slash', []]
    assert parse(dumps(value)) == value
