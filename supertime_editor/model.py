# -*- coding: utf-8 -*-
"""Editable model of a Supertime sequence.

A sequence is: edges (named time points, each defined relative to a parent edge, optionally
timed by a variable), variables (named times in ms), settings, and a channel grid
[set][channel] where each channel holds one entry per edge: analog value (NaN = no change),
digital value (-1 = no change), time constant, ramp function and step size.

Python 2.7 / 3 compatible, standard library only.
"""
from __future__ import print_function, division
import os

from . import lvcore

K_NAME = "Channel Name"
K_CARD = "Card #"
K_CHAN = "Channel #"
K_EDGEIDX = "Edge Name"
K_ANLG = "Edge Value (Anlg)"
K_DIG = "Edge Value (Dig)"
K_TC = "Time constant"
K_SIG = "Signal\nType"
K_FUNC = "Function type"
K_CONV = "Conversion VI"
K_STEP = "Step size (ms)"

E_ABS = "Absolute Time (ms)"
E_NAME = "Edge Name"
E_PARENT = "Defined with Respect to"
E_REL = "Relative Time(ms)"
E_VARS = "Var Names         Time (ms)"
E_TYPE = "Time Type:"

V_NAME = "Variable Name"
V_VAL = "Variable Value (ms)"

SETTINGS = ["Target \nResolution (us):", "Digital I/O",
            "Device number for analog card which does digital outputs", "Number of installed cards",
            "Virtual device number used to enter pseudo-digital outputs", "Device number for timing card",
            "File name", "Device and channel used to reset counters", "External vi"]

CELL_FIELDS = (K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP)
CELL_DEFAULTS = {K_ANLG: lvcore.FILE_NAN, K_DIG: -1, K_TC: 0.0, K_FUNC: u"", K_STEP: 1.0}


