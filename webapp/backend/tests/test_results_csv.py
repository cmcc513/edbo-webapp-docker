"""Tests for the batch results CSV parser (no HTTP / optimizer required)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app.results_csv import (  # noqa: E402
    CsvFormatError, make_resolver, parse_target, plan_rows, read_csv_bytes,
    resolve_columns,
)

SPACE = {
    ("DBU", "THF", 20): 0,
    ("MTBD", "DMSO", 40): 1,
    ("K2CO3", "Toluene", 30): 2,
}
KEYS = ["base", "solvent", "temperature"]


def _resolve(components):
    temperature = float(components["temperature"])
    return SPACE.get((
        str(components["base"]),
        str(components["solvent"]),
        int(temperature) if temperature.is_integer() else temperature,
    ))


def _plans(csv_text: str, existing=None, encoding="utf-8"):
    df = read_csv_bytes(csv_text.encode(encoding))
    components, target = resolve_columns(df, KEYS, "yield")
    return plan_rows(df, components, target, make_resolver(_resolve), existing or set())


def test_download_roundtrip_with_blank_yields_is_skipped():
    plans = _plans("base,solvent,temperature,yield\nDBU,THF,20,\nMTBD,DMSO,40,\n")
    assert [p.action for p in plans] == ["skip", "skip"]


def test_update_add_and_invalid_rows():
    plans = _plans(
        "base,solvent,temperature,yield\n"
        "DBU,THF,20.0,60\n"        # update (numeric text still matches)
        "MTBD,DMSO,40,35\n"        # update existing (imported)
        "MTBD,DMSO,40,99\n"        # duplicate condition
        "K2CO3,Toluene,30,77\n"    # add
        "DBU,THF,999,50\n"         # not in the reaction space
        "DBU,THF,20,abc\n"         # invalid yield
        ",,,\n"                    # empty line
    , existing={1})
    assert [(p.action, p.domain_index, p.observed_value) for p in plans] == [
        ("import", 0, 60.0),
        ("import", 1, 35.0),
        ("reject", 1, None),
        ("import", 2, 77.0),
        ("reject", None, None),
        ("reject", 0, None),
        ("skip", None, None),
    ]
    assert plans[1].existing is True
    assert plans[0].existing is False
    assert "重复" in plans[2].reason
    assert "反应空间" in plans[4].reason
    assert "数值" in plans[5].reason


def test_missing_component_column_is_reported():
    with pytest.raises(CsvFormatError, match="solvent"):
        resolve_columns(read_csv_bytes(b"base,temperature,yield\nDBU,20,5\n"),
                        KEYS, "yield")


def test_missing_target_column_is_reported():
    with pytest.raises(CsvFormatError, match="目标列"):
        resolve_columns(read_csv_bytes(b"base,solvent,temperature\nDBU,THF,20\n"),
                        KEYS, "yield")


def test_chinese_target_header_and_gbk_encoding():
    plans = _plans("base,solvent,temperature,产率\nDBU,THF,20,33\n",
                   encoding="gb18030")
    assert plans[0].action == "import" and plans[0].observed_value == 33.0


def test_empty_file_is_rejected():
    with pytest.raises(CsvFormatError):
        read_csv_bytes(b"   ")


@pytest.mark.parametrize("text,expected", [
    ("", (None, "blank")),
    ("  ", (None, "blank")),
    ("42.5", (42.5, None)),
    ("50%", (50.0, None)),
    ("abc", (None, "invalid")),
    ("nan", (None, "invalid")),
])
def test_parse_target(text, expected):
    assert parse_target(text) == expected
