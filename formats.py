"""File formats of Empire at War: the text file (.dat), archives (.meg), Lua table literals, and small XML helpers."""
import re
import struct
import zlib


# --- MasterTextFile .dat ---
# uint32 count; count x (crc32(key), value length, key length) sorted by crc; then the values (UTF-16LE), then the
# keys (ASCII), both in record order.
def read_dat(data):
    (count,) = struct.unpack_from("<I", data, 0)
    records = [struct.unpack_from("<III", data, 4 + 12 * i) for i in range(count)]
    offset = 4 + 12 * count
    values, keys = [], []
    for _, value_len, _ in records:
        values.append(data[offset:offset + 2 * value_len].decode("utf-16-le", "replace"))
        offset += 2 * value_len
    for _, _, key_len in records:
        keys.append(data[offset:offset + key_len].decode("ascii", "replace"))
        offset += key_len
    return dict(zip(keys, values))


def write_dat(texts):
    entries = sorted(((zlib.crc32(k.encode("ascii")), k, v) for k, v in texts.items()), key=lambda e: e[0])
    out = bytearray(struct.pack("<I", len(entries)))
    for crc, key, value in entries:
        out += struct.pack("<III", crc, len(value), len(key))
    for _, _, value in entries:
        out += value.encode("utf-16-le")
    for _, key, _ in entries:
        out += key.encode("ascii")
    return bytes(out)


# --- .meg archives ---
class Meg:
    """An archive's file table (names in upper case, as the game stores them); file contents read on demand."""

    def __init__(self, path):
        self.path = path
        self.files = {}
        with open(path, "rb") as f:
            head = f.read(24)
            a, b = struct.unpack_from("<II", head, 0)
            offset = 8
            if a == 0x8FFFFFFF:                         # version 3 (encrypted): not read
                return
            if a == 0xFFFFFFFF:                         # version 2: a longer header
                a, b = struct.unpack_from("<II", head, 12)
                offset = 20
            f.seek(offset)
            names = []
            for _ in range(a):
                (n,) = struct.unpack("<H", f.read(2))
                names.append(f.read(n).decode("latin-1").upper())
            table = f.read(20 * b)
            for i in range(b):
                crc, index, length, start, name_index = struct.unpack_from("<5I", table, 20 * i)
                if name_index < len(names):
                    self.files[names[name_index]] = (start, length)

    def read(self, name):
        start, length = self.files[name.upper()]
        with open(self.path, "rb") as f:
            f.seek(start)
            return f.read(length)


def write_meg(files):
    """files: [(name inside the archive, e.g. DATA\\ART\\MAPS\\X.TED, bytes)] -> archive bytes (version 1)."""
    files = sorted(((n.upper().encode("ascii"), d) for n, d in files), key=lambda f: zlib.crc32(f[0]))
    names = b"".join(struct.pack("<H", len(n)) + n for n, _ in files)
    offset = 8 + len(names) + 20 * len(files)
    records, blobs = b"", b""
    for i, (name, data) in enumerate(files):
        records += struct.pack("<5I", zlib.crc32(name), i, len(data), offset + len(blobs), i)
        blobs += data
    return struct.pack("<2I", len(files), len(files)) + names + records + blobs


