# -*- coding: utf-8 -*-
"""Read and write Supertime .dt4 sequence files (LabVIEW 6.1 flattened data).

Runs on Python 2.7 and Python 3, standard library only.  The record type descriptor
(record.td, taken from a supertime*.log header) describes the data cluster; this module
parses it and uses it to unflatten/flatten the file bytes.  See FORMAT_NOTES.md.
"""
from __future__ import print_function, division
import os
import struct
import sys

PY2 = sys.version_info[0] == 2

TYPE_NAMES = {
    0x00: "void", 0x01: "I8", 0x02: "I16", 0x03: "I32", 0x04: "I64",
    0x05: "U8", 0x06: "U16", 0x07: "U32", 0x08: "U64",
    0x09: "SGL", 0x0A: "DBL", 0x0B: "EXT",
    0x15: "enumU8", 0x16: "enumU16", 0x17: "enumU32",
    0x21: "bool", 0x30: "string", 0x32: "path",
    0x40: "array", 0x50: "cluster", 0xF1: "typedef",
}

# Supertime writes "no change" as a NaN with every bit set
FILE_NAN = struct.unpack(">d", b"\xff" * 8)[0]


def is_nan(x):
    return x != x


class TD(object):
    """One node of a LabVIEW type descriptor tree."""

    def __init__(self, code, label=None):
        self.code = code
        self.label = label
        self.children = []
        self.dims = 0
        self.enum_items = []
        self.typedef_name = None

    def kind(self):
        return TYPE_NAMES.get(self.code, "0x%02x" % self.code)


def _pstr(buf, pos):
    n = buf[pos]
    return bytes(buf[pos + 1:pos + 1 + n]).decode("latin-1"), pos + 1 + n


def parse_td(buf, pos=0):
    """Parse one type descriptor at buf[pos] (buf is a bytearray); return (TD, end)."""
    length, code = struct.unpack_from(">HH", buf, pos)
    end = pos + length
    has_label = bool(code & 0x4000)
    low = code & 0xFF
    p = pos + 4
    td = TD(low)
    if low == 0xF1:
        p += 4
        td.typedef_name, p = _pstr(buf, p)
        if p & 1:
            p += 1
        inner, p = parse_td(buf, p)
        td.children = [inner]
    elif low == 0x40:
        (nd,) = struct.unpack_from(">H", buf, p)
        p += 2
        td.dims = nd
        p += 4 * nd
        elem, p = parse_td(buf, p)
        td.children = [elem]
    elif low == 0x50:
        (n,) = struct.unpack_from(">H", buf, p)
        p += 2
        for _ in range(n):
            c, p = parse_td(buf, p)
            td.children.append(c)
    elif low in (0x15, 0x16, 0x17):
        (n,) = struct.unpack_from(">H", buf, p)
        p += 2
        for _ in range(n):
            s, p = _pstr(buf, p)
            td.enum_items.append(s)
    elif low in (0x30, 0x32):
        p += 4
    if has_label:
        td.label, p = _pstr(buf, p)
    return td, end


def cluster_keys(td):
    """Dict keys used for a cluster's members (member label, de-duplicated with '_')."""
    keys = []
    for i, ch in enumerate(td.children):
        key = ch.label
        if not key and ch.children:
            key = ch.children[0].label
        key = key or ("field%d" % i)
        while key in keys:
            key += "_"
        keys.append(key)
    return keys


# ---------------------------------------------------------------- unflatten
class Reader(object):
    def __init__(self, buf, pos=0):
        self.buf = buf
        self.pos = pos

    def take(self, fmt):
        v = struct.unpack_from(fmt, self.buf, self.pos)
        self.pos += struct.calcsize(fmt)
        return v if len(v) > 1 else v[0]


def _read_path(r):
    tag = bytes(r.buf[r.pos:r.pos + 4])
    if tag != b"PTH0":
        raise ValueError("expected PTH0 at %d, got %r" % (r.pos, tag))
    r.pos += 4
    n = r.take(">i")
    end = r.pos + n
    r.take(">H")          # path type (0 = absolute)
    count = r.take(">H")
    parts = []
    for _ in range(count):
        s, r.pos = _pstr(r.buf, r.pos)
        parts.append(s)
    r.pos = end
    return u"\\".join(parts) if parts else u""


_SCALARS = {0x01: ">b", 0x02: ">h", 0x03: ">i", 0x04: ">q",
            0x05: ">B", 0x06: ">H", 0x07: ">I", 0x08: ">Q",
            0x09: ">f", 0x0A: ">d", 0x21: ">B"}