class Sequence(object):
    def __init__(self, data, fmt="dt4", path=None):
        self.data = data
        self.fmt = fmt
        self.path = path
        self.dc = lvcore.data_cluster_td()

    # ---- files
    @classmethod
    def load(cls, path):
        data, fmt = lvcore.decode_dt4(path)
        return cls(data, fmt, path)

    def save(self, path=None):
        path = path or self.path
        self.data["File name"] = os.path.basename(path)
        with open(path, "wb") as f:
            f.write(lvcore.encode_dt4(self.data, self.fmt, self.dc))
        self.path = path

    def to_bytes(self):
        return lvcore.encode_dt4(self.data, self.fmt, self.dc)

    # ---- basic accessors
    @property
    def edges(self):
        return self.data["Edge Array"]

    @property
    def variables(self):
        return self.data["Variable Array"]

    @property
    def grid(self):
        """channel array as stored: rows = channels, each row = one entry per data set."""
        return self.data["Channel Array"]

    @property
    def nsets(self):
        g = self.grid
        return len(g[0]) if g else len(self.data["Set Name Array Input"])

    @property
    def set_names(self):
        return self.data["Set Name Array Input"]

    def channels(self, s=0):
        return [row[s] for row in self.grid]

    def channel_names(self):
        return [row[0][K_NAME] for row in self.grid]

    def find_channel(self, name):
        for i, row in enumerate(self.grid):
            if row[0][K_NAME] == name:
                return i
        return -1

    def edge_names(self):
        return [e[E_NAME] for e in self.edges]

    def find_edge(self, name):
        for i, e in enumerate(self.edges):
            if e[E_NAME] == name:
                return i
        return -1

    def find_variable(self, name):
        for i, v in enumerate(self.variables):
            if v[V_NAME] == name:
                return i
        return -1

    def setting(self, key):
        return self.data[key]

    # ---- timing
    def relative_time(self, i):
        e = self.edges[i]
        if e[E_TYPE] == 1 and e[E_VARS]:
            return sum(self.variables[k][V_VAL] for k in e[E_VARS] if k < len(self.variables))
        return e[E_REL]

    def recompute_times(self):
        """Recompute every absolute time from parent + relative (or variable) time.

        Returns the list of edge indices whose parent chain is broken (cycle or bad index);
        those keep their stored absolute time.
        """
        E = self.edges
        res = self.data.get("Target \nResolution (us):") or 1.0
        quantum = res / 1000.0                      # resolution in ms
        memo = {}
        bad = []
        for i in range(len(E)):
            chain = []
            j = i
            seen = set()
            while j not in memo and j not in seen and 0 <= j < len(E) and E[j][E_PARENT] != j:
                seen.add(j)
                chain.append(j)
                j = E[j][E_PARENT]
            if j in memo:
                a = memo[j]
            elif 0 <= j < len(E) and E[j][E_PARENT] == j:
                a = E[j][E_ABS]                      # root (StartCycleRef)
                memo[j] = a
            else:
                bad.append(i)
                continue
            for k in reversed(chain):
                a = a + self.relative_time(k)
                a = round(a / quantum) * quantum
                memo[k] = a
        for i, a in memo.items():
            E[i][E_ABS] = a
        return bad

    def edge_order(self):
        """Edge indices sorted by absolute time (stable)."""
        return sorted(range(len(self.edges)), key=lambda i: (self.edges[i][E_ABS], i))

    def cycle_length(self):
        return max([e[E_ABS] for e in self.edges] or [0.0])

    # ---- cells
    def cell(self, ch, edge, s=0):
        """(analog, digital, time_constant, function, step) of channel ch at edge index edge."""
        c = self.grid[ch][s]
        return tuple(c[f][edge] for f in CELL_FIELDS)

    def set_cell(self, ch, edge, s=0, **fields):
        c = self.grid[ch][s]
        for f, v in fields.items():
            if f not in CELL_FIELDS:
                raise KeyError(f)
            if f == K_ANLG and v is None:
                v = lvcore.FILE_NAN
            c[f][edge] = v

    def cell_is_change(self, ch, edge, s=0):
        c = self.grid[ch][s]
        return (not lvcore.is_nan(c[K_ANLG][edge])) or c[K_DIG][edge] != -1 or bool(c[K_FUNC][edge])

    @staticmethod
    def cell_value(c, field, edge):
        """Value of one per-edge field, tolerating channels whose arrays are shorter than the
        edge list (such files exist; Supertime treats the missing tail as 'no change')."""
        lst = c[field]
        return lst[edge] if edge < len(lst) else CELL_DEFAULTS[field]

    def repair(self):
        """Pad or trim every channel's per-edge arrays to the edge count. Returns #fixed."""
        n = len(self.edges)
        fixed = 0
        for row in self.grid:
            for c in row:
                for f in CELL_FIELDS:
                    if len(c[f]) != n:
                        c[f] = (c[f] + [CELL_DEFAULTS[f]] * n)[:n]
                        fixed += 1
        return fixed

    # ---- edges
    def add_edge(self, name, parent, relative_ms, time_type=0, var_indices=None):
        """Append an edge; every channel in every set gets a default (no change) entry."""
        self.repair()                               # arrays must be edge-aligned before appending
        self.edges.append({E_ABS: 0.0, E_NAME: name, E_PARENT: parent, E_REL: relative_ms,
                           E_VARS: list(var_indices or []), E_TYPE: time_type})
        for row in self.grid:
            for c in row:
                for f in CELL_FIELDS:
                    c[f].append(CELL_DEFAULTS[f])
        self.recompute_times()
        return len(self.edges) - 1

    def delete_edge(self, i):
        """Remove edge i; children are re-parented to its parent with their time preserved."""
        E = self.edges
        victim = E[i]
        for j, e in enumerate(E):
            if j != i and e[E_PARENT] == i:
                e[E_PARENT] = victim[E_PARENT]
                if e[E_TYPE] == 0:
                    e[E_REL] = e[E_REL] + self.relative_time(i)
        del E[i]
        for e in E:
            if e[E_PARENT] > i:
                e[E_PARENT] -= 1
            elif e[E_PARENT] == i:
                e[E_PARENT] = 0
        for row in self.grid:
            for c in row:
                for f in CELL_FIELDS:
                    if i < len(c[f]):
                        del c[f][i]
                if c[K_EDGEIDX] >= len(E):
                    c[K_EDGEIDX] = 0
        self.recompute_times()

    def rename_edge(self, i, name):
        self.edges[i][E_NAME] = name

    # ---- variables
    def add_variable(self, name, value_ms):
        self.variables.append({V_NAME: name, V_VAL: value_ms})
        return len(self.variables) - 1

    def delete_variable(self, k):
        del self.variables[k]
        for e in self.edges:
            e[E_VARS] = [v - 1 if v > k else v for v in e[E_VARS] if v != k]
        self.recompute_times()

    # ---- channels
    def add_channel(self, name, card, channel, signal_type, conversion_vi=u""):
        n = len(self.edges)
        row = []
        for _ in range(max(self.nsets, 1)):
            c = {K_NAME: name, K_CARD: card, K_CHAN: channel, K_EDGEIDX: 0, K_SIG: signal_type,
                 K_CONV: conversion_vi}
            for f in CELL_FIELDS:
                c[f] = [CELL_DEFAULTS[f]] * n
            row.append(c)
        self.grid.append(row)
        return len(self.grid) - 1

    def delete_channel(self, ch):
        del self.grid[ch]

    # ---- sanity
    def check(self):
        """Return a list of problems (strings) with the sequence's internal consistency."""
        problems = []
        n = len(self.edges)
        for ri, row in enumerate(self.grid):
            for s, c in enumerate(row):
                for f in CELL_FIELDS:
                    if len(c[f]) != n:
                        problems.append("channel %r set %d: %s has %d entries, %d edges"
                                        % (c[K_NAME], s, f, len(c[f]), n))
        for i, e in enumerate(self.edges):
            if not (0 <= e[E_PARENT] < n):
                problems.append("edge %d %r: parent index %d out of range" % (i, e[E_NAME], e[E_PARENT]))
            for v in e[E_VARS]:
                if not (0 <= v < len(self.variables)):
                    problems.append("edge %d %r: variable index %d out of range" % (i, e[E_NAME], v))
        bad = self.recompute_times()
        for i in bad:
            problems.append("edge %d %r: parent chain is a cycle" % (i, self.edges[i][E_NAME]))
        return problems


