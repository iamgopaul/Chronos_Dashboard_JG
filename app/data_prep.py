"""Load CSV and build a clean univariate or panel series for Chronos."""

from __future__ import annotations

import io
import warnings
from typing import Any, Optional

import numpy as np
import pandas as pd


def parse_datetime_column(series: pd.Series) -> pd.Series:
    """
    Parse date columns from CSV (e.g. WRDS datadate as 1/31/2010).
    Uses format='mixed' (pandas 2+) so mixed strings do not trigger inference warnings.
    """
    s = series
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce")
    try:
        return pd.to_datetime(s, errors="coerce", format="mixed")
    except (ValueError, TypeError):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return pd.to_datetime(s, errors="coerce")


def time_bounds_for_column(df: pd.DataFrame, time_col: str) -> Optional[dict[str, Any]]:
    """Min/max calendar dates for a column, or None if nothing parses."""
    if time_col not in df.columns:
        return None
    t = parse_datetime_column(df[time_col]).dropna()
    if t.empty:
        return None
    min_dt = t.min().normalize()
    max_dt = t.max().normalize()
    return {
        "time_col": time_col,
        "min_date": min_dt.strftime("%Y-%m-%d"),
        "max_date": max_dt.strftime("%Y-%m-%d"),
        "n_valid_dates": int(len(t)),
    }


def read_csv_bytes(data: bytes, encoding: str = "utf-8") -> pd.DataFrame:
    # Large WRDS exports: avoid mixed-type column inference splitting rows incorrectly
    return pd.read_csv(io.BytesIO(data), encoding=encoding, low_memory=False)


def filter_raw_dataframe(
    df: pd.DataFrame,
    *,
    time_col: str,
    date_start: Optional[str] = None,
    date_end: Optional[str] = None,
    category_col: Optional[str] = None,
    category_values: Optional[list[str]] = None,
    id_col: Optional[str] = None,
    item_ids_allowlist: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    Subset raw CSV rows before prepare_series.
    Date bounds are inclusive on both ends (calendar day).
    """
    out = df.copy()
    if time_col not in out.columns:
        raise ValueError(f"Missing time column: {time_col}")

    t = parse_datetime_column(out[time_col])
    if date_start:
        ds = pd.Timestamp(date_start).normalize()
        out = out.loc[t >= ds]
        t = parse_datetime_column(out[time_col])
    if date_end:
        de = pd.Timestamp(date_end).normalize() + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
        out = out.loc[t <= de]
    if category_col and category_values:
        if category_col not in out.columns:
            raise ValueError(f"Missing category column: {category_col}")
        vals = {str(v).strip() for v in category_values if str(v).strip()}
        if vals:
            out = out[out[category_col].astype(str).isin(vals)]
    if id_col and item_ids_allowlist:
        if id_col not in out.columns:
            raise ValueError(f"Missing id column: {id_col}")
        allow = {str(x).strip() for x in item_ids_allowlist if str(x).strip()}
        if allow:
            out = out[out[id_col].astype(str).isin(allow)]
    return out.reset_index(drop=True)


def prepare_series(
    df: pd.DataFrame,
    time_col: str,
    target_col: str,
    id_col: Optional[str] = None,
    freq: Optional[str] = None,
    winsorize_pct: Optional[tuple[float, float]] = None,
) -> pd.DataFrame:
    """
    Returns long dataframe: item_id, timestamp, target (sorted, regularized).
    If id_col is None, uses a single series id 'series'.
    """
    use = df[[time_col, target_col]].copy()
    if id_col and id_col in df.columns:
        use[id_col] = df[id_col].astype(str)
    else:
        use["_item"] = "series"
        id_col = "_item"

    use[time_col] = parse_datetime_column(use[time_col])
    n_before = len(use)
    use[target_col] = pd.to_numeric(use[target_col], errors="coerce")
    n_numeric = use[target_col].notna().sum()
    use = use.dropna(subset=[time_col, target_col])

    if use.empty:
        hint = ""
        if n_numeric == 0 and n_before > 0:
            hint = (
                f" Target column {target_col!r} has no numeric values after conversion. "
                "On WRDS/Compustat, pick a numeric ratio (e.g. ROA from niq/atq), not status codes like "
                "'costat' (active/inactive letters)."
            )
        elif n_before > 0:
            hint = (
                f" Only {n_numeric}/{n_before} rows had a numeric {target_col!r}; "
                f"or dates in {time_col!r} did not parse. Check column types."
            )
        raise ValueError(
            "No valid rows after parsing time and numeric target." + hint
        )

    if winsorize_pct:
        lo, hi = winsorize_pct
        lo_v = use[target_col].quantile(lo)
        hi_v = use[target_col].quantile(hi)
        use[target_col] = use[target_col].clip(lo_v, hi_v)

    parts = []
    for item, g in use.groupby(id_col, sort=False):
        g = g.sort_values(time_col)
        g = g.drop_duplicates(subset=[time_col], keep="last")
        if freq:
            g = g.set_index(time_col)
            g = g[[target_col]].resample(freq).last().dropna(how="all")
            g = g.reset_index()
            g.columns = ["timestamp", "target"]
        else:
            g = g.rename(columns={time_col: "timestamp", target_col: "target"})
        g["item_id"] = str(item)
        if not g.empty:
            parts.append(g[["item_id", "timestamp", "target"]])

    if not parts:
        raise ValueError(
            "No series could be built after grouping/resampling. "
            "If this is panel data (many firms), set Series ID to gvkey (or similar). "
            "If using frequency (QE), ensure datadate parses as dates."
        )

    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(["item_id", "timestamp"])
    return out


def train_test_split_last(
    series: np.ndarray,
    test_horizon: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Last `test_horizon` points are test; rest is train context."""
    if test_horizon <= 0 or len(series) <= test_horizon:
        raise ValueError("Series too short for requested test horizon.")
    train = series[:-test_horizon].copy()
    test = series[-test_horizon:].copy()
    return train, test
