# -*- coding: utf-8 -*-
"""Compare two sequences and copy differences across to unify them.

Edges are matched by name (duplicates by order of occurrence), channels by name.
Every difference is a Difference record that knows how to apply itself in either direction.
"""
from __future__ import print_function, division
from collections import OrderedDict

from . import lvcore
from .model import (K_NAME, K_CARD, K_CHAN, K_SIG, K_CONV, K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP,
                    E_NAME, E_PARENT, E_REL, E_VARS, E_TYPE, E_ABS, V_NAME, V_VAL, SETTINGS, strip_prefix)

CELL_LABELS = OrderedDict([(K_ANLG, "analog"), (K_DIG, "digital"), (K_FUNC, "ramp"),
                           (K_STEP, "step (ms)"), (K_TC, "time const")])


def _eq(a, b):
    if isinstance(a, float) and isinstance(b, float):
        if lvcore.is_nan(a) and lvcore.is_nan(b):
            return True
        return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))
    return a == b


def fmt_value(v):
    if v is None:
        return ""
    if isinstance(v, float):
        if lvcore.is_nan(v):
            return "-"
        return ("%.6g" % v)
    if v == -1:
        return "-"
    return "%s" % (v,)


def _occurrence_keys(names):
    """Map names to (name, k) keys so duplicate names stay distinct and ordered."""
    seen = {}
    keys = []
    for n in names:
        k = seen.get(n, 0)
        seen[n] = k + 1
        keys.append((n, k))
    return keys


class Difference(object):
    """kind: 'edge-missing', 'edge', 'channel-missing', 'channel', 'cell', 'variable', 'setting'."""

    def __init__(self, kind, where, field, va, vb, data=None):
        self.kind = kind
        self.where = where          # (channel name, edge name) or name
        self.field = field
        self.va = va
        self.vb = vb
        self.data = data or {}

    def label(self):
        if self.kind == "cell":
            return u"%s @ %s" % self.where
        return u"%s" % (self.where,)

    def __repr__(self):
        return "<%s %s %s: %s | %s>" % (self.kind, self.label(), self.field, fmt_value(self.va), fmt_value(self.vb))


