from rbit.data.archive import match_files, parse_listing
from rbit.data.tables import TABLES

BASE = "/Data_Archive/Wholesale_Electricity/MMSDM/2025/MMSDM_2025_03/MMSDM_Historical_Data_SQLLoader"
NEW_DATA = [
    "PUBLIC_ARCHIVE%23DISPATCHPRICE%23FILE01%23202503010000.zip",
    "PUBLIC_ARCHIVE%23DISPATCHREGIONSUM%23FILE01%23202503010000.zip",
    "PUBLIC_ARCHIVE%23PREDISPATCHPRICE%23FILE01%23202503010000.zip",
    "PUBLIC_ARCHIVE%23PREDISPATCHPRICESENSITIVITIES%23FILE01%23202503010000.zip",
]
OLD_DATA = [
    "PUBLIC_DVD_DISPATCHPRICE_202110010000.zip",
    "PUBLIC_DVD_PREDISPATCHPRICE_D_202110010000.zip",
    "PUBLIC_DVD_DISPATCHREGIONSUM_202110010000.zip",
]


def listing(names, folder="DATA"):
    links = "".join(f'<A HREF="{BASE}/{folder}/{n}">{n}</A><br>' for n in names)
    return f'<html><body><A HREF="{BASE}">[To Parent Directory]</A><br>{links}</body></html>'


def test_parse_listing_decodes_and_keeps_only_zips():
    names = parse_listing(listing(NEW_DATA))
    assert "PUBLIC_ARCHIVE#DISPATCHPRICE#FILE01#202503010000.zip" in names
    assert all(n.endswith(".zip") for n in names) and len(names) == len(NEW_DATA)


def test_dispatchprice_does_not_match_predispatch_tables():
    for names in (parse_listing(listing(NEW_DATA)), parse_listing(listing(OLD_DATA))):
        got = match_files(names, TABLES["dispatch_price"])
        assert len(got) == 1 and "PREDISPATCH" not in got[0]


def test_all_runs_files_both_schemes_and_multi_part():
    p5 = TABLES["p5min_region"]
    new = parse_listing(listing([
        "PUBLIC_ARCHIVE%23P5MIN_REGIONSOLUTION%23ALL%23FILE01%23202503010000.zip",
        "PUBLIC_ARCHIVE%23P5MIN_REGIONSOLUTION%23ALL%23FILE02%23202503010000.zip",
        "PUBLIC_ARCHIVE%23P5MIN_CONSTRAINTSOLUTION%23ALL%23FILE01%23202503010000.zip",
    ], "P5MIN_ALL_DATA"))
    assert len(match_files(new, p5)) == 2
    old = ["PUBLIC_DVD_P5MIN_REGIONSOLUTION_ALL_202110010000.zip", "PUBLIC_DVD_P5MIN_REGIONSOLUTION_202110010000.zip"]
    assert match_files(old, p5) == ["PUBLIC_DVD_P5MIN_REGIONSOLUTION_ALL_202110010000.zip"]


def test_predispatch_all_runs_old_scheme_has_no_all_marker():
    pdp = TABLES["predispatch_price"]
    old = ["PUBLIC_DVD_PREDISPATCHPRICE_202110010000.zip", "PUBLIC_DVD_PREDISPATCHPRICESENSITIVITIES_202110010000.zip"]
    assert match_files(old, pdp) == ["PUBLIC_DVD_PREDISPATCHPRICE_202110010000.zip"]
    new = ["PUBLIC_ARCHIVE#PREDISPATCHPRICE#ALL#FILE01#202503010000.zip",
           "PUBLIC_ARCHIVE#PREDISPATCHPRICE#FILE01#202503010000.zip"]  # the DATA-folder latest-run file
    assert match_files(new, pdp) == ["PUBLIC_ARCHIVE#PREDISPATCHPRICE#ALL#FILE01#202503010000.zip"]