# ---------------------------------------------------------------- ramps, traces, checks, batch edits
def _gcd(a, b):
    while b:
        a, b = b, a % b
    return a


def step_us(step_ms):
    """A step size in whole microseconds (the clock is 1 us)."""
    return int(round(step_ms * 1000.0))


class Ramp(object):
    """One ramp on a channel: from edge i0 (value v0) to the next edge with a value, i1."""

    def __init__(self, ch, i0, i1, v0, v1, func, step, tc, t0, t1):
        self.ch, self.i0, self.i1, self.v0, self.v1 = ch, i0, i1, v0, v1
        self.func, self.step, self.tc, self.t0, self.t1 = func, step, tc, t0, t1

    def __repr__(self):
        return "<Ramp ch%d %s edge %d->%d %g->%g step %g ms %g..%g>" % (
            self.ch, self.func, self.i0, self.i1, self.v0, self.v1, self.step, self.t0, self.t1)


def _ramps_for(seq, ch, s=0):
    """Ramps on channel ch: a cell with a value and a ramp function starts a ramp that runs to
    the next edge (in time) where the channel has a value."""
    c = seq.grid[ch][s]
    order = seq.edge_order()
    ramps = []
    for k, i in enumerate(order):
        v0 = Sequence.cell_value(c, K_ANLG, i)
        f = Sequence.cell_value(c, K_FUNC, i)
        if lvcore.is_nan(v0) or not f:
            continue
        for j in order[k + 1:]:
            v1 = Sequence.cell_value(c, K_ANLG, j)
            if not lvcore.is_nan(v1):
                ramps.append(Ramp(ch, i, j, v0, v1, f, Sequence.cell_value(c, K_STEP, i),
                                  Sequence.cell_value(c, K_TC, i),
                                  seq.edges[i][E_ABS], seq.edges[j][E_ABS]))
                break
    return ramps


