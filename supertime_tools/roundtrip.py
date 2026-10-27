#!/usr/bin/env python3
"""Decode every .dt4/.dt3 under a folder and re-encode it; report any byte difference.

usage: roundtrip.py <supertime.log or .head> <folder> [<folder> ...]
"""
import os
import sys
from lvflat import read_datalog_header, decode_dt4, encode_dt4

td, _ = read_datalog_header(sys.argv[1])
ok = bad = 0
for folder in sys.argv[2:]:
    for root, _, files in os.walk(folder):
        for f in sorted(files):
            if not f.lower().endswith((".dt4", ".dt3")):
                continue
            p = os.path.join(root, f)
            try:
                data, used, size = decode_dt4(p, td)
            except Exception as e:
                print("DECODE FAIL %s: %s" % (p, e))
                bad += 1
                continue
            raw = open(p, "rb").read()
            enc = encode_dt4(data, td)
            if enc == raw:
                ok += 1
            else:
                bad += 1
                n = next((i for i in range(min(len(raw), len(enc))) if raw[i] != enc[i]), min(len(raw), len(enc)))
                print("MISMATCH %s: first diff at %d (orig %d bytes, enc %d bytes) orig=%s enc=%s"
                      % (p, n, len(raw), len(enc), raw[n:n + 16].hex(), enc[n:n + 16].hex()))
print("identical: %d   differing/failed: %d" % (ok, bad))
