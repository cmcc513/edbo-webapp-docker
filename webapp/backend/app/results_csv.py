"""CSV round-trip for the current run-list (export template -> upload results).

The batch CSV has one column per reaction component plus the target column
(e.g. ``yield``). Yields may be blank when the file is downloaded; after the
experiments are run the same file is uploaded back. Each row is validated and
then either updates the experiment with identical component values in the
current round or is appended as a new completed experiment.

This module holds only parsing/validation logic (no DB, no optimizer) so it can
be checked in isolation; the router layer applies the resulting plan.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

#: Target-column names accepted on upload. Component columns are matched against
#: the component name (case-insensitive, surrounding spaces ignored).
TARGET_ALIASES = (
    "yield", "yld", "产率", "收率", "yield(%)", "yield (%)",
    "目标", "目标值", "target",
)


class CsvFormatError(Exception):
    """Raised when the uploaded file is not a usable results CSV."""


@dataclass
class RowPlan:
    row: int                       # 1-based data row (the header is row 1)
    action: str                    # import | skip | reject
    reason: str | None = None
    components: dict[str, str] | None = None
    domain_index: int | None = None
    observed_value: float | None = None
    existing: bool = False         # condition is already in the current round
    warnings: list[str] = field(default_factory=list)


def read_csv_bytes(content: bytes) -> pd.DataFrame:
    """Parse CSV bytes, tolerating the encodings Excel commonly writes."""
    if not content.strip():
        raise CsvFormatError("CSV 文件为空。")
    last: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return pd.read_csv(
                io.BytesIO(content), encoding=encoding,
                dtype=str, keep_default_na=False,
            )
        except UnicodeDecodeError as exc:
            last = exc
        except pd.errors.EmptyDataError as exc:
            raise CsvFormatError("CSV 文件没有可读取的内容。") from exc
        except pd.errors.ParserError as exc:
            raise CsvFormatError(f"CSV 解析失败：{exc}") from exc
    raise CsvFormatError(f"CSV 编码无法识别（已尝试 UTF-8 / GB18030）：{last}")


def _text(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, float) and math.isnan(raw):
        return ""
    return str(raw).strip()


def _column_key(name: Any) -> str:
    return str(name).strip().lower()


def resolve_columns(
    df: pd.DataFrame, component_keys: list[str], target: str
) -> tuple[dict[str, Any], Any]:
    """Map component names and the target name onto actual CSV columns."""
    known: dict[str, Any] = {}
    for col in df.columns:
        known.setdefault(_column_key(col), col)

    component_columns: dict[str, Any] = {}
    missing: list[str] = []
    for key in component_keys:
        col = known.get(_column_key(key))
        if col is None:
            missing.append(key)
        else:
            component_columns[key] = col
    if missing:
        expected = list(component_keys) + [target]
        raise CsvFormatError(
            "CSV 缺少反应组分列：" + "、".join(missing)
            + "。需要的列为：" + "、".join(expected) + "。"
        )

    target_column = None
    for alias in (target, *TARGET_ALIASES):
        col = known.get(_column_key(alias))
        if col is not None:
            target_column = col
            break
    if target_column is None:
        raise CsvFormatError(f"CSV 缺少目标列（{target} / yield / 产率）。")
    return component_columns, target_column


def parse_target(text: str) -> tuple[float | None, str | None]:
    """Parse the yield cell. Returns (value, error) where error is None/blank/invalid."""
    value_text = text.strip()
    if value_text == "":
        return None, "blank"
    if value_text.endswith("%"):
        value_text = value_text[:-1].strip()
    try:
        value = float(value_text)
    except ValueError:
        return None, "invalid"
    if not math.isfinite(value):
        return None, "invalid"
    return value, None


def coerce_value(text: str) -> Any:
    """Turn a CSV string into the int/float form used by the reaction space."""
    stripped = text.strip()
    try:
        number = float(stripped)
    except ValueError:
        return stripped
    if not math.isfinite(number):
        return stripped
    return int(number) if number.is_integer() else number


def make_resolver(
    resolve_canonical: Callable[[dict[str, Any]], int | None]
) -> Callable[[dict[str, str]], int | None]:
    """Build a row resolver that also accepts Excel's numeric formatting.

    A component read back as text ("40" or "40.0") must still match a numeric
    space value (40), so the raw values are tried first and the numeric
    coercion second.
    """

    def resolve(components: dict[str, str]) -> int | None:
        index = resolve_canonical(components)
        if index is not None:
            return index
        coerced = {k: coerce_value(v) for k, v in components.items()}
        if coerced != components:
            return resolve_canonical(coerced)
        return None

    return resolve


def plan_rows(
    df: pd.DataFrame,
    component_columns: dict[str, Any],
    target_column: Any,
    resolve: Callable[[dict[str, str]], int | None],
    existing_indices: set[int],
) -> list[RowPlan]:
    """Validate every data row and decide whether it imports, skips or fails."""
    plans: list[RowPlan] = []
    imported_rows: dict[int, int] = {}  # domain_index -> first importing row

    for position, (_, raw) in enumerate(df.iterrows()):
        row_number = position + 2  # header is row 1
        components = {k: _text(raw[col]) for k, col in component_columns.items()}

        if all(v == "" for v in components.values()):
            plans.append(RowPlan(row=row_number, action="skip",
                                 reason="空行，已忽略。"))
            continue
        blank = [k for k, v in components.items() if v == ""]
        if blank:
            plans.append(RowPlan(
                row=row_number, action="reject", components=components,
                reason="缺少组分取值：" + "、".join(blank) + "。",
            ))
            continue

        domain_index = resolve(components)
        if domain_index is None:
            plans.append(RowPlan(
                row=row_number, action="reject", components=components,
                reason="反应条件不在反应空间内（组分取值不存在或组合非法）。",
            ))
            continue

        raw_yield = _text(raw[target_column])
        observed_value, error = parse_target(raw_yield)
        if error == "blank":
            plans.append(RowPlan(
                row=row_number, action="skip", components=components,
                domain_index=domain_index, reason="产率为空，未导入。",
            ))
            continue
        if error is not None:
            plans.append(RowPlan(
                row=row_number, action="reject", components=components,
                domain_index=domain_index,
                reason=f"产率不是有效数值：{raw_yield}。",
            ))
            continue

        if domain_index in imported_rows:
            plans.append(RowPlan(
                row=row_number, action="reject", components=components,
                domain_index=domain_index,
                reason=f"反应条件与第 {imported_rows[domain_index]} 行重复。",
            ))
            continue
        imported_rows[domain_index] = row_number

        plan = RowPlan(
            row=row_number, action="import", components=components,
            domain_index=domain_index, observed_value=observed_value,
            existing=domain_index in existing_indices,
        )
        if observed_value < 0:
            plan.warnings.append("产率为负值，请确认。")
        plans.append(plan)

    return plans
