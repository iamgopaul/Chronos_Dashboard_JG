"""Heuristic time / target / panel ID / freq for WRDS & Compustat-style CSVs."""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd


def time_column_try_order(df: pd.DataFrame, suggested_time: Optional[str]) -> list[str]:
    """Column names to try (in order) when finding a parsable calendar date column."""
    cols = list(df.columns)
    by_lower = {_norm(c): c for c in cols}
    ordered: list[str] = []
    seen: set[str] = set()

    def add(name: Optional[str]) -> None:
        if name and name in df.columns and name not in seen:
            seen.add(name)
            ordered.append(name)

    add(suggested_time)
    for key in ("datadate", "date", "prcdate", "mthcaldt"):
        add(by_lower.get(key))
    for c in cols:
        if "date" in _norm(c):
            add(c)
    return ordered


def _norm(name: str) -> str:
    return str(name).strip().lower()


# Prefer these as target when present and mostly numeric (ratios & flows).
_TARGET_PRIORITY = (
    "roa",
    "roe",
    "niq",
    "oibdpq",
    "saleq",
    "epspxq",
    "atq",
    "ceqq",
    "seqq",
    "ltq",
    "pstkq",
)

# Codes / identifiers — not forecast targets.
_TARGET_DENY = frozenset(
    {
        "costat",
        "curcd",
        "curcdq",
        "datafmt",
        "indfmt",
        "consol",
        "tic",
        "gvkey",
        "datadate",
        "date",
        "naics",
        "sic",
        "fqtr",
        "fyearq",
        "n_obs",
        "dlrsn",
        "exchg",
        "fic",
        "conm",
        "sector",
    }
)

_ID_KEYS = ("gvkey", "permno", "cusip", "iid")


def suggest_mapping(df: pd.DataFrame, *, sample_rows: int = 12_000) -> dict[str, Any]:
    """
    Return suggested time_col, target_col, id_col, freq for Chronos prep.
    Tuned for WRDS quarterly Compustat extracts (datadate, gvkey, ROA/ROE, QE).
    """
    cols = list(df.columns)
    by_lower = {_norm(c): c for c in cols}

    time_col: Optional[str] = None
    for key in ("datadate", "date", "prcdate", "mthcaldt"):
        if key in by_lower:
            time_col = by_lower[key]
            break
    if time_col is None:
        for c in cols:
            if "date" in _norm(c):
                time_col = c
                break

    id_col: Optional[str] = None
    for key in _ID_KEYS:
        if key in by_lower:
            id_col = by_lower[key]
            break

    n = min(sample_rows, len(df))
    head = df.iloc[:n] if n else df

    target_col: Optional[str] = None
    for key in _TARGET_PRIORITY:
        if key not in by_lower:
            continue
        c = by_lower[key]
        sub = pd.to_numeric(head[c], errors="coerce")
        if len(sub) and sub.notna().sum() >= max(5, int(0.15 * len(sub))):
            target_col = c
            break

    if target_col is None:
        best_ratio = 0.0
        best_c: Optional[str] = None
        for c in cols:
            ln = _norm(c)
            if ln in _TARGET_DENY or c == time_col or c == id_col:
                continue
            sub = pd.to_numeric(head[c], errors="coerce")
            if not len(sub):
                continue
            ratio = float(sub.notna().mean())
            if ratio > best_ratio:
                best_ratio = ratio
                best_c = c
        if best_ratio >= 0.25 and best_c:
            target_col = best_c

    freq = ""
    if "fqtr" in by_lower or "fyearq" in by_lower:
        freq = "QE"

    parts = []
    if time_col and target_col:
        parts.append(f"time={time_col}, target={target_col}")
    if id_col:
        parts.append(f"series={id_col}")
    if freq:
        parts.append(f"freq={freq}")
    note = "Suggested mapping for this file: " + "; ".join(parts) + "." if parts else ""

    return {
        "time_col": time_col,
        "target_col": target_col,
        "id_col": id_col,
        "freq": freq,
        "note": note,
    }
