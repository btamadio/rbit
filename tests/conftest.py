import zipfile
from pathlib import Path


def write_mms_zip(path: Path, sections: list[tuple[list[str], list[list[str]]]]) -> Path:
    """Write an MMS-format CSV (C header, I/D sections, C footer) into a zip."""
    lines = ['C,SETP.WORLD,DVD_TEST,AEMO,PUBLIC,2025/04/08,13:54:04,1,MONTHLY_ARCHIVE,1']
    for header, rows in sections:
        lines.append(",".join(["I", "X", "Y", "1", *header]))
        lines += [",".join(["D", "X", "Y", "1", *r]) for r in rows]
    lines.append('C,"END OF REPORT",3')
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(path.stem + ".CSV", "\n".join(lines) + "\n")
    return path