def _trace(seq, ch, s=0):
    """(time, value) points describing the channel over the cycle: holds between edges,
    straight lines across ramps (the shape of non-linear ramps is not reproduced)."""
    c = seq.grid[ch][s]
    digital = c[K_SIG] == 1
    pts = []
    cur = None
    ramp_end = None
    order = seq.edge_order()
    for k, i in enumerate(order):
        t = seq.edges[i][E_ABS]
        if digital:
            d = Sequence.cell_value(c, K_DIG, i)
            if d == -1:
                continue
            if cur is not None:
                pts.append((t, cur))
            cur = float(d)
            pts.append((t, cur))
            continue
        v = Sequence.cell_value(c, K_ANLG, i)
        if lvcore.is_nan(v):
            continue
        if ramp_end == i:                       # arriving at the end of a ramp: line already drawn
            pts.append((t, v))
            ramp_end = None
        else:
            if cur is not None:
                pts.append((t, cur))
            pts.append((t, v))
        cur = v
        if Sequence.cell_value(c, K_FUNC, i):
            for j in order[k + 1:]:
                if not lvcore.is_nan(Sequence.cell_value(c, K_ANLG, j)):
                    ramp_end = j
                    break
    if cur is not None:
        pts.append((seq.cycle_length(), cur))
    return pts


class RampConflict(object):
    def __init__(self, r1, r2, gcd_us, t0, t1):
        self.r1, self.r2, self.gcd_us, self.t0, self.t1 = r1, r2, gcd_us, t0, t1


def _check_ramps(seq, s=0, min_step_us=2):
    """Flag ramps whose step is below the 2 us minimum, and pairs of simultaneous ramps whose
    step sizes do not share a common multiple of at least 2 us: Supertime interpolates both and
    ends up trying to output edges every gcd(step1, step2) us, which breaks below the clock."""
    problems = []
    all_ramps = []
    for ch in range(len(seq.grid)):
        for r in _ramps_for(seq, ch, s):
            all_ramps.append(r)
            su = step_us(r.step)
            if su < min_step_us:
                problems.append(("step too small", r, None, su))
            elif abs(r.step * 1000.0 - su) > 1e-6:
                problems.append(("step not a whole us", r, None, su))
    # only ramps that actually change the value are interpolated by Supertime
    real = sorted([r for r in all_ramps if r.v0 != r.v1 and r.t1 > r.t0], key=lambda r: r.t0)
    for a in range(len(real)):
        ra = real[a]
        for b in range(a + 1, len(real)):
            rb = real[b]
            if rb.t0 >= ra.t1:
                break
            if ra.ch == rb.ch or rb.t1 <= ra.t0:
                continue
            g = _gcd(step_us(ra.step), step_us(rb.step))
            if g < min_step_us:
                problems.append(("simultaneous ramps need steps with a common multiple >= %d us" % min_step_us,
                                 ra, rb, g))
    return problems, all_ramps


def _set_cells(seq, cells, s=0, **fields):
    """Set the given fields on every (channel, edge) in cells; fields not given stay as they are."""
    seq.repair()
    n = 0
    for ch, ei in cells:
        seq.set_cell(ch, ei, s, **fields)
        n += 1
    return n


