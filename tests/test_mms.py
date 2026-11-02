from conftest import write_mms_zip

from rbit.data.mms import read_mms_zip


def test_sections_region_filter_and_missing_columns(tmp_path):
    p = write_mms_zip(tmp_path / "x.zip", [
        (["SETTLEMENTDATE", "REGIONID", "RRP"], [
            ['"2025/03/01 00:05:00"', "NSW1", "139.85348"],
            ['"2025/03/01 00:05:00"', "QLD1", "132.25575"],
        ]),
        # a second section (newer report version) with an extra column
        (["SETTLEMENTDATE", "REGIONID", "RRP", "LASTCHANGED"], [
            ['"2025/03/01 00:10:00"', "NSW1", "120.1034", '"2025/03/01 00:05:03"'],
        ]),
    ])
    df = read_mms_zip(p, ["SETTLEMENTDATE", "REGIONID", "RRP", "LASTCHANGED"], region="NSW1")
    assert list(df["RRP"]) == ["139.85348", "120.1034"]
    assert set(df["REGIONID"]) == {"NSW1"}
    assert df["LASTCHANGED"].iloc[0] is None and df["LASTCHANGED"].iloc[1] == "2025/03/01 00:05:03"
    assert df["SETTLEMENTDATE"].iloc[0] == "2025/03/01 00:05:00"  # quotes stripped


def test_region_token_only_in_other_column_is_filtered(tmp_path):
    p = write_mms_zip(tmp_path / "y.zip", [(["REGIONID", "NOTE"], [["QLD1", "NSW1"]])])
    assert read_mms_zip(p, ["REGIONID"], region="NSW1").empty
