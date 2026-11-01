"""Tiny, dependency-free PDF text reader (enough for invoice PDFs made by Skia/Chrome, Word, QuickBooks).
Uses `pdftotext` when it exists; otherwise decodes Flate streams and maps glyph ids through each font's ToUnicode table.
Best effort: returns "" when it cannot read a file."""
import re
import shutil
import subprocess
import zlib


def _cmap(txt):
    m = {}
    for blk in re.findall(r"beginbfchar(.*?)endbfchar", txt, re.S):
        for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            m[int(a, 16)] = bytes.fromhex(b).decode("utf-16-be", "ignore")
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", txt, re.S):
        for a, b, c in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            lo, hi, base = int(a, 16), int(b, 16), int(c, 16)
            for i in range(lo, min(hi, lo + 5000) + 1):
                m[i] = chr(base + i - lo)
    return m


def _objects(data):
    objs = {}
    for m in re.finditer(rb"(\d+)\s+\d+\s+obj(.*?)endobj", data, re.S):
        objs[int(m.group(1))] = m.group(2)
    return objs


def _stream(body):
    m = re.search(rb"stream\r?\n(.*?)\r?\nendstream", body, re.S)
    if not m:
        return b""
    raw = m.group(1)
    if b"FlateDecode" in body[: m.start()]:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return b""
    return raw


def _builtin(data):
    objs = _objects(data)
    fonts = {}  # object number of font -> cmap
    for n, body in objs.items():
        if b"/Type" in body and b"/Font" in body and b"/ToUnicode" in body:
            r = re.search(rb"/ToUnicode\s+(\d+)\s+\d+\s+R", body)
            if r and int(r.group(1)) in objs:
                fonts[n] = _cmap(_stream(objs[int(r.group(1))]).decode("latin-1"))
    # font resource name -> cmap (names like /F4 are unique per document for Skia output; first win)
    byname = {}
    for body in objs.values():
        for name, num in re.findall(rb"/(F\d+)\s+(\d+)\s+\d+\s+R", body):
            if int(num) in fonts:
                byname.setdefault(name.decode(), fonts[int(num)])
    out = []
    for n, body in objs.items():
        if b"/Length" not in body or b"stream" not in body:
            continue
        s = _stream(body)
        if b"BT" not in s:
            continue
        txt = s.decode("latin-1")
        cm = {}
        line_y = None
        for tok in re.finditer(r"/(F\d+)\s+[\d.]+\s+Tf|([\d.\-]+)\s+([\d.\-]+)\s+Tm|<([0-9A-Fa-f]+)>\s*Tj|\((.*?)(?<!\\)\)\s*Tj|\[(.*?)\]\s*TJ|T\*|[\d.\-]+\s+[\d.\-]+\s+Td", txt, re.S):
            g = tok.groups()
            if g[0]:
                cm = byname.get(g[0], {})
            elif g[1] is not None:
                y = round(float(g[2]))
                if line_y is not None and y != line_y:
                    out.append("\n")
                line_y = y
            elif g[3]:
                h = g[3]
                step = 4 if len(h) % 4 == 0 else 2
                out.append("".join(cm.get(int(h[i:i + step], 16), chr(int(h[i:i + step], 16)) if step == 2 else "") for i in range(0, len(h), step)))
            elif g[4] is not None:
                out.append(g[4])
            elif g[5] is not None:
                for hx, lit in re.findall(r"<([0-9A-Fa-f]+)>|\((.*?)\)", g[5]):
                    if hx:
                        step = 4 if len(hx) % 4 == 0 else 2
                        out.append("".join(cm.get(int(hx[i:i + step], 16), "") for i in range(0, len(hx), step)))
                    else:
                        out.append(lit)
        out.append("\n")
    return "".join(out)


def pdf_text(path):
    exe = shutil.which("pdftotext")
    if exe:
        try:
            return subprocess.run([exe, "-layout", str(path), "-"], capture_output=True, text=True, timeout=30).stdout
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        with open(path, "rb") as f:
            return _builtin(f.read())
    except OSError:
        return ""