def _find_cells(seq, channels=None, edge_pattern=None, value=None, step=None, func=None, s=0,
                tol=1e-9):
    """Cells matching all given criteria: channel indices, a substring of the edge name,
    an analog (or digital) value, a step size, a ramp function name ('' = none)."""
    import re
    rx = re.compile(edge_pattern, re.I) if edge_pattern else None
    out = []
    for ch in (channels if channels is not None else range(len(seq.grid))):
        c = seq.grid[ch][s]
        digital = c[K_SIG] == 1
        for ei, e in enumerate(seq.edges):
            if rx and not rx.search(e[E_NAME]):
                continue
            if value is not None:
                if digital:
                    if Sequence.cell_value(c, K_DIG, ei) != int(value):
                        continue
                else:
                    a = Sequence.cell_value(c, K_ANLG, ei)
                    if lvcore.is_nan(a) or abs(a - value) > tol * max(1.0, abs(value)):
                        continue
            if step is not None and abs(Sequence.cell_value(c, K_STEP, ei) - step) > tol:
                continue
            if func is not None and Sequence.cell_value(c, K_FUNC, ei) != func:
                continue
            out.append((ch, ei))
    return out


def _find_edges(seq, name_pattern=None, relative=None, tol=1e-9):
    import re
    rx = re.compile(name_pattern, re.I) if name_pattern else None
    out = []
    for i, e in enumerate(seq.edges):
        if rx and not rx.search(e[E_NAME]):
            continue
        if relative is not None and abs(e[E_REL] - relative) > tol:
            continue
        out.append(i)
    return out


Sequence.ramps = _ramps_for
Sequence.trace = _trace
Sequence.check_ramps = _check_ramps
Sequence.set_cells = _set_cells
Sequence.find_cells = _find_cells
Sequence.find_edges = _find_edges


# ---------------------------------------------------------------- edge-name simplification
_PREFIX_RX = __import__("re").compile(r"^((?:\s*\d+:\s*)+)(.*)$")


def split_prefix(name):
    """'1: 18: 1: 0: Y: End rotate' -> ([1, 18, 1, 0], 'Y: End rotate'); plain names -> ([], name)."""
    m = _PREFIX_RX.match(name)
    if not m:
        return [], name
    nums = [int(x) for x in __import__("re").findall(r"\d+", m.group(1))]
    return nums, m.group(2)


def strip_prefix(name):
    return split_prefix(name)[1]


def _simplify_names(seq, dry_run=False):
    """Drop the numeric prefixes that splicing adds to edge names ('0: ', '1: 18: 1: 0: ').

    Each edge gets the shortest form that is still unique in the sequence: the bare name if
    nothing else has it, else the first prefix number, else the first two, and so on.
    Returns the list of (old, new) renames; applies them unless dry_run.
    """
    names = seq.edge_names()
    parsed = [split_prefix(n) for n in names]
    taken = {}
    for nums, base in parsed:
        taken.setdefault(base, 0)
        taken[base] += 1
    new = list(names)
    # candidates per edge, shortest first
    cands = []
    for nums, base in parsed:
        c = [base] + [u"%s %s" % (u" ".join(u"%d:" % x for x in nums[:k]), base) for k in range(1, len(nums) + 1)]
        cands.append(c)
    # pick, for every edge, the shortest candidate that no other edge could also claim at that level
    chosen = [None] * len(names)
    for level in range(max(len(c) for c in cands) if cands else 0):
        counts = {}
        for i, c in enumerate(cands):
            if chosen[i] is None:
                key = c[min(level, len(c) - 1)]
                counts[key] = counts.get(key, 0) + 1
        for i, c in enumerate(cands):
            if chosen[i] is None:
                key = c[min(level, len(c) - 1)]
                if counts[key] == 1 or level >= len(c) - 1:
                    chosen[i] = key
    # anything still colliding keeps its original name
    seen = {}
    for i, key in enumerate(chosen):
        seen[key] = seen.get(key, 0) + 1
    renames = []
    for i, key in enumerate(chosen):
        if seen[key] > 1:
            key = names[i]
        if key != names[i]:
            renames.append((names[i], key))
            if not dry_run:
                seq.edges[i][E_NAME] = key
    return renames


Sequence.simplify_names = _simplify_names
