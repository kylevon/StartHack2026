"""Read-only access to the watched document folder, for any mix of file types.

Text-like files (CSV, TSV, Markdown, JSON, logs, anything that decodes) are read
as text whatever their encoding. Spreadsheets (.xlsx, .xlsm, .xls) are flattened
to rows. PDFs are read page by page: pages with a text layer as text, scanned
pages as images. Photos and scans in any common image format are handed over as
images, downscaled when they are too large for a model to accept.

Everything is local for now. The agent only ever sees paths relative to the
folder root, so swapping the folder for a remote source later means replacing
`snapshot` and the byte-loading here, nothing else.
"""
import base64
import fnmatch
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".tif", ".tiff", ".bmp"}
PASSTHROUGH_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
SHEET_SUFFIXES = {".xlsx", ".xlsm", ".xls"}
ENCODINGS = ("utf-8-sig", "cp1252")  # then latin-1, which never fails
PAGE_CHARS = 30_000  # text returned per read_file call; longer files continue with `offset`
SCAN_PAGES = 4  # scanned PDF pages returned as images per call
MAX_SIDE = 2000  # longest image side, in pixels, sent to the model
MAX_RAW_IMAGE = 3_500_000  # bytes; larger images are re-encoded
MIN_PAGE_TEXT = 40  # a PDF page with fewer characters than this is treated as a scan


class FileError(Exception):
    """A problem the agent can fix by changing its arguments."""


def resolve(root: Path, rel: str) -> Path:
    path = (root / rel.lstrip("/")).resolve()
    if path != root and root not in path.parents:
        raise FileError(f"'{rel}' is outside the document folder.")
    return path


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """Every file under root as {relative path: (size, mtime_ns)}."""
    out = {}
    if not root.is_dir():
        return out
    for path in root.rglob("*"):
        if path.is_file():
            stat = path.stat()
            out[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return out


def list_files(root: Path, folder: str = "", pattern: str = "*", limit: int = 300) -> str:
    base = resolve(root, folder)
    if not base.is_dir():
        raise FileError(f"'{folder}' is not a folder. Call list_files with folder='' to see the top level.")
    rels = sorted(p.relative_to(root).as_posix() for p in base.rglob("*") if p.is_file())
    rels = [r for r in rels if fnmatch.fnmatch(Path(r).name, pattern) or fnmatch.fnmatch(r, pattern)]
    if not rels:
        return f"No files match pattern '{pattern}' under '{folder or '.'}'."
    lines = [f"{r}  ({(root / r).stat().st_size:,} bytes)" for r in rels[:limit]]
    if len(rels) > limit:
        lines.append(f"... {len(rels) - limit} more. Narrow with folder= or pattern=.")
    return f"{len(rels)} files:\n" + "\n".join(lines)


# ----- turning files into text -----
def _decode(data: bytes, rel: str) -> str:
    if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise FileError(f"'{rel}' is a binary file of a type read_file cannot open. It opens text, CSV, Excel, PDF and image files.")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):  # UTF-16 with a byte-order mark, as Excel's "Unicode text" export writes
        return data.decode("utf-16", errors="replace")
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _rows(title: str, rows) -> list[str]:
    out = [f"## Sheet: {title}"]
    for row in rows:
        if any(cell not in (None, "") for cell in row):
            out.append(" | ".join("" if cell is None else str(cell) for cell in row))
    return out


def _sheet_text(path: Path) -> str:
    parts = []
    if path.suffix.lower() == ".xls":
        import xlrd

        book = xlrd.open_workbook(path)
        for sheet in book.sheets():
            parts += _rows(sheet.name, (sheet.row_values(i) for i in range(sheet.nrows)))
    else:
        from openpyxl import load_workbook

        book = load_workbook(path, read_only=True, data_only=True)
        for sheet in book.worksheets:
            parts += _rows(sheet.title, sheet.iter_rows(values_only=True))
    return "\n".join(parts)


_text_cache: dict[tuple[str, int], str] = {}


def searchable_text(path: Path) -> str:
    """All the text that can be extracted from a file without looking at it as an image. Cached per file version."""
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _text_cache:
        suffix = path.suffix.lower()
        try:
            if suffix == ".pdf":
                import pymupdf as fitz

                with fitz.open(path) as doc:
                    text = "\n".join(page.get_text() for page in doc)
            elif suffix in SHEET_SUFFIXES:
                text = _sheet_text(path)
            elif suffix in IMAGE_SUFFIXES:
                text = ""
            else:
                text = _decode(path.read_bytes(), path.name)
        except Exception:  # an unreadable file is simply not searchable
            text = ""
        _text_cache[key] = text
    return _text_cache[key]