class Comparison(object):
    def __init__(self, a, b, sets=(0, 0), ignore_prefixes=False):
        self.a = a
        self.b = b
        self.ignore_prefixes = ignore_prefixes
        self.sa, self.sb = sets
        self.diffs = []
        self.edge_map = []          # list of (ia or None, ib or None, key)
        self.chan_map = []
        self.run()

    # ---- matching
    def run(self):
        a, b = self.a, self.b
        self.diffs = []
        norm = strip_prefix if self.ignore_prefixes else (lambda n: n)
        ka = _occurrence_keys([norm(n) for n in a.edge_names()])
        kb = _occurrence_keys([norm(n) for n in b.edge_names()])
        ib_of = dict((k, i) for i, k in enumerate(kb))
        ia_of = dict((k, i) for i, k in enumerate(ka))
        self.edge_map = []
        for i, k in enumerate(ka):
            self.edge_map.append((i, ib_of.get(k), k))
        for j, k in enumerate(kb):
            if k not in ia_of:
                self.edge_map.append((None, j, k))
        ca = a.channel_names()
        cb = b.channel_names()
        jb_of = dict((n, j) for j, n in enumerate(cb))
        ia_c = dict((n, i) for i, n in enumerate(ca))
        self.chan_map = [(i, jb_of.get(n), n) for i, n in enumerate(ca)]
        self.chan_map += [(None, j, n) for j, n in enumerate(cb) if n not in ia_c]

        # edges
        for ia, ib, key in self.edge_map:
            name = key[0] if key[1] == 0 else u"%s (%d)" % key
            if ia is None or ib is None:
                side = "B" if ia is None else "A"
                e = (b.edges[ib] if ia is None else a.edges[ia])
                self.diffs.append(Difference("edge-missing", name, "only in " + side,
                                             e[E_ABS] if ia is not None else None,
                                             e[E_ABS] if ib is not None else None,
                                             {"ia": ia, "ib": ib}))
                continue
            ea, eb = a.edges[ia], b.edges[ib]
            pa = norm(a.edges[ea[E_PARENT]][E_NAME]) if 0 <= ea[E_PARENT] < len(a.edges) else "?"
            pb = norm(b.edges[eb[E_PARENT]][E_NAME]) if 0 <= eb[E_PARENT] < len(b.edges) else "?"
            va = [a.variables[k][V_NAME] for k in ea[E_VARS] if k < len(a.variables)]
            vb = [b.variables[k][V_NAME] for k in eb[E_VARS] if k < len(b.variables)]
            uses_var = ea[E_TYPE] == 1 or eb[E_TYPE] == 1
            for field, x, y in (("parent", pa, pb), ("relative (ms)", ea[E_REL], eb[E_REL]),
                                ("time type", ea[E_TYPE], eb[E_TYPE]), ("variables", va, vb),
                                ("absolute (ms)", ea[E_ABS], eb[E_ABS])):
                if field == "variables" and not uses_var:
                    continue                 # a type-0 edge ignores its variable list
                if not _eq(x, y):
                    self.diffs.append(Difference("edge", name, field, x, y, {"ia": ia, "ib": ib}))

        # variables
        vna = dict((v[V_NAME], v[V_VAL]) for v in a.variables)
        vnb = dict((v[V_NAME], v[V_VAL]) for v in b.variables)
        for n in list(vna) + [n for n in vnb if n not in vna]:
            if n not in vnb or n not in vna:
                self.diffs.append(Difference("variable", n, "only in " + ("A" if n in vna else "B"),
                                             vna.get(n), vnb.get(n)))
            elif not _eq(vna[n], vnb[n]):
                self.diffs.append(Difference("variable", n, "value (ms)", vna[n], vnb[n]))

        # channels and cells
        for ia, ib, name in self.chan_map:
            if ia is None or ib is None:
                self.diffs.append(Difference("channel-missing", name, "only in " + ("B" if ia is None else "A"),
                                             None, None, {"ia": ia, "ib": ib}))
                continue
            ca = a.grid[ia][self.sa]
            cb = b.grid[ib][self.sb]
            for field, label in ((K_CARD, "card"), (K_CHAN, "channel #"), (K_SIG, "signal type"),
                                 (K_CONV, "conversion VI")):
                if not _eq(ca[field], cb[field]):
                    self.diffs.append(Difference("channel", name, label, ca[field], cb[field], {"ia": ia, "ib": ib}))
            for ea, eb, key in self.edge_map:
                if ea is None or eb is None:
                    continue
                ename = key[0] if key[1] == 0 else u"%s (%d)" % key
                for field, label in CELL_LABELS.items():
                    x, y = a.cell_value(ca, field, ea), b.cell_value(cb, field, eb)
                    if not _eq(x, y):
                        self.diffs.append(Difference("cell", (name, ename), label, x, y,
                                                     {"ia": ia, "ib": ib, "ea": ea, "eb": eb, "field": field}))

        # settings
        for k in SETTINGS:
            if k == "File name":
                continue
            if not _eq(a.data.get(k), b.data.get(k)):
                self.diffs.append(Difference("setting", k.replace("\n", " "), "value", a.data.get(k), b.data.get(k)))

    # ---- unify
    def apply(self, d, direction="A->B"):
        """Copy one difference from one sequence to the other. Returns True if applied."""
        src, dst = (self.a, self.b) if direction == "A->B" else (self.b, self.a)
        ssrc, sdst = (self.sa, self.sb) if direction == "A->B" else (self.sb, self.sa)
        i_src = d.data.get("ia" if direction == "A->B" else "ib")
        i_dst = d.data.get("ib" if direction == "A->B" else "ia")
        if d.kind == "cell":
            e_src = d.data["ea" if direction == "A->B" else "eb"]
            e_dst = d.data["eb" if direction == "A->B" else "ea"]
            if i_dst is None or e_dst is None:
                return False
            f = d.data["field"]
            dst.repair()
            dst.grid[i_dst][sdst][f][e_dst] = src.cell_value(src.grid[i_src][ssrc], f, e_src)
            return True
        if d.kind == "channel":
            key = {"card": K_CARD, "channel #": K_CHAN, "signal type": K_SIG, "conversion VI": K_CONV}[d.field]
            dst.grid[i_dst][sdst][key] = src.grid[i_src][ssrc][key]
            return True
        if d.kind == "variable":
            if d.field == "value (ms)":
                k = dst.find_variable(d.where)
                dst.variables[k][V_VAL] = src.variables[src.find_variable(d.where)][V_VAL]
                dst.recompute_times()
                return True
            if src.find_variable(d.where) >= 0 and dst.find_variable(d.where) < 0:
                dst.add_variable(d.where, src.variables[src.find_variable(d.where)][V_VAL])
                return True
            if src.find_variable(d.where) < 0 and dst.find_variable(d.where) >= 0:
                dst.delete_variable(dst.find_variable(d.where))
                return True
            return False
        if d.kind == "edge":
            es, ed = src.edges[i_src], dst.edges[i_dst]
            if d.field == "relative (ms)":
                ed[E_REL] = es[E_REL]
            elif d.field == "time type":
                ed[E_TYPE] = es[E_TYPE]
            elif d.field == "parent":
                pname = src.edges[es[E_PARENT]][E_NAME]
                k = dst.find_edge(pname)
                if k < 0:
                    return False
                ed[E_PARENT] = k
            elif d.field == "variables":
                names = [src.variables[k][V_NAME] for k in es[E_VARS] if k < len(src.variables)]
                idx = []
                for n in names:
                    k = dst.find_variable(n)
                    if k < 0:
                        k = dst.add_variable(n, src.variables[src.find_variable(n)][V_VAL])
                    idx.append(k)
                ed[E_VARS] = idx
            else:
                return False
            dst.recompute_times()
            return True
        if d.kind == "edge-missing":
            if i_src is None:           # exists only in the destination: unify by deleting it
                k = dst.find_edge(d.where if isinstance(d.where, str) else d.where)
                k = i_dst if i_dst is not None and i_dst < len(dst.edges) else k
                if k is None or k < 0 or k >= len(dst.edges):
                    return False
                dst.delete_edge(k)
                self._shift_after_delete("edge", direction, k)
                return True
            es = src.edges[i_src]
            pname = src.edges[es[E_PARENT]][E_NAME] if 0 <= es[E_PARENT] < len(src.edges) else None
            k = dst.find_edge(pname) if pname else 0
            if k < 0:
                k = 0
            names = [src.variables[v][V_NAME] for v in es[E_VARS] if v < len(src.variables)]
            idx = []
            for n in names:
                j = dst.find_variable(n)
                if j < 0:
                    j = dst.add_variable(n, src.variables[src.find_variable(n)][V_VAL])
                idx.append(j)
            new = dst.add_edge(es[E_NAME], k, es[E_REL], es[E_TYPE], idx)
            # copy the per-channel values for channels that exist on both sides
            for ia, ib, cname in self.chan_map:
                if ia is None or ib is None:
                    continue
                cs = src.grid[ia if direction == "A->B" else ib][ssrc]
                cd = dst.grid[ib if direction == "A->B" else ia][sdst]
                for f in (K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP):
                    cd[f][new] = src.cell_value(cs, f, i_src)
            return True
        if d.kind == "channel-missing":
            if i_src is None:           # exists only in the destination: delete it there
                if i_dst is None or i_dst >= len(dst.grid):
                    return False
                dst.delete_channel(i_dst)
                self._shift_after_delete("channel", direction, i_dst)
                return True
            cs = src.grid[i_src][ssrc]
            dst.repair()
            new = dst.add_channel(cs[K_NAME], cs[K_CARD], cs[K_CHAN], cs[K_SIG], cs[K_CONV])
            cd = dst.grid[new][sdst]
            # match edges by name afresh (indices may have moved since this comparison ran)
            dst_idx = {}
            for j, e in enumerate(dst.edges):
                dst_idx.setdefault(e[E_NAME], j)
            for i, e in enumerate(src.edges):
                j = dst_idx.get(e[E_NAME])
                if j is None:
                    continue
                for f in (K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP):
                    cd[f][j] = src.cell_value(cs, f, i)
            return True
        if d.kind == "setting":
            key = [k for k in SETTINGS if k.replace("\n", " ") == d.where][0]
            dst.data[key] = src.data[key]
            return True
        return False

    def _shift_after_delete(self, what, direction, k):
        """Keep the stored indices of the remaining differences valid after a deletion in dst."""
        key = ("ib" if direction == "A->B" else "ia")
        ekey = ("eb" if direction == "A->B" else "ea")
        for d in self.diffs:
            if what == "channel" and d.kind in ("cell", "channel", "channel-missing") and d.data.get(key) is not None:
                if d.data[key] == k:
                    d.data[key] = None
                elif d.data[key] > k:
                    d.data[key] -= 1
            if what == "edge" and d.kind in ("cell",) and d.data.get(ekey) is not None:
                if d.data[ekey] == k:
                    d.data[ekey] = None
                elif d.data[ekey] > k:
                    d.data[ekey] -= 1
            if what == "edge" and d.kind in ("edge", "edge-missing") and d.data.get(key) is not None:
                if d.data[key] == k:
                    d.data[key] = None
                elif d.data[key] > k:
                    d.data[key] -= 1

    STRUCTURAL = ("variable", "edge-missing", "channel-missing")

    def unify_all(self, direction="A->B", kinds=None):
        """Make the destination match the source for every difference (or only `kinds`).

        Additions never move existing indices, deletions are done from the highest index
        down, and the comparison is re-run between passes.  Returns #differences applied.
        """
        dst_key = "ib" if direction == "A->B" else "ia"
        total = 0
        for _ in range(12):
            self.run()
            todo = [d for d in self.diffs if (kinds is None or d.kind in kinds)]
            if not todo:
                break
            n = 0
            adds = [d for d in todo if d.kind in self.STRUCTURAL and d.data.get(dst_key) is None]
            dels = [d for d in todo if d.kind in self.STRUCTURAL and d.data.get(dst_key) is not None]
            for d in adds:                                   # variables, missing edges, missing channels
                n += 1 if self.apply(d, direction) else 0
            if dels:
                self.run()                                   # indices again valid after additions
                todo2 = [d for d in self.diffs if d.kind in self.STRUCTURAL and d.data.get(dst_key) is not None]
                for d in sorted(todo2, key=lambda d: -d.data[dst_key]):
                    n += 1 if self.apply(d, direction) else 0
            if n == 0:                                       # nothing structural left: values
                for d in [d for d in todo if d.kind not in self.STRUCTURAL]:
                    n += 1 if self.apply(d, direction) else 0
            total += n
            if n == 0:
                break
        self.run()
        return total

    def summary(self):
        from collections import Counter
        c = Counter(d.kind for d in self.diffs)
        return ", ".join("%d %s" % (n, k) for k, n in sorted(c.items()))
