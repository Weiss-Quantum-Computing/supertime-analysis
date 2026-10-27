#!/usr/bin/env python3
"""Reconstruct a readable block-diagram netlist from a LabVIEW 6.1 VI extracted by pylabview.

usage: lvdiagram6.py <extract dir containing x_BDHP.bin, x_FPHP.bin, x_TRec*.bin, x.xml>

Reverse-engineered layout (big-endian, see FORMAT_NOTES.md):
  heap record   [I32 size][I32 chunk][I32 class][payload words]   from offset 0x38
  reference     payload word == (record start + 0xC) of the target record
  class 0x07    pointer list: [count][ptr...]
  class 0x1b    diagram: w2 node list, w3 ?, w4 wire list, w5 bg colour
  class 0x1d    diagram's FP-terminal/constant holder: w1 diagram, w2 list
  class 0x15    terminal: w1 owner, w2 wire, w3 descriptor, w4 visual (self or 0x16)
  class 0x16    front-panel terminal: w3 = offset of DCO (0x12) in the FPHP heap, w8 label
  class 0x17    wire: w1 diagram, w2 terminal list
  class 0x13    diagram constant (DCO): w1 0x1d, w2 terminal list, w5 display object
  class 0x0a    text label: w1 owner, w4/w5 bounds (top<<16|left, bottom<<16|right)
  node classes  w0 flags, w1 diagram, w2 terminal list, w3 label, w4/w5 bounds
  class 0x31    subVI call (label text = VI name), 0x2f primitive (w9 low 16 bits = prim id)
  class 0x20/0x21 For/While loop, 0x2c Case, 0x29 Sequence: a list field holds sub-diagrams
"""
import glob
import os
import re
import struct
import sys
import xml.etree.ElementTree as ET

HDR = 0x38

NODE_NAMES = {
    0x16: "FPterm", 0x2f: "prim", 0x31: "subVI", 0x32: "LocalVar", 0x20: "ForLoop",
    0x21: "WhileLoop", 0x2c: "Case", 0x29: "Sequence", 0x44: "IndexArray?", 0x48: "node48",
    0x4a: "node4a", 0x63: "(Un)BundleByName?", 0x93: "FormatString?", 0x8c: "PropertyNode", 0xa9: "node a9",
    0xc5: "nodec5", 0x34: "node34", 0x36: "node36", 0x3a: "node3a", 0x3c: "node3c",
    0x3e: "node3e", 0x40: "node40", 0x42: "node42", 0x6c: "node6c", 0x92: "node92",
    0xae: "nodeae", 0xb9: "nodeb9", 0xbb: "nodebb", 0xbd: "nodebd", 0x13: "const",
}
CONST_DISPLAY = {0x50: "numeric", 0x51: "string", 0x52: "array", 0x57: "enum/ring",
                 0x5b: "bool", 0x4f: "path?", 0x64: "cluster", 0x53: "cluster?", 0x94: "refnum?"}
STRUCT_CLASSES = {0x20, 0x21, 0x2c, 0x29}

# primitive names: the high half of a primitive node's last word is a 'CURS' string resource id in
# LabVIEW 6.1's resource/labview.rsc (table extracted to lv61_strings.json next to this script)
try:
    import json as _json
    _CURS = _json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lv61_strings.json")))["CURS"]
except Exception:
    _CURS = {}


def prim_name(w9):
    import html
    return html.unescape(_CURS.get(str(w9 >> 16), "prim#%d" % (w9 & 0xffff)))


class Heap:
    def __init__(self, path):
        self.buf = open(path, "rb").read()
        self.objs = {}            # payload offset -> (cls, words)
        self.order = []
        pos = HDR
        while pos + 12 <= len(self.buf):
            size, chunk, cls = struct.unpack_from(">III", self.buf, pos)
            if size < 12 or pos + size > len(self.buf):
                break
            n = (size - 12) // 4
            words = struct.unpack_from(">%dI" % n, self.buf, pos + 12)
            self.objs[pos + 0xC] = (cls, words)
            self.order.append(pos + 0xC)
            pos += size

    def cls(self, ref):
        o = self.objs.get(ref)
        return o[0] if o else None

    def words(self, ref):
        o = self.objs.get(ref)
        return o[1] if o else ()

    def lst(self, ref):
        """Elements of a 0x07 pointer list."""
        if self.cls(ref) != 0x07:
            return []
        w = self.words(ref)
        n = w[0] if w else 0
        return [x for x in w[1:1 + n] if x in self.objs]

    def by_class(self, c):
        return [r for r in self.order if self.objs[r][0] == c]


