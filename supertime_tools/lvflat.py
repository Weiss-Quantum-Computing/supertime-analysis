#!/usr/bin/env python3
"""Decode LabVIEW (classic, pre-8.0) type descriptors and flattened data.

Used for the Supertime experiment-control files:
  * supertime*.log            LabVIEW datalog files ("DTLG" header) whose header
                              carries the type descriptor of each record.
  * *.dt4 / *.dt3             a flattened "data cluster.ctl" (channels, edges,
                              variables, card settings) written by supertime.vi.

Everything is big-endian.  Strings/arrays carry an I32 length/dimension prefix.
"""
import struct
import sys
import json


# ---------------------------------------------------------------- type descriptors
class TD:
    """One node of a LabVIEW type descriptor tree."""

    def __init__(self, code, label=None):
        self.code = code          # low byte of the type code
        self.label = label
        self.children = []        # cluster members / array element
        self.dims = 0             # arrays
        self.enum_items = []      # enums
        self.typedef_name = None  # typedef wrappers (0xF1)

    def kind(self):
        return TYPE_NAMES.get(self.code, "0x%02x" % self.code)

    def pretty(self, indent=0):
        pad = "  " * indent
        s = pad + self.kind()
        if self.typedef_name:
            s += " <%s>" % self.typedef_name
        if self.label:
            s += "  '%s'" % self.label
        if self.enum_items:
            s += "  {" + ", ".join(self.enum_items) + "}"
        if self.code == 0x40:
            s += "  ndims=%d" % self.dims
        out = [s]
        for c in self.children:
            out.append(c.pretty(indent + 1))
        return "\n".join(out)


TYPE_NAMES = {
    0x00: "void", 0x01: "I8", 0x02: "I16", 0x03: "I32", 0x04: "I64",
    0x05: "U8", 0x06: "U16", 0x07: "U32", 0x08: "U64",
    0x09: "SGL", 0x0A: "DBL", 0x0B: "EXT",
    0x15: "enumU8", 0x16: "enumU16", 0x17: "enumU32",
    0x21: "bool", 0x30: "string", 0x32: "path",
    0x40: "array", 0x50: "cluster", 0xF1: "typedef",
}


def _pstr(buf, pos):
    n = buf[pos]
    return buf[pos + 1:pos + 1 + n].decode("latin-1"), pos + 1 + n


def parse_td(buf, pos=0):
    """Parse one type descriptor at buf[pos]; return (TD, pos_after)."""
    (length, code) = struct.unpack_from(">HH", buf, pos)
    end = pos + length
    has_label = bool(code & 0x4000)
    low = code & 0xFF
    p = pos + 4
    td = TD(low)

    if low == 0xF1:                                 # typedef wrapper
        p += 4                                      # flags
        td.typedef_name, p = _pstr(buf, p)
        if p & 1:
            p += 1
        inner, p = parse_td(buf, p)
        td.children = [inner]
    elif low == 0x40:                               # array
        (nd,) = struct.unpack_from(">H", buf, p)
        p += 2
        td.dims = nd
        p += 4 * nd                                 # fixed sizes (always -1 here)
        elem, p = parse_td(buf, p)
        td.children = [elem]
    elif low == 0x50:                               # cluster
        (n,) = struct.unpack_from(">H", buf, p)
        p += 2
        for _ in range(n):
            c, p = parse_td(buf, p)
            td.children.append(c)
    elif low in (0x15, 0x16, 0x17):                 # enum
        (n,) = struct.unpack_from(">H", buf, p)
        p += 2
        for _ in range(n):
            s, p = _pstr(buf, p)
            td.enum_items.append(s)
    elif low in (0x30, 0x32):                       # string / path: I32 max size
        p += 4
    # scalars carry nothing extra

    if has_label:
        td.label, p = _pstr(buf, p)
    return td, end