# --- Lua table literals ---
_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<long_comment>--\[(?P<eq1>=*)\[.*?\](?P=eq1)\])
  | (?P<comment>--[^\n]*)
  | (?P<long_string>\[(?P<eq2>=*)\[.*?\](?P=eq2)\])
  | (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<number>0[xX][0-9a-fA-F]+|\d+\.?\d*(?:[eE][-+]?\d+)?|\.\d+)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\.\.|==|~=|<=|>=|[{}\[\]=,;().:#+\-*/<>^%])
""", re.S | re.X)


def _tokens(text):
    pos, out = 0, []
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            pos += 1
            continue
        pos = m.end()
        kind = m.lastgroup
        if kind in ("space", "comment", "long_comment"):
            continue
        value = m.group(kind)
        if kind == "string":
            value = bytes(value[1:-1], "latin-1", "replace").decode("unicode_escape", "replace")
        elif kind == "long_string":
            value = re.sub(r"^\[=*\[\n?|\]=*\]$", "", value)
            kind = "string"
        elif kind == "number":
            value = float(int(value, 16)) if value.lower().startswith("0x") else float(value)
            if value == int(value):
                value = int(value)
        out.append((kind, value))
    return out


class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def value(self):
        kind, v = self.take()
        if kind == "op" and v == "{":
            result = self.table()
        elif kind in ("string", "number"):
            result = v
        elif kind == "op" and v == "-" and self.peek()[0] == "number":
            result = -self.take()[1]
        elif kind == "name":
            result = {"true": True, "false": False, "nil": None}.get(v, v)
            while self.peek() in (("op", "."), ("op", ":")) and self.peek(1)[0] == "name":   # a.b.c
                self.i += 2
            if self.peek() == ("op", "("):                 # a call: skipped
                self.skip_group("(", ")")
                result = None
        elif kind == "op" and v == "(":
            result = self.value()
            self.skip_to(")")
        else:
            result = None
        while self.peek() == ("op", ".."):                 # "a" .. "b"
            self.i += 1
            other = self.value()
            result = (str(result) if result is not None else "") + (str(other) if other is not None else "")
        return result

    def skip_group(self, open_, close):
        depth = 0
        while self.i < len(self.t):
            kind, v = self.take()
            if kind == "op" and v == open_:
                depth += 1
            elif kind == "op" and v == close:
                depth -= 1
                if depth == 0:
                    return

    def skip_to(self, close):
        while self.i < len(self.t) and self.peek() != ("op", close):
            self.i += 1
        self.i += 1

    def table(self):
        out, n = {}, 1
        while self.i < len(self.t):
            kind, v = self.peek()
            if kind == "op" and v == "}":
                self.i += 1
                break
            if kind == "op" and v in (",", ";"):
                self.i += 1
                continue
            if kind == "op" and v == "[":
                self.i += 1
                key = self.value()
                self.skip_to("]")
                self.skip_to("=")
                out[key] = self.value()
            elif kind == "name" and self.peek(1) == ("op", "="):
                self.i += 2
                out[v] = self.value()
            else:
                out[n] = self.value()
                n += 1
        return out


def lua_table(text, name=None):
    """The table literal a Lua file returns (`return {...}`), or the one assigned to `name` (`name = {...}`)."""
    if name:
        m = re.search(r"(?<![A-Za-z0-9_.])" + re.escape(name) + r"\s*=\s*\{", text)
    else:
        m = re.search(r"\breturn\s*\{", text)
        if not m:
            m = re.search(r"\blocal\s+[A-Za-z_]\w*\s*=\s*\{", text)
    if not m:
        return None
    p = _Parser(_tokens(text[m.end() - 1:]))
    p.take()
    return p.table()


def lua_list(t):
    """A Lua array (a dict with keys 1..n) as a Python list."""
    if not isinstance(t, dict):
        return []
    return [t[i] for i in range(1, len(t) + 1) if i in t]


# --- XML ---
def strip_comments(text):
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def tag(body, name):
    m = re.search(r"<" + name + r">\s*([^<]*?)\s*</" + name + ">", body, re.I)
    return m.group(1) if m else None


def set_tag(body, name, value):
    """body with <name>value</name>, replaced where it is or added before the closing tag."""
    new, n = re.subn(r"<" + name + r">[^<]*</" + name + ">", "<" + name + ">" + value + "</" + name + ">", body,
                     count=1, flags=re.I)
    if n:
        return new
    i = body.rfind("</")
    return body[:i] + "\t<" + name + ">" + value + "</" + name + ">\r\n\t" + body[i:]


def file_list(text):
    """The <File> entries of a file list (GameObjectFiles.xml, CampaignFiles.xml, ...), comments left out."""
    return [f.strip() for f in re.findall(r"<File>\s*([^<]*?)\s*</File>", strip_comments(text), re.I)]


def add_files(text, closing, files):
    """text with <File> entries added before the last `closing` tag (those already listed are left out)."""
    have = {f.lower() for f in file_list(text)}
    lines = "".join("\t<File>" + f + "</File>\r\n" for f in files if f.lower() not in have)
    i = text.rindex(closing)
    return text[:i] + lines + text[i:]


def decode(data):
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", "replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")
