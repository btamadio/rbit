"""Find and download monthly MMSDM archive files from NEMWeb."""

import re
import time
from pathlib import Path
from urllib.parse import quote, unquote

import httpx

from rbit.data.tables import TableSpec

BASE_URL = "https://nemweb.com.au/Data_Archive/Wholesale_Electricity/MMSDM"
_HREF = re.compile(r'HREF="([^"]+)"', re.IGNORECASE)


def month_dir_url(year: int, month: int, folder: str) -> str:
    return f"{BASE_URL}/{year}/MMSDM_{year}_{month:02d}/MMSDM_Historical_Data_SQLLoader/{folder}/"


def parse_listing(html: str) -> list[str]:
    """File names (URL-decoded) linked from a NEMWeb directory listing."""
    names = []
    for href in _HREF.findall(html):
        name = unquote(href.rstrip("/").rsplit("/", 1)[-1])
        if name.lower().endswith(".zip"):
            names.append(name)
    return names


def match_files(names: list[str], spec: TableSpec) -> list[str]:
    rx = spec.file_regex()
    return sorted(n for n in names if rx.match(n))


def _get(client: httpx.Client, url: str, retries: int = 4) -> httpx.Response:
    for attempt in range(retries):
        try:
            r = client.get(url)
            r.raise_for_status()
            return r
        except (httpx.HTTPError, httpx.TransportError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def list_folder(client: httpx.Client, year: int, month: int, folder: str) -> list[str]:
    return parse_listing(_get(client, month_dir_url(year, month, folder)).text)


def download(client: httpx.Client, year: int, month: int, folder: str, name: str, dest_dir: Path,
             retries: int = 4) -> Path:
    """Download one archive file into dest_dir (skipped if already complete)."""
    dest = dest_dir / name.replace("#", "_")
    if dest.exists():
        return dest
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = month_dir_url(year, month, folder) + quote(name)
    tmp = dest.with_suffix(".part")
    for attempt in range(retries):
        try:
            with client.stream("GET", url) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
            tmp.rename(dest)
            return dest
        except (httpx.HTTPError, httpx.TransportError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def make_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(60.0, read=300.0), follow_redirects=True)
