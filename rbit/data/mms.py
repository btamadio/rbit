"""Parse AEMO MMS CSV files (C/I/D row format) out of zip archives."""

import csv
import io
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd


def read_mms_zip(path: Path, columns: list[str], region: str | None = None,
                 where: tuple[str, set[str]] | None = None) -> pd.DataFrame:
    """Read the D rows of every CSV member in an MMS zip.

    Each ``I`` row starts a section and gives its column names; ``D`` rows are data.
    Only ``columns`` are kept (missing ones are filled with None, since older report
    versions lack some fields). If ``region`` is given, rows are filtered on REGIONID;
    ``where=(column, values)`` keeps only rows whose column is in ``values`` (e.g. DUIDs).
    All values are returned as strings; typing happens in normalise.
    """
    if region is not None:
        where = ("REGIONID", {region})
    frames = []
    with zipfile.ZipFile(path) as zf:
        for member in zf.namelist():
            if not member.lower().endswith(".csv"):
                continue
            with zf.open(member) as raw:
                frames.extend(_parse_stream(io.TextIOWrapper(raw, encoding="utf-8", newline=""), columns, where))
    if not frames:
        return pd.DataFrame(columns=columns, dtype=object)
    return pd.concat(frames, ignore_index=True)


def _parse_stream(lines, columns: list[str], where: tuple[str, set[str]] | None) -> list[pd.DataFrame]:
    col, values = where if where else (None, set())
    tokens = [f",{v}," for v in values]
    frames: list[pd.DataFrame] = []
    header: list[str] | None = None
    buf: list[str] = []

    def flush():
        if header is not None and buf:
            rows = list(csv.reader(buf))
            idx = {c: i for i, c in enumerate(header)}
            data = {c: ([r[idx[c]] if idx[c] < len(r) else None for r in rows] if c in idx else [None] * len(rows))
                    for c in columns}
            df = pd.DataFrame(data, dtype=object)
            if col is not None:
                if col not in idx:
                    raise KeyError(f"filter column {col} not in section header")
                df = df[np.array([r[idx[col]] in values for r in rows], dtype=bool)]
            frames.append(df)
        buf.clear()

    for line in lines:
        kind = line[:2]
        if kind == "D,":
            if not tokens or any(t in line for t in tokens):  # cheap pre-filter; exact filter in flush()
                buf.append(line)
        elif kind == "I,":
            flush()
            header = next(csv.reader([line]))
        # C rows (file header/footer) are ignored
    flush()
    return frames
