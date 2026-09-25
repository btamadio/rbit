import argparse
import os

import datetime

from supabase import create_client, Client

from rbit.data import nem

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "report_name", choices=[nem.DISPATCH, nem.P5_MIN, nem.PREDISPATCH]
    )
    parser.add_argument("current_time", type=datetime.datetime.fromisoformat)
    parser.add_argument("--out", help="output path for outputting csv file")
    args = parser.parse_args()

    supabase_url = os.environ["SUPABASE_URL"]
    supabase_key = os.environ["SUPABASE_KEY"]

    supabase: Client = create_client(
        supabase_url=supabase_url,
        supabase_key=supabase_key,
    )

    url = nem.URLS_CURRENT[args.report_name]
    report_parser = nem.PARSERS[args.report_name]

    zip_files = nem.list_zip_files(url)
    zip_files = [
        zf
        for zf in zip_files
        if args.current_time - nem.parse_datetime_from_filename(zf)
        < datetime.timedelta(minutes=30)
    ]

    if not zip_files:
        raise ValueError("No files found.")

    for zip_file in zip_files:
        for filename, file in nem.csv_file_iter(zip_file):
            print(filename)
            dfs = report_parser(filename, file)
            for table_name, df in dfs.items():
                df.columns = df.columns.str.lower()
                records = df.to_dict(orient="records")
                supabase_table = f"{args.report_name}_{table_name}".lower()
                response = (
                    supabase.schema("nem")
                    .table(supabase_table)
                    .upsert(records, ignore_duplicates=True)
                    .execute()
                )
