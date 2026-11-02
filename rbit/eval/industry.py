"""Industry-claim decomposition (milestone M2b).

Splits realised revenue of the region's grid batteries into energy and FCAS for a calendar year,
from public AEMO data, to turn the $217k/MW (energy + FCAS) claim into an energy-only comparator.

    python -m rbit.eval.industry [--year 2025]

Method (per unit, 5-minute intervals, INTERVENTION=0 rows):
- Energy: E_t = (INITIALMW_t + INITIALMW_{t+1}) / 2 x 5/60 MWh, i.e. a straight line between
  successive SCADA readings (INITIALMW is signed for bidirectional units: < 0 when charging).
  Revenue = RRP_t x E_t x MLF, with the unit's generation MLF when E_t > 0 and load MLF otherwise.
  A dispatch-target variant (TOTALCLEARED instead of SCADA) is reported as a cross-check.
- FCAS: sum over the 10 services of enabled MW x regional FCAS price x 5/60 (no MLF applies).
- PortfolioEnergy's published figures match an RRP basis (no MLFs): Riverina 1 2025 comes out at
  ~186k $/MW without MLFs vs 190k published, and ~162k with its MLFs. Both bases are reported;
  comparisons with the claim use the RRP basis.
- Not included: FCAS cost recovery and regulation performance (FPP) payments/charges, market
  fees, and any contract/hedge revenue. $/MW uses the registered MAXCAPACITY; units active for
  part of the year are annualised by days registered.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from rbit.config import INTERVAL_H, DataConfig
from rbit.data import archive, store
from rbit.data.mms import read_mms_zip
from rbit.data.tables import TableSpec
from rbit.market.mlf import load_registration, mlf_schedule, mlf_series

INDUSTRY_CLAIM = 217_000  # $/MW/yr, PortfolioEnergy, NSW 2 h category, 2025, energy + FCAS
PEER_CLAIM = {"RESS1": 190_000}  # Riverina 1 BESS on PortfolioEnergy's comparison page
CLAIMED_ENERGY_SHARE = 0.93  # the ~93% arbitrage share to confirm or correct
TWO_HOUR = (1.75, 2.25)  # MWh/MW range for the "2-hour" category
# Units left out of fleet statistics: not merchant batteries, so their revenue says nothing about trading.
EXCLUDED = {
    "WTAHB1": "Waratah Super Battery: contracted as a System Integrity Protection Scheme and mostly held in "
              "reserve (2025 mean |MW| ~8-50 of 850)",
}

SERVICES = ["RAISE6SEC", "RAISE60SEC", "RAISE5MIN", "RAISEREG", "LOWER6SEC", "LOWER60SEC", "LOWER5MIN",
            "LOWERREG", "RAISE1SEC", "LOWER1SEC"]


def _spec(table: str) -> TableSpec:
    return TableSpec(name=table.lower(), mms_table=table, folder="DATA", old_marker="", new_marker="", columns={},
                     key=())


def _download(cfg: DataConfig, table: str, year: int, month: int) -> list[Path]:
    spec = _spec(table)
    with archive.make_client() as client:
        names = archive.match_files(archive.list_folder(client, year, month, "DATA"), spec)
        if not names:
            raise FileNotFoundError(f"{table} not in the {year}-{month:02d} archive")
        return [archive.download(client, year, month, "DATA", n, cfg.raw_dir / f"{year}{month:02d}") for n in names]


def _num(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def fleet(cfg: DataConfig, year: int) -> pd.DataFrame:
    """Bidirectional units in cfg.region registered at some point during ``year``, with size and duration."""
    reg = load_registration(cfg)
    y0, y1 = pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1)
    bdu = reg[(reg["DISPATCHTYPE"] == "BIDIRECTIONAL") & (reg["START_DATE"] < y1) & (reg["END_DATE"] > y0)]
    units = bdu.groupby("DUID").agg(station=("STATIONID", "first"), registered_from=("START_DATE", "min"))

    p = pd.Period(cfg.end, freq="M")
    cols = ["DUID", "EFFECTIVEDATE", "VERSIONNO", "MAXCAPACITY", "MAXSTORAGECAPACITY"]
    det = pd.concat([read_mms_zip(f, cols, where=("DUID", set(units.index)))
                     for f in _download(cfg, "DUDETAIL", p.year, p.month)], ignore_index=True)
    det["EFFECTIVEDATE"] = pd.to_datetime(det["EFFECTIVEDATE"], format="%Y/%m/%d %H:%M:%S")
    det = _num(det, ["VERSIONNO", "MAXCAPACITY", "MAXSTORAGECAPACITY"])
    det = det[det["EFFECTIVEDATE"] < y1].sort_values(["DUID", "EFFECTIVEDATE", "VERSIONNO"]).groupby("DUID").last()
    units = units.join(det[["MAXCAPACITY", "MAXSTORAGECAPACITY"]].rename(
        columns={"MAXCAPACITY": "mw", "MAXSTORAGECAPACITY": "mwh"}))
    units["duration_h"] = units["mwh"] / units["mw"]
    units["active_from"] = units["registered_from"].clip(lower=y0)
    units["days"] = (y1 - units["active_from"]).dt.total_seconds() / 86400
    units["full_year"] = units["registered_from"] <= y0
    units["two_hour"] = units["duration_h"].between(*TWO_HOUR)
    units["excluded"] = units.index.map(lambda d: EXCLUDED.get(d, ""))
    return units.sort_values("mw", ascending=False)


_DL_COLS = ["SETTLEMENTDATE", "DUID", "INTERVENTION", "INITIALMW", "TOTALCLEARED", *SERVICES]
_PRICE_COLS = ["SETTLEMENTDATE", "REGIONID", "INTERVENTION", *[f"{s}RRP" for s in SERVICES]]


def _unit_month(cfg: DataConfig, duids: tuple[str, ...], year: int, month: int) -> pd.DataFrame:
    out = cfg.clean_dir / "unit_dispatch" / f"{year}{month:02d}.parquet"
    if out.exists():
        cached = pd.read_parquet(out)
        if set(duids) <= set(cached["duid"].unique()):
            return cached[cached["duid"].isin(duids)]
    df = pd.concat([read_mms_zip(f, _DL_COLS, where=("DUID", set(duids)))
                    for f in _download(cfg, "DISPATCHLOAD", year, month)], ignore_index=True)
    df = _num(df, ["INTERVENTION", "INITIALMW", "TOTALCLEARED", *SERVICES])
    df = df[df["INTERVENTION"] == 0].drop(columns="INTERVENTION")
    df["SETTLEMENTDATE"] = pd.to_datetime(df["SETTLEMENTDATE"], format="%Y/%m/%d %H:%M:%S")
    df = df.rename(columns={"SETTLEMENTDATE": "interval_end", "DUID": "duid", "INITIALMW": "initial_mw",
                            "TOTALCLEARED": "total_cleared"} | {s: s.lower() for s in SERVICES})
    df = df.drop_duplicates(["duid", "interval_end"], keep="last")
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    return df


def _fcas_prices_month(cfg: DataConfig, year: int, month: int) -> pd.DataFrame:
    df = pd.concat([read_mms_zip(f, _PRICE_COLS, cfg.region) for f in _download(cfg, "DISPATCHPRICE", year, month)],
                   ignore_index=True)
    df = _num(df, ["INTERVENTION", *[f"{s}RRP" for s in SERVICES]])
    df = df[df["INTERVENTION"] == 0]
    df["interval_end"] = pd.to_datetime(df["SETTLEMENTDATE"], format="%Y/%m/%d %H:%M:%S")
    return df.drop_duplicates("interval_end", keep="last")[["interval_end", *[f"{s}RRP" for s in SERVICES]]]


def load_year(cfg: DataConfig, duids: list[str], year: int, workers: int = 6) -> tuple[pd.DataFrame, pd.DataFrame]:
    months = [(year, m) for m in range(1, 13)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        units = list(pool.map(_unit_month, [cfg] * 12, [tuple(duids)] * 12, *zip(*months)))
        prices = list(pool.map(_fcas_prices_month, [cfg] * 12, *zip(*months)))
    y0, y1 = pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1)
    u = pd.concat(units, ignore_index=True)
    p = pd.concat(prices, ignore_index=True)
    in_year = lambda d: d[(d["interval_end"] > y0) & (d["interval_end"] <= y1)]  # noqa: E731
    return in_year(u), in_year(p)


def unit_revenues(units: pd.DataFrame, prices: pd.DataFrame, rrp: pd.DataFrame, mlfs: dict[str, pd.DataFrame],
                  ) -> pd.DataFrame:
    """Energy and FCAS revenue ($) per unit for the given intervals."""
    df = units.merge(rrp[["interval_end", "rrp"]], on="interval_end", how="left").merge(prices, on="interval_end",
                                                                                         how="left")
    if df["rrp"].isna().any():
        raise ValueError("missing RRP for some unit intervals")
    df = df.sort_values(["duid", "interval_end"])
    nxt = df.groupby("duid")["initial_mw"].shift(-1)
    contiguous = df.groupby("duid")["interval_end"].shift(-1) - df["interval_end"] == pd.Timedelta(minutes=5)
    df["energy_mwh"] = (df["initial_mw"] + nxt.where(contiguous, df["initial_mw"])) / 2 * INTERVAL_H
    df["target_mwh"] = df["total_cleared"] * INTERVAL_H
    rows = []
    for duid, g in df.groupby("duid"):
        m = mlf_series(mlfs[duid], g["interval_end"])
        mlf_e = np.where(g["energy_mwh"] > 0, m.gen, m.load)
        mlf_t = np.where(g["target_mwh"] > 0, m.gen, m.load)
        fcas = {s.lower(): float((g[s.lower()].fillna(0) * g[f"{s}RRP"].fillna(0)).sum() * INTERVAL_H)
                for s in SERVICES}
        rows.append({
            "duid": duid,
            "intervals": len(g),
            "energy": float((g["rrp"] * g["energy_mwh"] * mlf_e).sum()),
            "energy_rrp": float((g["rrp"] * g["energy_mwh"]).sum()),
            "energy_target": float((g["rrp"] * g["target_mwh"] * mlf_t).sum()),
            "fcas": sum(fcas.values()),
            "discharged_mwh": float(g["energy_mwh"].clip(lower=0).sum()),
            "mlf_gen": float(m.gen.mean()), "mlf_load": float(m.load.mean()),
        } | {f"fcas_{k}": v for k, v in fcas.items()})
    return pd.DataFrame(rows).set_index("duid")


def analyse(cfg: DataConfig, year: int) -> pd.DataFrame:
    units = fleet(cfg, year)
    reg = load_registration(cfg)
    mlfs = {d: mlf_schedule(reg, units.loc[d, "station"], [d]) for d in units.index}
    u, prices = load_year(cfg, list(units.index), year)
    rrp = store.load(cfg, "dispatch_price", pd.Timestamp(year, 1, 1), pd.Timestamp(year + 1, 1, 1, 0, 5))
    rev = unit_revenues(u, prices, rrp, mlfs)
    res = units.join(rev, how="inner")
    scale = 365 / res["days"] / res["mw"]  # annualised $/MW
    for c in ("energy", "energy_rrp", "energy_target", "fcas"):
        res[f"{c}_per_mw"] = res[c] * scale
    res["total_per_mw"] = res["energy_per_mw"] + res["fcas_per_mw"]
    res["total_rrp_per_mw"] = res["energy_rrp_per_mw"] + res["fcas_per_mw"]
    res["energy_share"] = res["energy_rrp"] / (res["energy_rrp"] + res["fcas"])  # RRP basis, like the claim
    res["cycles_per_day"] = res["discharged_mwh"] / res["mwh"] / res["days"]
    return res


def _k(x: float) -> str:
    return "" if pd.isna(x) else f"{x / 1000:,.0f}k"


def build_report(res: pd.DataFrame, year: int, pf: pd.DataFrame | None) -> str:
    two = res[res["two_hour"] & res["full_year"] & (res["excluded"] == "")]
    share = two["energy_rrp"].sum() / (two["energy_rrp"].sum() + two["fcas"].sum())  # pooled $, RRP basis
    lo, hi = two["energy_share"].min(), two["energy_share"].max()
    comp, comp_lo, comp_hi = INDUSTRY_CLAIM * share, INDUSTRY_CLAIM * lo, INDUSTRY_CLAIM * hi
    w = two["mw"]
    fleet_rrp = float((two["energy_rrp_per_mw"] * w).sum() / w.sum())
    fleet_mlf = float((two["energy_per_mw"] * w).sum() / w.sum())
    rows = [f"| {d} | {r.mw:g} | {r.mwh:g} | {r.duration_h:.2f} | {'yes' if r.two_hour else ''} | {r.days:.0f} | "
            f"{r.mlf_gen:.3f} / {r.mlf_load:.3f} | {_k(r.energy_rrp_per_mw)} | {_k(r.energy_per_mw)} | "
            f"{_k(r.fcas_per_mw)} | {_k(r.total_rrp_per_mw)} | "
            f"{'' if pd.isna(r.energy_share) else f'{r.energy_share:.0%}'} | {r.cycles_per_day:.2f} | "
            f"{'excluded' if r.excluded else ''} |" for d, r in res.iterrows()]
    fcas_cols = [f"fcas_{s.lower()}" for s in SERVICES]
    mix = (two[fcas_cols].sum() / two["fcas"].sum()).sort_values(ascending=False)
    mix_rows = [f"| {c.removeprefix('fcas_').upper()} | {v:.0%} |" for c, v in mix.items() if v >= 0.005]
    verdict = (f"the estimate is {share:.1%}, so the {CLAIMED_ENERGY_SHARE:.0%} figure "
               + ("holds" if abs(share - CLAIMED_ENERGY_SHARE) < 0.02 else
                  f"{'under' if share > CLAIMED_ENERGY_SHARE else 'over'}states the arbitrage share by "
                  f"{abs(share - CLAIMED_ENERGY_SHARE) * 100:.1f} percentage points"))
    lines = [
        f"# M2b: energy vs FCAS revenue of NSW grid batteries, CY{year}",
        "",
        f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} by `python -m rbit.eval.industry`. Method and exclusions:",
        "see the module docstring in `rbit/eval/industry.py`. Estimates from public AEMO data (SCADA, FCAS",
        "enablement, prices, registered MLFs); annualised $/MW of registered max capacity.",
        "**RRP basis** = revenue at the regional price with no loss factors (how PortfolioEnergy reports);",
        "**MLF basis** = after each unit's marginal loss factors (closer to cash settlement).",
        "",
        "## Per unit",
        "",
        "| DUID | MW | MWh | h | 2 h | Days | MLF gen / load | Energy $/MW (RRP) | Energy $/MW (MLF) |"
        " FCAS $/MW | Total $/MW (RRP) | Energy share | Cycles/day | |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        *rows,
        "",
        "Excluded from fleet statistics:",
        "",
        *[f"- {d}: {why}" for d, why in EXCLUDED.items() if d in res.index],
        "",
        f"## Calibration against PortfolioEnergy's comparison page",
        "",
    ]
    for d, published in PEER_CLAIM.items():
        if d in res.index:
            r = res.loc[d]
            lines += [f"- {d}: RRP basis **{_k(r.total_rrp_per_mw)}** vs {_k(published)} published "
                      f"({r.total_rrp_per_mw / published - 1:+.0%}); MLF basis {_k(r.total_per_mw)} "
                      f"({r.total_per_mw / published - 1:+.0%}). Their figures look like the RRP basis."]
    lines += [
        "",
        f"## NSW 2-hour merchant fleet ({TWO_HOUR[0]}–{TWO_HOUR[1]} h, registered all year): {', '.join(two.index)}",
        "",
        f"- Energy share of energy + FCAS revenue (RRP basis, pooled $): **{share:.1%}**; by unit {lo:.0%}–{hi:.0%}.",
        f"- Claimed ~{CLAIMED_ENERGY_SHARE:.0%} arbitrage share: {verdict}.",
        f"- Capacity-weighted energy revenue: {_k(fleet_rrp)} $/MW/yr (RRP basis), {_k(fleet_mlf)} (MLF basis).",
        "",
        "FCAS revenue mix of this fleet:",
        "",
        "| Service | Share of FCAS $ |",
        "|---|---|",
        *mix_rows,
        "",
        f"## Energy-only comparator for the {_k(INDUSTRY_CLAIM)} claim",
        "",
        f"`{_k(INDUSTRY_CLAIM)} x {share:.1%}` = **{_k(comp)} $/MW/yr** on the RRP basis (range {_k(comp_lo)}–"
        f"{_k(comp_hi)} with the per-unit shares; {_k(INDUSTRY_CLAIM * CLAIMED_ENERGY_SHARE)} at the claimed "
        f"{CLAIMED_ENERGY_SHARE:.0%}). Assumes the claimant's revenue mix matches this fleet's.",
        "",
    ]
    if pf is not None:
        b = pf[(pf["year"] == year) & (pf["duration_h"] == 2.0)]
        b4_mlf = b[(b["benchmark"] == "B4") & (b["label"] == "base")]["revenue_per_mw"].iloc[0]
        b3_mlf = b[(b["benchmark"] == "B3") & (b["label"] == "base")]["revenue_per_mw"].iloc[0]
        b4_rrp = b[(b["benchmark"] == "B4") & (b["label"] == "MLF 1.0")]["revenue_per_mw"].iloc[0]
        r1 = res.loc["RESS1"] if "RESS1" in res.index else None
        entries = [
            ("B4 perfect-foresight LP", b4_rrp, b4_mlf),
            ("B3 perfect-foresight MPC, 24 h", np.nan, b3_mlf),
            ("Energy-only comparator (claim x fleet energy share)", comp, np.nan),
            ("Riverina 1 actual energy revenue", r1.energy_rrp_per_mw if r1 is not None else np.nan,
             r1.energy_per_mw if r1 is not None else np.nan),
            ("NSW 2 h merchant fleet actual energy revenue", fleet_rrp, fleet_mlf),
        ]
        pct = lambda v, ref: "" if pd.isna(v) else f"{v / ref:.0%}"  # noqa: E731
        lines += [
            f"## Side by side, CY{year}, 2 h, energy only, $/MW/yr",
            "",
            "B4 on the MLF basis uses Riverina 1's MLFs (M2); on the RRP basis it is the M2 \"MLF 1.0\" run.",
            "",
            "| Strategy | RRP basis | % of B4 | MLF basis (RESS1) | % of B4 |",
            "|---|---|---|---|---|",
            *[f"| {n} | {_k(a)} | {pct(a, b4_rrp)} | {_k(m)} | {pct(m, b4_mlf)} |" for n, a, m in entries],
            f"| Industry claim, energy + FCAS (reference) | {_k(INDUSTRY_CLAIM)} | {pct(INDUSTRY_CLAIM, b4_rrp)} | | |",
            "",
            "B3 was only run on the MLF basis. B2 (pre-dispatch MPC) and RL rows are added from M3 / M6.",
            "",
        ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--out", type=Path, default=Path("reports") / "m2b_industry_claim")
    ap.add_argument("--perfect-foresight", type=Path, default=Path("reports") / "m2_perfect_foresight.csv")
    args = ap.parse_args(argv)
    cfg = DataConfig()
    res = analyse(cfg, args.year)
    pf = pd.read_csv(args.perfect_foresight) if args.perfect_foresight.exists() else None
    args.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(args.out.with_suffix(".csv"))
    args.out.with_suffix(".md").write_text(build_report(res, args.year, pf))
    print(f"wrote {args.out.with_suffix('.md')} and .csv")


if __name__ == "__main__":
    main()