def unflatten(td, r):
    c = td.code
    if c == 0xF1:
        return unflatten(td.children[0], r)
    if c == 0x50:
        out = {}
        for key, ch in zip(cluster_keys(td), td.children):
            out[key] = unflatten(ch, r)
        return out
    if c == 0x40:
        dims = [r.take(">i") for _ in range(td.dims)]
        elem = td.children[0]
        total = 1
        for d in dims:
            total *= d
        flat = [unflatten(elem, r) for _ in range(total)]

        def shape(lst, ds):
            if len(ds) <= 1:
                return lst
            step = len(lst) // ds[0] if ds[0] else 0
            return [shape(lst[i * step:(i + 1) * step], ds[1:]) for i in range(ds[0])]
        return shape(flat, dims)
    if c == 0x30:
        n = r.take(">i")
        s = bytes(r.buf[r.pos:r.pos + n]).decode("latin-1")
        r.pos += n
        return s
    if c == 0x32:
        return _read_path(r)
    if c in (0x15, 0x16, 0x17):
        v = r.take({0x15: ">B", 0x16: ">H", 0x17: ">I"}[c])
        return td.enum_items[v] if v < len(td.enum_items) else v
    fmt = _SCALARS.get(c)
    if fmt is None:
        raise ValueError("unsupported type 0x%02x" % c)
    v = r.take(fmt)
    return bool(v) if c == 0x21 else v


# ---------------------------------------------------------------- flatten
def _write_path(out, s):
    parts = s.split(u"\\") if s else []
    body = struct.pack(">HH", 0, len(parts))
    for p in parts:
        b = p.encode("latin-1")
        body += struct.pack(">B", len(b)) + b
    out.append(b"PTH0" + struct.pack(">i", len(body)) + body)


def flatten(td, value, out):
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
        b = value.encode("latin-1") if not isinstance(value, bytes) else value
        out.append(struct.pack(">i", len(b)) + b)
        return
    if c == 0x32:
        _write_path(out, value)
        return
    if c in (0x15, 0x16, 0x17):
        idx = td.enum_items.index(value) if not isinstance(value, int) else value
        out.append(struct.pack({0x15: ">B", 0x16: ">H", 0x17: ">I"}[c], idx))
        return
    fmt = _SCALARS[c]
    out.append(struct.pack(fmt, int(value) if c == 0x21 else value))


# ---------------------------------------------------------------- the Supertime record
def find_typedef(td, name):
    if td.code == 0xF1 and td.typedef_name == name:
        return td
    for c in td.children:
        r = find_typedef(c, name)
        if r:
            return r
    return None


def _default_td_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "record.td")


def load_record_td(path=None):
    """The {date, time, data cluster.ctl} record type from record.td (or a supertime*.log header)."""
    with open(path or _default_td_path(), "rb") as f:
        buf = bytearray(f.read(8192))
    start = 0x10 if buf[:4] == bytearray(b"DTLG") else 0
    td, _ = parse_td(buf, start)
    return td


def data_cluster_td(record_td=None):
    return find_typedef(record_td or load_record_td(), "data cluster.ctl")


def dt3_variant(dc):
    """The 2007-2008 .dt3 layout: 'Card #' is a U8 and there is no trailing 'External vi' path."""
    import copy
    v = copy.deepcopy(dc)
    chan = find_typedef(v, "channel.ctl").children[0]
    chan.children[1].code = 0x05
    clus = v.children[0]
    clus.children = [c for c in clus.children if c.label != "External vi"]
    return v


def decode_dt4(path, dc=None):
    """Decode a .dt4/.dt3 file.  Returns (data dict, format name)."""
    dc = dc or data_cluster_td()
    with open(path, "rb") as f:
        buf = bytearray(f.read())
    last_err = None
    for name, t in (("dt4", dc), ("dt3", dt3_variant(dc))):
        r = Reader(buf)
        try:
            data = unflatten(t, r)
        except Exception as e:
            last_err = e
            continue
        if r.pos == len(buf):
            if name == "dt3":
                data["External vi"] = u""
            return data, name
        last_err = ValueError("%s layout consumed %d of %d bytes" % (name, r.pos, len(buf)))
    raise ValueError("could not decode %s: %s" % (path, last_err))


def encode_dt4(data, fmt="dt4", dc=None):
    dc = dc or data_cluster_td()
    if fmt == "dt3":
        dc = dt3_variant(dc)
    out = []
    flatten(dc, data, out)
    return b"".join(out)


def channel_td(dc=None):
    """The channel.ctl cluster type (for enum item lists etc.)."""
    return find_typedef(dc or data_cluster_td(), "channel.ctl").children[0]


def function_types(dc=None):
    """The ramp function names, index order as stored in the file."""
    for ch in channel_td(dc).children:
        if ch.label == "Function type":
            return list(ch.children[0].children[0].enum_items)
    return []
