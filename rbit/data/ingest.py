"""Download and clean MMSDM tables for one region.

    python -m rbit.data.ingest --start 2021-10 --end 2026-09 [--tables dispatch_price ...]

Raw zips are cached under data/raw/YYYYMM/ and months already cleaned are skipped,
so the command can be re-run after an interruption.
"""

import argparse
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed

import pandas as pd

from rbit.config import DataConfig
from rbit.data import archive
from rbit.data.mms import read_mms_zip
from rbit.data.normalise import normalise
from rbit.data.store import missing_marker, month_path
from rbit.data.tables import TABLES, TableSpec

log = logging.getLogger("rbit.ingest")


def months(start: str, end: str) -> list[tuple[int, int]]:
    return [(p.year, p.month) for p in pd.period_range(start, end, freq="M")]


def ingest_month(cfg: DataConfig, year: int, month: int, specs: list[TableSpec], force: bool = False,
                 keep_raw: bool = True) -> dict[str, int]:
    """Ingest the given tables for one month; returns rows written per table."""
    todo = [s for s in specs if force or not (month_path(cfg, s.name, year, month).exists()
                                              or missing_marker(cfg, s.name, year, month).exists())]
    written: dict[str, int] = {}
    if not todo:
        return written
    raw_dir = cfg.raw_dir / f"{year}{month:02d}"
    with archive.make_client() as client:
        listings = {f: archive.list_folder(client, year, month, f) for f in {s.folder for s in todo}}
        for spec in todo:
            names = archive.match_files(listings[spec.folder], spec)
            if not names:
                # Known archive gaps exist (e.g. PREDISPATCH all-runs files for 2022-10). Record and move on;
                # the quality report lists them and InfoSet never fills them with stale runs.
                log.warning("%s missing from archive for %d-%02d (%s)", spec.mms_table, year, month, spec.folder)
                marker = missing_marker(cfg, spec.name, year, month)
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(f"{spec.mms_table} not in {archive.month_dir_url(year, month, spec.folder)}\n")
                written[spec.name] = 0
                continue
            paths = [archive.download(client, year, month, spec.folder, n, raw_dir) for n in names]
            raw = pd.concat([read_mms_zip(p, list(spec.columns), cfg.region) for p in paths], ignore_index=True)
            df = normalise(raw, spec)
            out = month_path(cfg, spec.name, year, month)
            out.parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(out, index=False)
            written[spec.name] = len(df)
            if not keep_raw:
                for p in paths:
                    p.unlink()
    return written


def main(argv: list[str] | None = None) -> None:
    cfg = DataConfig()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=cfg.start)
    ap.add_argument("--end", default=cfg.end)
    ap.add_argument("--tables", nargs="*", default=list(TABLES), choices=list(TABLES))
    ap.add_argument("--region", default=cfg.region)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--force", action="store_true", help="re-clean months that already exist")
    ap.add_argument("--drop-raw", action="store_true", help="delete raw zips after cleaning")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cfg = cfg.model_copy(update={"region": args.region})
    specs = [TABLES[t] for t in args.tables]
    failures = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(ingest_month, cfg, y, m, specs, args.force, not args.drop_raw): (y, m)
                for y, m in months(args.start, args.end)}
        for fut in as_completed(futs):
            y, m = futs[fut]
            try:
                log.info("%d-%02d done %s", y, m, fut.result() or "(cached)")
            except Exception as e:  # keep going; report at the end
                failures.append((y, m, e))
                log.error("%d-%02d FAILED: %r", y, m, e)
    if failures:
        raise SystemExit(f"{len(failures)} month(s) failed: {[(y, m) for y, m, _ in failures]}")


if __name__ == "__main__":
    main()
