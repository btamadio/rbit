import csv
import datetime
import io
import logging
import os
import random
import time
import typing as tt
import urllib.parse
import zipfile

import bs4
import pandas as pd
import requests

logger = logging.getLogger(__name__)

DISPATCH = "dispatch"
P5_MIN = "p5_min"
PREDISPATCH = "predispatch"

URLS_CURRENT = {
    DISPATCH: "https://www.nemweb.com.au/Reports/CURRENT/DispatchIS_Reports",
    P5_MIN: "https://www.nemweb.com.au/Reports/CURRENT/P5_Reports",
    PREDISPATCH: "https://www.nemweb.com.au/Reports/CURRENT/PredispatchIS_Reports",
}

URLS_ARCHIVE = {
    DISPATCH: "https://www.nemweb.com.au/Reports/ARCHIVE/DispatchIS_Reports",
    P5_MIN: "https://www.nemweb.com.au/Reports/ARCHIVE/P5_Reports",
    PREDISPATCH: "https://www.nemweb.com.au/Reports/ARCHIVE/PredispatchIS_Reports",
}


def parse_datetime_from_filename(filename: str) -> datetime.datetime:
    date_str = os.path.splitext(os.path.split(filename)[-1])[0].split("_")[2]
    if len(date_str) == 8:
        format = "%Y%m%d"
    elif len(date_str) == 12:
        format = "%Y%m%d%H%M"
    else:
        raise ValueError(f"Failed to parse datetime from filename: {filename}")

    return datetime.datetime.strptime(date_str, format)


def parse_publication_datetime_from_filename(filename: str) -> datetime.datetime:
    return pd.to_datetime(
        os.path.splitext(os.path.split(filename)[-1])[0].split("_")[-1],
        format="%Y%m%d%H%M%S",
    )


def list_zip_files(target_url):
    files = []
    response = requests.get(target_url)
    response.raise_for_status()
    soup = bs4.BeautifulSoup(response.text, "html.parser")
    for link in soup.find_all("a"):
        href = str(link.get("href"))
        if not href or not href.lower().endswith(".zip"):
            continue
        files.append(urllib.parse.urljoin(target_url, href))
    return files


def csv_file_iter(outer_zip_url):

    base_delay = 1
    max_delay = 30
    max_attempts = 5

    attempt = 0
    succeeded = False

    while not succeeded:
        try:
            response = requests.get(outer_zip_url, timeout=10)
            response.raise_for_status()
            succeeded = True

        except requests.exceptions.HTTPError as e:
            attempt += 1
            if attempt >= max_attempts:
                logger.error(f"Max retries exceeded")
                break

            delay = random.uniform(0, min((2**attempt) * base_delay, max_delay))

            status_code = e.response.status_code

            if e.response.status_code == 404:
                raise e

            error_body = e.response.text
            logger.warning(f"HTTPError [{status_code}]: {error_body}. Retrying...")
            time.sleep(delay)

    outer_zip_buffer = io.BytesIO(response.content)
    with zipfile.ZipFile(outer_zip_buffer) as outer_zip:
        # handle top-level CSVs
        csv_file_names = sorted(
            [f for f in outer_zip.namelist() if f.lower().endswith(".csv")]
        )
        for csv_file_name in csv_file_names:
            with outer_zip.open(csv_file_name) as csv_file:
                yield csv_file_name, io.TextIOWrapper(csv_file, encoding="utf-8")

        # handle nested ZIPs
        inner_zip_names = sorted(
            [f for f in outer_zip.namelist() if f.lower().endswith(".zip")]
        )
        for inner_name in inner_zip_names:
            inner_zip_bytes = outer_zip.read(inner_name)
            with zipfile.ZipFile(io.BytesIO(inner_zip_bytes)) as inner_zip:
                csv_file_names = [
                    f for f in inner_zip.namelist() if f.lower().endswith(".csv")
                ]
                for csv_file_name in csv_file_names:
                    with inner_zip.open(csv_file_name) as csv_file:
                        yield csv_file_name, io.TextIOWrapper(
                            csv_file, encoding="utf-8"
                        )


def parse_report(
    file: tt.Iterable[str], table_columns: dict[str, list[str]] | None = None
) -> dict[str, pd.DataFrame]:
    tables = {}
    reader = csv.reader(file)
    for row in reader:
        if row[0] == "C":
            continue
        if row[0] == "I":
            table_name = row[2]
            tables[table_name] = {"columns": row, "data": []}
        if row[0] == "D":
            table_name = row[2]
            tables[table_name]["data"].append(row)
    dfs = {name: pd.DataFrame(**table) for name, table in tables.items()}

    if table_columns:
        filtered = {}
        for table_name, df in dfs.items():
            if table_name in table_columns.keys():
                filtered[table_name] = df[table_columns[table_name]]
        return filtered

    return dfs


def parse_dispatch_report(
    filename: str, file: tt.Iterable[str]
) -> dict[str, pd.DataFrame]:
    return parse_report(
        file,
        table_columns={
            "PRICE": ["REGIONID", "SETTLEMENTDATE", "INTERVENTION", "RRP"],
            "REGIONSUM": ["REGIONID", "SETTLEMENTDATE", "INTERVENTION", "TOTALDEMAND"],
            "INTERCONNECTION": [
                "SETTLEMENTDATE",
                "INTERVENTION",
                "FROM_REGIONID",
                "TO_REGIONID",
                "MWFLOW",
            ],
        },
    )


def parse_p5min_report(
    filename: str, file: tt.Iterable[str]
) -> dict[str, pd.DataFrame]:
    data = parse_report(
        file,
        table_columns={
            "REGIONSOLUTION": [
                "REGIONID",
                "RUN_DATETIME",
                "INTERVAL_DATETIME",
                "INTERVENTION",
                "RRP",
                "TOTALDEMAND",
                "NETINTERCHANGE",
            ]
        },
    )

    for table_name in data.keys():
        data[table_name]["PUBLICATION_DATETIME"] = (
            parse_publication_datetime_from_filename(filename).isoformat()
        )
    return data


def parse_predispatch_report(
    filename: str, file: tt.Iterable[str]
) -> dict[str, pd.DataFrame]:
    data = parse_report(
        file,
        table_columns={
            "REGION_PRICES": ["REGIONID", "DATETIME", "INTERVENTION", "RRP"],
            "REGION_SOLUTION": [
                "REGIONID",
                "DATETIME",
                "INTERVENTION",
                "TOTALDEMAND",
                "NETINTERCHANGE",
            ],
        },
    )
    for table_name in data.keys():
        data[table_name]["PUBLICATION_DATETIME"] = (
            parse_publication_datetime_from_filename(filename).isoformat()
        )
        data[table_name]["RUN_DATETIME"] = parse_datetime_from_filename(
            filename
        ).isoformat()
    return data


PARSERS: dict[str, tt.Callable[[str, tt.Iterable[str]], dict[str, pd.DataFrame]]] = {
    DISPATCH: parse_dispatch_report,
    P5_MIN: parse_p5min_report,
    PREDISPATCH: parse_predispatch_report,
}
