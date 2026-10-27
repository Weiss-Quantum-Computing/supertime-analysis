#!/usr/bin/env python3
"""LabVIEW 6.1 data-space type map (DSTM) and default data (DFDS).

The DSTM block is one big cluster type descriptor whose members describe the VI's data
space.  Member codes seen: 0x63 (data-space slot: raw I16,I16,I16), 0x83 (wraps another
descriptor), normal types with high-byte flags 0x20/0x40/0x50/0x70/0x78.
The DFDS block holds the flattened default values of the members flagged 0x20, in order.

usage: lvdstm.py <extract dir>   -> prints the top-level members and the decoded defaults
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lvflat import TD, Reader, _pstr, unflatten  # noqa: E402


def parse_td(buf, pos):
    length, code = struct.unpack_from(">HH", buf, pos)
    end = pos + length
    low = code & 0xFF
    td = TD(low)
    td.flags = code >> 8
    td.start = pos
    td.length = length
    p = pos + 4
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
        td.fixed = []
        for _ in range(nd):
            (d,) = struct.unpack_from(">I", buf, p)
            p += 4
            td.fixed.append(d)
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
    elif low == 0x63:
        td.raw = struct.unpack_from(">HHH", buf, p)
        p += 6
    elif low == 0x83:
        inner, p = parse_td(buf, p)
        td.children = [inner]
    if code & 0x4000 and p < end:
        try:
            td.label, p = _pstr(buf, p)
        except Exception:
            pass
    return td, end


def unflatten_ds(td, r):
    """Like lvflat.unflatten but knows fixed-size arrays and the DSTM-only codes."""
    c = td.code
    if c == 0x63:
        return None
    if c == 0x83:
        return None
    if c == 0xF1:
        return unflatten_ds(td.children[0], r)
    if c == 0x50:
        out = []
        for ch in td.children:
            out.append((ch.label, unflatten_ds(ch, r)))
        return out
    if c == 0x40:
        dims = []
        for d in td.fixed:
            if d & 0x80000000:
                dims.append(d & 0x7fffffff)
            else:
                dims.append(r.take(">i"))
        total = 1
        for d in dims:
            total *= d
        elem = td.children[0]
        vals = [unflatten_ds(elem, r) for _ in range(total)]
        return {"dims": dims, "data": vals}
    return unflatten(td, r)


def load(d):
    buf = open(os.path.join(d, "x_DSTM.bin"), "rb").read()
    top, end = parse_td(buf, 0)
    return buf, top


def defaults(d):
    buf, top = load(d)
    dfds = open(os.path.join(d, "x_DFDS.bin"), "rb").read()
    r = Reader(dfds)
    out = []
    for m in top.children:
        if m.flags & 0x20:
            start = r.pos
            try:
                v = unflatten_ds(m, r)
            except Exception as e:
                out.append((m, start, None, "ERR %s" % e))
                break
            out.append((m, start, r.pos, v))
    return out, r.pos, len(dfds), top


def show(td, depth=0):
    s = "  " * depth + "@0x%03x code=0x%02x flags=0x%02x" % (td.start, td.code, td.flags)
    if td.label:
        s += " '%s'" % td.label
    if td.typedef_name:
        s += " <%s>" % td.typedef_name
    if td.code == 0x63:
        s += " raw=%s" % (td.raw,)
    if td.code == 0x40:
        s += " dims=%s" % [hex(x) for x in td.fixed]
    print(s)
    for c in td.children:
        show(c, depth + 1)


if __name__ == "__main__":
    d = sys.argv[1]
    buf, top = load(d)
    for m in top.children:
        show(m)
    out, used, size, _ = defaults(d)
    print("\nDFDS consumed %d of %d" % (used, size))
    for m, a, b, v in out:
        print("  member @0x%03x [%s..%s] %r" % (m.start, hex(a), hex(b) if b else "?", v if not isinstance(v, str) or len(v) < 300 else v[:300]))
