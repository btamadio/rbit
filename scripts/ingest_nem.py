import argparse
import os

import datetime

from supabase import create_client, Client

from rbit.data import nem


def download_to_csv(report_name: str, zip_files: list[str]) -> int:
    inserted_rows = 0
    out_filenames = set()
    for zip_file in zip_files:
        for filename, file in nem.csv_file_iter(zip_file):
            dfs = report_parser(filename, file)
            for table_name, df in dfs.items():
                df.columns = df.columns.str.lower()

                out_filename = os.path.join(
                    args.out, f"{report_name}_{table_name}.csv".lower()
                )
                df.to_csv(
                    out_filename,
                    index=False,
                    header=out_filename not in out_filenames,
                    mode="x" if out_filename not in out_filenames else "a",
                )
                out_filenames.add(out_filename)
                inserted_rows += len(df)
                print(f"[{filename}] {out_filename}: {len(df)} rows written")
    return inserted_rows


def upsert_to_supabase(report_name: str, zip_files: list[str]) -> int:
    supabase_url = os.environ.get("SUPABASE_URL", "URL")
    supabase_key = os.environ.get("SUPABASE_KEY", "KEY")
    supabase: Client = create_client(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
    )

    inserted_rows = 0
    for zip_file in zip_files:
        for filename, file in nem.csv_file_iter(zip_file):
            dfs = report_parser(filename, file)
            for table_name, df in dfs.items():
                df.columns = df.columns.str.lower()
                records = df.to_dict(orient="records")
                supabase_table = f"{report_name}_{table_name}".lower()
                response = (
                    supabase.schema("nem")
                    .table(supabase_table)
                    .upsert(records, ignore_duplicates=True)
                    .execute()
                )
                if response.data:
                    inserted_rows += len(response.data)
                    print(
                        f"[{filename}] {supabase_table}: {len(response.data)} rows inserted"
                    )
    return inserted_rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "report_name", choices=[nem.DISPATCH, nem.P5_MIN, nem.PREDISPATCH]
    )
    parser.add_argument("current_time", type=datetime.datetime.fromisoformat)
    parser.add_argument(
        "--lookback",
        type=int,
        default=1,
        help="hours before current time to look for files",
    )
    parser.add_argument("--out", help="output path for outputting csv file")
    args = parser.parse_args()

    url = nem.URLS_CURRENT[args.report_name]
    report_parser = nem.PARSERS[args.report_name]

    zip_files = nem.list_zip_files(url)
    zip_files = [
        zf
        for zf in zip_files
        if args.current_time - nem.parse_datetime_from_filename(zf)
        < datetime.timedelta(hours=args.lookback)
    ]

    if not zip_files:
        raise ValueError("No files found.")

    print(f"Parsing {len(zip_files)} files")

    if args.out:
        inserted_rows = download_to_csv(args.report_name, zip_files)
    else:
        inserted_rows = upsert_to_supabase(args.report_name, zip_files)

    print(f"total: {inserted_rows} rows inserted")