def rect(w4, w5):
    return (w4 >> 16, w4 & 0xffff, w5 >> 16, w5 & 0xffff)


def s16(v):
    return v - 0x10000 if v >= 0x8000 else v


class VI:
    def __init__(self, d):
        self.d = d
        self.bd = Heap(os.path.join(d, "x_BDHP.bin"))
        self.fp = Heap(os.path.join(d, "x_FPHP.bin")) if os.path.exists(os.path.join(d, "x_FPHP.bin")) else None
        self.trecs = []
        for f in glob.glob(os.path.join(d, "x_TRec*.bin")):
            b = open(f, "rb").read()
            if len(b) <= 0x4c:
                continue
            n = b[0x4b]
            txt = b[0x4c:0x4c + n].decode("latin-1")
            r = struct.unpack_from(">4h", b, 0x0c)
            self.trecs.append((r, txt, b[4:8].hex()))
        self.name = os.path.basename(os.path.abspath(d))
        self.subvis = []
        x = os.path.join(d, "x.xml")
        if os.path.exists(x):
            try:
                t = ET.parse(x).getroot()
                ti = t.find("TITL/Section/String")
                if ti is not None and ti.text and ti.text.strip():
                    self.name = ti.text
            except ET.ParseError:
                pass

    # ---- text lookup
    def label_text(self, heap, ref):
        if heap.cls(ref) != 0x0a:
            return None
        w = heap.words(ref)
        t, l, b, r = rect(w[4], w[5])
        t, l, b, r = s16(t), s16(l), s16(b), s16(r)
        hits = [txt for (rr, txt, fl) in self.trecs
                if abs(rr[0] - t) <= 1 and abs(rr[1] - l) <= 1 and abs(rr[2] - b) <= 1 and abs(rr[3] - r) <= 1]
        if hits:
            return hits[0]
        return None

    def fp_control_name(self, fp_off):
        """Name of the front-panel control whose DCO (0x12) payload sits at fp_off in the FPHP heap."""
        if not self.fp or self.fp.cls(fp_off) != 0x12:
            return None
        ctl = self.fp.words(fp_off)[5]
        ccls = self.fp.cls(ctl)
        name = None
        # the control's parts list is word 6 for most control classes; search any list field
        for w in self.fp.words(ctl):
            if self.fp.cls(w) == 0x07:
                for p in self.fp.lst(w):
                    if self.fp.cls(p) == 0x0a:
                        txt = self.label_text(self.fp, p)
                        if txt:
                            name = txt
                            break
            if name:
                break
        return name, ccls

    # ---- connector pane of a callee (from its CPTM block, if that VI was extracted next to this one)
    _cp_cache = {}

    def conpane_names(self, viname):
        if viname in self._cp_cache:
            return self._cp_cache[viname]
        names = []
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", viname)
        cand = os.path.join(os.path.dirname(os.path.abspath(self.d)), safe, "x_CPTM.bin")
        if os.path.exists(cand):
            b = open(cand, "rb").read()
            n = struct.unpack_from(">H", b, 4)[0] if len(b) >= 6 else 0
            # type descriptors follow a short header; find a start that tiles the block exactly
            for start in range(6, min(len(b), 40), 2):
                pos, labs = start, []
                try:
                    while pos + 4 <= len(b):
                        ln, code = struct.unpack_from(">HH", b, pos)
                        if ln < 4 or pos + ln > len(b):
                            raise ValueError
                        td = b[pos:pos + ln]
                        # label = trailing pascal string of this descriptor
                        lab = ""
                        if code & 0x4000:
                            k = td[-1]
                            if td[-1] == 0 and len(td) > 2:   # padding byte
                                k = td[-2 - td[-2]] if False else None
                            # scan back: last pascal string whose length fits
                            for L in range(1, min(200, ln - 4)):
                                if ln - 1 - L >= 4 and td[ln - 1 - L] == L and all(32 <= c < 127 or c in (9, 10, 13) for c in td[ln - L:ln]):
                                    lab = td[ln - L:ln].decode("latin-1")
                                    break
                                if ln - 2 - L >= 4 and td[ln - 2 - L] == L and td[-1] == 0 and all(32 <= c < 127 or c in (9, 10, 13) for c in td[ln - 1 - L:ln - 1]):
                                    lab = td[ln - 1 - L:ln - 1].decode("latin-1")
                                    break
                        labs.append(lab)
                        pos += ln
                    if pos == len(b) and (n == 0 or len(labs) == n):
                        names = labs
                        break
                except ValueError:
                    continue
        self._cp_cache[viname] = names
        return names

    # ---- diagram model
    def node_label(self, ref):
        w = self.bd.words(ref)
        if len(w) > 3 and self.bd.cls(w[3]) == 0x0a:
            return self.label_text(self.bd, w[3])
        return None

    def describe_node(self, ref):
        cls = self.bd.cls(ref)
        w = self.bd.words(ref)
        kind = NODE_NAMES.get(cls, "cls%02x" % cls)
        extra = ""
        if cls == 0x16:
            r = self.fp_control_name(w[3]) if self.fp else None
            if r and r[0]:
                extra = "'%s'" % r[0]
            else:
                extra = "(fp@0x%x)" % w[3]
        elif cls == 0x31:
            extra = "'%s'" % (self.node_label(ref) or "?")
        elif cls == 0x32:
            # local variable: terminal descriptor (0x67) word 3 = FPHP offset of the control's DCO
            name = None
            for t in self.terminals(ref):
                d = self.bd.words(t)[3]
                if self.bd.cls(d) == 0x67 and self.fp:
                    r = self.fp_control_name(self.bd.words(d)[3])
                    if r and r[0]:
                        name = r[0]
            extra = "'%s'" % (name or "?")
        elif cls == 0x8c:
            nprops = len(self.bd.lst(w[11])) if len(w) > 11 else 0
            extra = "'%s' [%d props]" % (self.node_label(ref) or "?", nprops)
        elif cls == 0x2f:
            extra = "'%s'" % prim_name(w[9])
        elif cls == 0x13:
            disp = w[5]
            dc = self.bd.cls(disp)
            extra = CONST_DISPLAY.get(dc, "cls%02x" % dc) if dc is not None else "?"
            # a constant's displayed text, when stored as a text record
            for x in self.bd.words(disp):
                if self.bd.cls(x) == 0x07:
                    for p in self.bd.lst(x):
                        txt = self.label_text(self.bd, p)
                        if txt:
                            extra += " '%s'" % txt
                            break
        else:
            lab = self.node_label(ref)
            if lab:
                extra = "'%s'" % lab
        if cls == 0x31:
            params = self.conpane_names(self.node_label(ref) or "")
            if params:
                extra += "  params: " + ", ".join("%d=%s" % (i, n) for i, n in enumerate(params))
        if cls not in (0x16, 0x13) and len(w) > 5:
            t, l, b, r = rect(w[4], w[5])
            extra += " @(%d,%d)" % (s16(l), s16(t))
        return kind, extra

    def terminals(self, ref):
        """Terminal objects of a node, in list order (0x15 terminals; a 0x16 FP terminal is its own terminal)."""
        if self.bd.cls(ref) == 0x16:
            return [ref]
        w = self.bd.words(ref)
        if len(w) > 2:
            return [t for t in self.bd.lst(w[2]) if self.bd.cls(t) == 0x15]
        return []

    def border_terminals(self, ref):
        """All 0x15 terminals owned by a node (structures: tunnels, i, N, shift registers, selector)."""
        return [t for t in self.bd.by_class(0x15) if self.bd.words(t)[1] == ref]

    DESC_NAMES = {0x22: "tunnel", 0x23: "tunnel", 0x24: "i", 0x26: "N", 0x25: "cond", 0x2d: "tunnel",
                  0x2e: "selector", 0x2a: "tunnel", 0x27: "shiftreg", 0x28: "shiftreg", 0x2b: "seq"}

    def term_name(self, t, owner_id, idx):
        """Name a terminal: index for ordinary nodes, descriptor-based for structure borders."""
        w = self.bd.words(t)
        d = w[3] if len(w) > 3 else 0
        dc = self.bd.cls(d)
        if dc == 0x33:
            ci = self.bd.words(d)[9]
            params = self.conpane_names(self.node_label(w[1]) or "")
            if ci < len(params) and params[ci]:
                return "%s.%s" % (owner_id, params[ci])
            return "%s.%d" % (owner_id, ci)
        if dc in self.DESC_NAMES:
            dw = self.bd.words(d)
            side = "in" if self.bd.cls(w[1]) == 0x1d else "out"
            if dc in (0x24, 0x26, 0x25, 0x2e):
                return "%s.%s" % (owner_id, self.DESC_NAMES[dc])
            r = rect(dw[5], dw[6]) if len(dw) > 6 else (0, 0, 0, 0)
            return "%s.%s@(%d,%d).%s" % (owner_id, self.DESC_NAMES[dc], s16(r[1]), s16(r[0]), side)
        return "%s.%d" % (owner_id, idx)

    def subdiagrams(self, ref):
        if self.bd.cls(ref) not in STRUCT_CLASSES:
            return []
        w = self.bd.words(ref)
        if len(w) > 13 and self.bd.cls(w[13]) == 0x07:
            return [e for e in self.bd.lst(w[13]) if self.bd.cls(e) == 0x1b]
        return []

    def dump(self, out=sys.stdout):
        bd = self.bd
        roots = bd.by_class(0x7e)
        top = bd.words(roots[0])[0] if roots else None
        if bd.cls(top) != 0x1b:
            diags = bd.by_class(0x1b)
            top = diags[0] if diags else None
        # index terminals -> owner node
        self.term_owner = {}
        self.node_ids = {}
        self.inner_terms = {}
        self.counter = 0
        # group structure-border terminals by the structure node their descriptor belongs to
        self.terms_by_struct = {}
        for t in bd.by_class(0x15):
            d = bd.words(t)[3]
            if bd.cls(d) in self.DESC_NAMES:
                self.terms_by_struct.setdefault(bd.words(d)[1], []).append(t)
        print("VI: %s" % self.name, file=out)
        if top is None:
            print("  (no diagram)", file=out)
            return
        self._dump_diagram(top, 1, out)

    def _nodes_of(self, diag):
        w = self.bd.words(diag)
        nodes = [n for n in self.bd.lst(w[2]) if self.bd.cls(n) not in (0x15, 0x0a)] if len(w) > 2 else []
        # constants and FP terminals hang off the 0x1d holder(s) of this diagram
        for h in self.bd.by_class(0x1d):
            if self.bd.words(h)[1] == diag:
                for n in self.bd.lst(self.bd.words(h)[2]):
                    if self.bd.cls(n) == 0x15:
                        self.inner_terms[n] = diag      # inner side of a structure border terminal
                    elif n not in nodes:
                        nodes.append(n)
        for c in self.bd.by_class(0x13):
            if self.bd.words(c)[1] in self.bd.by_class(0x1d) and self.bd.words(self.bd.words(c)[1])[1] == diag:
                if c not in nodes:
                    nodes.append(c)
        return nodes

    def _dump_diagram(self, diag, depth, out):
        pad = "  " * depth
        nodes = self._nodes_of(diag)
        # free labels (comments) owned by the diagram
        for lab in self.bd.by_class(0x0a):
            if self.bd.words(lab)[1] == diag:
                txt = self.label_text(self.bd, lab)
                if txt:
                    print('%s# "%s"' % (pad, txt.replace("\r", " / ").replace("\n", " / ")), file=out)
        ids = {}
        for n in nodes:
            self.counter += 1
            ids[n] = "N%d" % self.counter
            self.node_ids[n] = ids[n]
            for i, t in enumerate(self.terminals(n)):
                self.term_owner[t] = self.term_name(t, ids[n], i)
            for t in self.terms_by_struct.get(n, []):
                if t not in self.term_owner:
                    self.term_owner[t] = self.term_name(t, ids[n], -1)
        for n in nodes:
            kind, extra = self.describe_node(n)
            terms = self.terminals(n)
            print("%s%-5s %-10s %s  [%d term]" % (pad, ids[n], kind, extra, len(terms)), file=out)
            cls = self.bd.cls(n)
            if cls in STRUCT_CLASSES or self.subdiagrams(n):
                # structure-border terminals (tunnels etc.) belong to the structure node itself
                for k, sd in enumerate(self.subdiagrams(n)):
                    print("%s  frame %d:" % (pad, k), file=out)
                    self._dump_diagram(sd, depth + 2, out)
        # wires of this diagram
        w = self.bd.words(diag)
        wires = [x for x in self.bd.lst(w[4])] if len(w) > 4 else []
        for wr in wires:
            if self.bd.cls(wr) != 0x17:
                continue
            ends = []
            for t in self.bd.lst(self.bd.words(wr)[2]):
                if t in self.term_owner:
                    ends.append(self.term_owner[t])
                else:
                    tw = self.bd.words(t)
                    ends.append("?(cls%02x owner=%02x desc=%02x)" % (self.bd.cls(t) or 0,
                                self.bd.cls(tw[1]) or 0 if len(tw) > 1 else 0,
                                self.bd.cls(tw[3]) or 0 if len(tw) > 3 else 0))
            if ends:
                print("%s  wire: %s" % (pad, " -- ".join(ends)), file=out)


if __name__ == "__main__":
    VI(sys.argv[1]).dump()