# ---------------------------------------------------------------- unflatten
class Reader:
    def __init__(self, buf, pos=0):
        self.buf = buf
        self.pos = pos

    def take(self, fmt):
        v = struct.unpack_from(fmt, self.buf, self.pos)
        self.pos += struct.calcsize(fmt)
        return v if len(v) > 1 else v[0]


def _read_path(r):
    tag = r.buf[r.pos:r.pos + 4]
    if tag != b"PTH0":
        raise ValueError("expected PTH0 at %d, got %r" % (r.pos, tag))
    r.pos += 4
    n = r.take(">i")
    end = r.pos + n
    ptype = r.take(">H")
    count = r.take(">H")
    parts = []
    for _ in range(count):
        s, r.pos = _pstr(r.buf, r.pos)
        parts.append(s)
    r.pos = end
    return "\\".join(parts) if parts else ""


def unflatten(td, r):
    c = td.code
    if c == 0xF1:
        return unflatten(td.children[0], r)
    if c == 0x50:
        out = {}
        for i, ch in enumerate(td.children):
            key = ch.label or ch.children[0].label if ch.children else ch.label
            key = key or ("field%d" % i)
            while key in out:
                key += "_"
            out[key] = unflatten(ch, r)
        return out
    if c == 0x40:
        dims = [r.take(">i") for _ in range(td.dims)]
        elem = td.children[0]
        total = 1
        for d in dims:
            total *= d
        flat = [unflatten(elem, r) for _ in range(total)]
        # reshape (row-major)
        def shape(lst, ds):
            if len(ds) <= 1:
                return lst
            step = len(lst) // ds[0] if ds[0] else 0
            return [shape(lst[i * step:(i + 1) * step], ds[1:]) for i in range(ds[0])]
        return shape(flat, dims)
    if c == 0x30:
        n = r.take(">i")
        s = r.buf[r.pos:r.pos + n].decode("latin-1")
        r.pos += n
        return s
    if c == 0x32:
        return _read_path(r)
    if c in (0x15, 0x16, 0x17):
        fmt = {0x15: ">B", 0x16: ">H", 0x17: ">I"}[c]
        v = r.take(fmt)
        return td.enum_items[v] if v < len(td.enum_items) else v
    fmt = {0x01: ">b", 0x02: ">h", 0x03: ">i", 0x04: ">q",
           0x05: ">B", 0x06: ">H", 0x07: ">I", 0x08: ">Q",
           0x09: ">f", 0x0A: ">d", 0x21: ">B"}.get(c)
    if fmt is None:
        raise ValueError("unsupported type 0x%02x" % c)
    v = r.take(fmt)
    return bool(v) if c == 0x21 else v


# ---------------------------------------------------------------- datalog files
def read_datalog_header(path):
    """Return (record TD, header bytes) for a DTLG file."""
    with open(path, "rb") as f:
        head = f.read(4096)
    if head[:4] != b"DTLG":
        raise ValueError("not a DTLG file")
    td, end = parse_td(head, 0x10)
    return td, head[:end]


def find_typedef(td, name):
    if td.code == 0xF1 and td.typedef_name == name:
        return td
    for c in td.children:
        r = find_typedef(c, name)
        if r:
            return r
    return None


def dt3_variant(dc):
    """The 2007-2008 .dt3 layout: 'Card #' is a U8 and there is no trailing 'External vi' path."""
    import copy
    v = copy.deepcopy(dc)
    chan = find_typedef(v, "channel.ctl").children[0]
    chan.children[1].code = 0x05            # Card #: U16 -> U8
    clus = v.children[0]
    clus.children = [c for c in clus.children if c.label != "External vi"]
    return v


