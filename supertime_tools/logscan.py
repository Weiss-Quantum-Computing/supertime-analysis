#!/usr/bin/env python3
"""Walk a Supertime datalog (supertime*.log) record by record.

Layout (LabVIEW 6.x datalog, big-endian):
  0x00  'DTLG'            0x04 version (0x06108004)
  0x08  I32 record count  0x0C I32 offset of the master index block
  0x10  type descriptor of one record
  then a 512-byte index block (128 I32 record offsets), then records.
  The master index block holds the offsets of every 128-entry index block.

Each record = {date string, time string, data cluster.ctl} - i.e. the full
sequence (channels, edges, variables) that was running at that moment.

usage: logscan.py <log> [--list | --extract N <out.dt4> | --json N]
"""
import struct
import sys
from lvflat import read_datalog_header, Reader, unflatten, find_typedef


def record_offsets(path):
    td, head = read_datalog_header(path)
    with open(path, "rb") as f:
        hdr = f.read(16)
        nrec, master = struct.unpack_from(">II", hdr, 8)
        f.seek(master)
        blocks = [b for b in struct.unpack(">128I", f.read(512)) if b]
        offs = []
        for b in blocks:
            f.seek(b)
            offs.extend(o for o in struct.unpack(">128I", f.read(512)) if o)
    return td, offs[:nrec]


def read_record(path, td, off, size_hint=4_000_000):
    with open(path, "rb") as f:
        f.seek(off)
        buf = f.read(size_hint)
    r = Reader(buf)
    rec = unflatten(td, r)
    return rec, r.pos


if __name__ == "__main__":
    path = sys.argv[1]
    td, offs = record_offsets(path)
    print("%d records" % len(offs), file=sys.stderr)
    if "--extract" in sys.argv:
        n = int(sys.argv[sys.argv.index("--extract") + 1])
        out = sys.argv[sys.argv.index("--extract") + 2]
        rec, used = read_record(path, td, offs[n])
        # re-flatten is not implemented; instead copy the raw bytes after the two strings
        with open(path, "rb") as f:
            f.seek(offs[n])
            buf = f.read(used)
        r = Reader(buf)
        unflatten(td.children[0], r)
        unflatten(td.children[1], r)
        open(out, "wb").write(buf[r.pos:])
        print("wrote %s (%d bytes) from record %d %s %s" % (out, used - r.pos, n, rec["date string"], rec["time string"]))
        sys.exit()
    if "--json" in sys.argv:
        import json
        n = int(sys.argv[sys.argv.index("--json") + 1])
        rec, _ = read_record(path, td, offs[n])
        print(json.dumps(rec, indent=1))
        sys.exit()
    # default: list
    print("idx   date        time       sequence file                                          edges  vars  cycle(ms)")
    import os
    end = os.path.getsize(path)
    for i, off in enumerate(offs):
        nxt = offs[i + 1] if i + 1 < len(offs) else end
        try:
            rec, used = read_record(path, td, off, size_hint=max(nxt - off, 16) + 4096)
        except Exception as e:
            print("%4d  @%d  ERROR %s" % (i, off, e))
            continue
        dc = rec["Input Cluster"]
        edges = dc["Edge Array"]
        cyc = max((e["Absolute Time (ms)"] for e in edges), default=float("nan"))
        print("%4d  %-10s  %-9s  %-52s %5d %5d  %10.3f" % (
            i, rec["date string"], rec["time string"], dc["File name"][:52], len(edges),
            len(dc["Variable Array"]), cyc))
