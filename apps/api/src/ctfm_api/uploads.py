"""Bounded upload checks. User filenames are display metadata only."""
import csv
import io
from pathlib import PurePosixPath
import zipfile

MAX_FILE_BYTES = 100 * 1024 * 1024

def display_name(filename):
    name = (filename or "").replace("\\", "/").split("/")[-1]
    if not name or name.startswith("~$") or len(name) > 240 or any(ord(c) < 32 for c in name):
        raise ValueError("Invalid or temporary filename")
    return name

def checked_zip(data, *, profile=False):
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        entries = archive.infolist()
        if not entries or len(entries) > 2000 or sum(e.file_size for e in entries) > 200 * 1024 * 1024:
            raise ValueError("ZIP expanded size or member count exceeds limit")
        names = [e.filename for e in entries]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP members are not allowed")
        for entry in entries:
            path = PurePosixPath(entry.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in entry.filename or ":" in entry.filename or entry.flag_bits & 1:
                raise ValueError("Unsafe or encrypted ZIP member")
        expected = {"manifest.json", "states.csv"} if profile else {"[Content_Types].xml", "xl/workbook.xml"}
        if not expected <= set(names) or (profile and set(names) != expected):
            raise ValueError("Required ZIP contents are missing")
        return archive
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("Invalid ZIP/XLSX file") from exc

def validate_upload(data, filename):
    name = display_name(filename)
    if not data or len(data) > MAX_FILE_BYTES:
        raise ValueError("File must contain data and be at most 100 MiB")
    suffix = PurePosixPath(name).suffix.lower()
    if suffix == ".xlsx":
        with checked_zip(data):
            pass
        return name, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if suffix != ".csv":
        raise ValueError("Only CSV and XLSX measurement files are supported")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = data.decode("cp949")
        except UnicodeDecodeError as exc:
            raise ValueError("CSV must use UTF-8 or CP949 encoding") from exc
    if "\x00" in text:
        raise ValueError("CSV contains binary data")
    try:
        from itertools import islice
        header = next((row for row in islice(csv.reader(io.StringIO(text)), 100) if len(row) >= 2), [])
    except csv.Error as exc:
        raise ValueError("Invalid CSV") from exc
    if len(header) < 2:
        raise ValueError("CSV must have at least two columns")
    return name, "text/csv"