def decode_dt4(path, record_td):
    """Decode a .dt4/.dt3 (flattened data cluster.ctl) with the typedef taken from a log TD.

    Returns (data, bytes_consumed, file_size).  Tries the current layout first and
    falls back to the older .dt3 layout; data['_format'] says which one matched.
    """
    dc = find_typedef(record_td, "data cluster.ctl")
    with open(path, "rb") as f:
        buf = f.read()
    last_err = None
    for name, t in (("dt4", dc), ("dt3", dt3_variant(dc))):
        r = Reader(buf)
        try:
            data = unflatten(t, r)
        except Exception as e:          # struct/ValueError: wrong layout or truncated file
            last_err = e
            continue
        if r.pos == len(buf):
            data["_format"] = name
            if name == "dt3":
                data["External vi"] = ""
            return data, r.pos, len(buf)
        last_err = ValueError("%s layout consumed %d of %d bytes" % (name, r.pos, len(buf)))
    raise ValueError("could not decode %s: %s" % (path, last_err))


# ---------------------------------------------------------------- flatten (encoder)
def cluster_keys(td):
    """The dict keys unflatten() produces for a cluster's members, in member order."""
    keys = []
    for i, ch in enumerate(td.children):
        key = ch.label or ch.children[0].label if ch.children else ch.label
        key = key or ("field%d" % i)
        while key in keys:
            key += "_"
        keys.append(key)
    return keys


def _write_path(out, s):
    parts = s.split("\\") if s else []
    body = struct.pack(">HH", 0, len(parts))
    for p in parts:
        b = p.encode("latin-1")
        body += bytes([len(b)]) + b
    out.append(b"PTH0" + struct.pack(">i", len(body)) + body)


def flatten(td, value, out):
    """Inverse of unflatten(): append the big-endian flattened bytes of `value` to list `out`."""
    c = td.code
    if c == 0xF1:
        return flatten(td.children[0], value, out)
    if c == 0x50:
        for key, ch in zip(cluster_keys(td), td.children):
            flatten(ch, value[key], out)
        return
    if c == 0x40:
        elem = td.children[0]
        dims = []
        v = value
        for _ in range(td.dims):
            dims.append(len(v))
            v = v[0] if v else []
        out.append(struct.pack(">%di" % td.dims, *dims))

        def walk(lst, depth):
            if depth == td.dims - 1:
                for x in lst:
                    flatten(elem, x, out)
            else:
                for sub in lst:
                    walk(sub, depth + 1)
        walk(value, 0)
        return
    if c == 0x30:
        b = value.encode("latin-1")
        out.append(struct.pack(">i", len(b)) + b)
        return
    if c == 0x32:
        _write_path(out, value)
        return
    if c in (0x15, 0x16, 0x17):
        fmt = {0x15: ">B", 0x16: ">H", 0x17: ">I"}[c]
        idx = td.enum_items.index(value) if isinstance(value, str) else int(value)
        out.append(struct.pack(fmt, idx))
        return
    fmt = {0x01: ">b", 0x02: ">h", 0x03: ">i", 0x04: ">q",
           0x05: ">B", 0x06: ">H", 0x07: ">I", 0x08: ">Q",
           0x09: ">f", 0x0A: ">d", 0x21: ">B"}[c]
    out.append(struct.pack(fmt, int(value) if c == 0x21 else value))


def encode_dt4(data, record_td):
    """Flatten a decoded sequence (as returned by decode_dt4) back into .dt4 bytes."""
    dc = find_typedef(record_td, "data cluster.ctl")
    if data.get("_format") == "dt3":
        dc = dt3_variant(dc)
    out = []
    flatten(dc, data, out)
    return b"".join(out)


if __name__ == "__main__":
    log = sys.argv[1]
    td, _ = read_datalog_header(log)
    if len(sys.argv) == 2:
        print(td.pretty())
        sys.exit(0)
    for p in sys.argv[2:]:
        data, used, size = decode_dt4(p, td)
        print("%s: consumed %d of %d bytes%s" % (p, used, size, "" if used == size else "  <-- MISMATCH"))
        if "--json" in sys.argv:
            print(json.dumps(data, indent=1)[:4000])