def search_files(root: Path, query: str, folder: str = "", limit: int = 60) -> str:
    """Case-insensitive substring search over file names and all extractable text."""
    base = resolve(root, folder)
    needle = query.lower()
    hits = []
    for path in sorted(base.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if needle in rel.lower():
            hits.append(f"{rel}: (file name matches)")
        for n, line in enumerate(searchable_text(path).splitlines(), 1):
            if needle in line.lower():
                hits.append(f"{rel}:{n}: {line.strip()[:300]}")
        if len(hits) > limit:
            break
    if not hits:
        return f"No match for '{query}'. Text inside photos and scanned pages is not searchable; open those with read_file."
    more = "\n... more matches exist. Narrow the query or the folder." if len(hits) > limit else ""
    return "\n".join(hits[:limit]) + more


# ----- reading one file -----
def _page(text: str, offset: int, rel: str) -> str:
    chunk = text[offset : offset + PAGE_CHARS]
    end = offset + len(chunk)
    if end < len(text):
        chunk += f"\n\n[Showing characters {offset}-{end} of {len(text)}. Call read_file('{rel}', offset={end}) for the rest.]"
    return chunk


def _image_block(data: bytes, mime: str) -> dict:
    return {"type": "image", "base64": base64.b64encode(data).decode(), "mime_type": mime}


def _render(page) -> dict:
    """A PDF page or an image as a JPEG no larger than MAX_SIDE on its longest side."""
    import pymupdf as fitz

    longest = max(page.rect.width, page.rect.height) or 1
    zoom = min(MAX_SIDE / longest, 2.0)  # 2.0 = 144 dpi for a PDF page, enough to read small print
    pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    return _image_block(pixmap.tobytes("jpg", jpg_quality=82), "image/jpeg")


def _read_image(path: Path, rel: str) -> list:
    import pymupdf as fitz

    suffix = path.suffix.lower()
    with fitz.open(path) as doc:
        page = doc[0]
        small = max(page.rect.width, page.rect.height) <= MAX_SIDE and path.stat().st_size <= MAX_RAW_IMAGE
        block = _image_block(path.read_bytes(), PASSTHROUGH_MIME[suffix]) if small and suffix in PASSTHROUGH_MIME else _render(page)
    return [{"type": "text", "text": f"{rel} (image):"}, block]


def _read_pdf(path: Path, rel: str, start: int):
    import pymupdf as fitz

    with fitz.open(path) as doc:
        total = doc.page_count
        if start >= total:
            raise FileError(f"'{rel}' has {total} pages; offset {start} is past the end. For PDFs, offset is a page number starting at 0.")
        blocks, chars, images, i = [], 0, 0, start
        while i < total:
            text = doc[i].get_text().strip()
            if len(text) >= MIN_PAGE_TEXT:
                if chars and chars + len(text) > PAGE_CHARS:
                    break
                blocks.append({"type": "text", "text": f"--- page {i + 1} of {total} ---\n{text}"})
                chars += len(text)
            else:
                if images == SCAN_PAGES:
                    break
                blocks.append({"type": "text", "text": f"--- page {i + 1} of {total}: scanned, shown as an image ---"})
                blocks.append(_render(doc[i]))
                images += 1
            i += 1
        if i < total:
            blocks.append({"type": "text", "text": f"[Showing pages {start + 1}-{i} of {total}. Call read_file('{rel}', offset={i}) for the next pages.]"})
    if not images:
        return "\n\n".join(block["text"] for block in blocks)
    return blocks


def read(root: Path, rel: str, offset: int = 0):
    """Return a file's content: a string, or content blocks when part of it has to be seen as an image."""
    path = resolve(root, rel)
    if not path.is_file():
        raise FileError(f"No file at '{rel}'. Use list_files or search_files to find the path.")
    suffix = path.suffix.lower()
    try:
        if suffix in IMAGE_SUFFIXES:
            return _read_image(path, rel)
        if suffix == ".pdf":
            return _read_pdf(path, rel, offset)
        if suffix in SHEET_SUFFIXES:
            return _page(_sheet_text(path), offset, rel)
    except FileError:
        raise
    except Exception as err:  # damaged or password-protected files, mislabelled extensions
        raise FileError(f"'{rel}' could not be opened as a {suffix} file ({type(err).__name__}: {err}).") from None
    return _page(_decode(path.read_bytes(), rel), offset, rel)
