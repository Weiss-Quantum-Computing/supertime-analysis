#!/usr/bin/env python3
"""Experimental walker for LabVIEW 6.x object heaps (FPHP / BDHP sections, "HeapVerP").

Observed layout (big-endian):
  0x00 I32 8, 'BDHP'/'FPHP'            wrapper written by pylabview dump
  0x08 I32 0x44 ?, I32 runtime ptr, I32 0x38 (header len), I32 total, I32 total, ...
  0x38 objects: [I32 size][I32 heapnum][I32 classid][payload ...]  repeated
  references inside payloads are (object start + 0xC), i.e. they point at the payload.

usage: lvheap6.py <x_BDHP.bin> [--raw]
"""
import struct
import sys

HDR = 0x38


def load(path):
    buf = open(path, "rb").read()
    objs = []            # (start, size, heapnum, cls, payload words)
    starts = {}
    pos = HDR
    while pos + 12 <= len(buf):
        size, hn, cls = struct.unpack_from(">III", buf, pos)
        if size < 12 or pos + size > len(buf):
            break
        pay = buf[pos + 12:pos + size]
        objs.append((pos, size, hn, cls, pay))
        starts[pos + 0xC] = len(objs) - 1
        pos += size
    return buf, objs, starts, pos


def is_runtime_ptr(w):
    # little-endian x86 user-space pointers like 0x7ff952f8 stored as f852f97f
    le = struct.unpack("<I", struct.pack(">I", w))[0]
    return 0x00400000 <= le <= 0x7fffffff and (w & 0xff) != 0 and (w >> 24) != 0


def describe_word(w, starts, idx):
    if w in starts:
        return "->#%d" % starts[w]
    if is_runtime_ptr(w):
        return "ptr"
    if w == 0:
        return "0"
    if w & 0x80000000:
        return "%d" % struct.unpack(">i", struct.pack(">I", w))[0]
    return "0x%x" % w


def dump(path, raw=False):
    buf, objs, starts, end = load(path)
    print("%s: %d objects, parsed to 0x%x of 0x%x" % (path, len(objs), end, len(buf)))
    for i, (st, size, hn, cls, pay) in enumerate(objs):
        words = []
        nwords = len(pay) // 4
        for k in range(nwords):
            w = struct.unpack_from(">I", pay, 4 * k)[0]
            words.append(describe_word(w, starts, i))
        tail = pay[4 * nwords:]
        line = "#%-4d @0x%04x cls=0x%02x hn=%d size=%-4d  %s" % (i, st, cls, hn, size, " ".join(words))
        if tail:
            line += "  tail=%s" % tail.hex()
        if raw:
            line += "\n       raw=" + pay.hex()
        print(line)


if __name__ == "__main__":
    dump(sys.argv[1], raw="--raw" in sys.argv)
