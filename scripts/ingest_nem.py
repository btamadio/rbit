import argparse
import collections
import datetime
import os

import tqdm

from supabase import create_client, Client

from rbit.data import nem

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
    parser.add_argument("--archive", type=bool, default=False)
    args = parser.parse_args()

    if args.archive:
        url = nem.URLS[args.report_name].format(archive_or_current="ARCHIVE")
    else:
        url = nem.URLS[args.report_name].format(archive_or_current="CURRENT")

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
        os.makedirs(args.out, exist_ok=True)

    else:
        supabase_url = os.environ.get("SUPABASE_URL", "")
        supabase_key = os.environ.get("SUPABASE_KEY", "")
        supabase: Client = create_client(
            supabase_url=supabase_url,
            supabase_key=supabase_key,
        )

    table_rows_inserted = collections.defaultdict(int)
    for zip_file in tqdm.tqdm(
        zip_files, desc="Total progress", unit="files", colour="#006199"
    ):
        for filename, file in nem.csv_file_iter(zip_file):
            dfs = report_parser(filename, file)

            for sub_table, df in dfs.items():
                df.columns = df.columns.str.lower()
                records = df.to_dict(orient="records")
                supabase_table_name = f"{args.report_name}_{sub_table}".lower()
                rows_inserted = 0

                if args.out:
                    out_filename = os.path.join(
                        args.out, f"{supabase_table_name}.csv".lower()
                    )
                    df.to_csv(
                        out_filename,
                        index=False,
                        header=table_rows_inserted[supabase_table_name] == 0,
                        mode=(
                            "x"
                            if table_rows_inserted[supabase_table_name] == 0
                            else "a"
                        ),
                    )
                    rows_inserted = len(df)

                else:
                    response = (
                        supabase.schema("nem")
                        .table(supabase_table_name)
                        .upsert(records, ignore_duplicates=True)
                        .execute()
                    )
                    if response.data:
                        rows_inserted = len(response.data)

                if rows_inserted > 0:
                    # print(f"{filename}\t{supabase_table_name}\t{rows_inserted}")
                    table_rows_inserted[supabase_table_name] += rows_inserted

    if len(table_rows_inserted) == 0:
        print("No new data")
    for table, rows in table_rows_inserted.items():
        print(f"Total\t{table}\t{rows}")
