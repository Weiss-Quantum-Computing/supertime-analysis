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
        return (not lvcore.is_nan(c[K_ANLG][edge])) or c[K_DIG][edge] != -1 or bool(c[K_TC][edge])

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


PULSE_SHAPES = (u"Gaussian", u"Blackman", u"Custom")


def is_pulse_shape(func):
    """Ramp functions that draw a shape between equal end values (t ignored / shape from file)."""
    return any((func or u"").startswith(p) for p in PULSE_SHAPES)


def ramp_steps(r):
    """Number of output levels a ramp generates."""
    return int((r.t1 - r.t0) / r.step + 1e-9) if r.step > 0 else 0


def ramp_report(seq, s=0, min_steps=0):
    """All enabled ramps sorted by number of steps (largest first), for hunting memory use."""
    rows = []
    for ch in range(len(seq.grid)):
        for r in seq.ramps(ch, s):
            n = ramp_steps(r)
            if n >= min_steps:
                rows.append((n, r))
    rows.sort(key=lambda x: -x[0])
    return rows


class Ramp(object):
    """One ramp on a channel: from edge i0 (value v0) to the next edge with a value, i1."""

    def __init__(self, ch, i0, i1, v0, v1, func, step, tc, t0, t1):
        self.ch, self.i0, self.i1, self.v0, self.v1 = ch, i0, i1, v0, v1
        self.func, self.step, self.tc, self.t0, self.t1 = func, step, tc, t0, t1

    def __repr__(self):
        return "<Ramp ch%d %s edge %d->%d %g->%g step %g ms %g..%g>" % (
            self.ch, self.func, self.i0, self.i1, self.v0, self.v1, self.step, self.t0, self.t1)


def _ramps_for(seq, ch, s=0):
    """Ramps on channel ch.  Supertime enables a ramp only where the time constant is nonzero;
    the ramp runs from that edge's value to the next edge (in time) where the channel has a
    value, with the cell's ramp function and step size.  Function/step entries on cells with a
    zero time constant are inert."""
    c = seq.grid[ch][s]
    order = seq.edge_order()
    ramps = []
    for k, i in enumerate(order):
        v0 = Sequence.cell_value(c, K_ANLG, i)
        f = Sequence.cell_value(c, K_FUNC, i)
        tc = Sequence.cell_value(c, K_TC, i)
        if not tc or lvcore.is_nan(v0):
            continue
        for j in order[k + 1:]:
            v1 = Sequence.cell_value(c, K_ANLG, j)
            if not lvcore.is_nan(v1):
                ramps.append(Ramp(ch, i, j, v0, v1, f, Sequence.cell_value(c, K_STEP, i),
                                  Sequence.cell_value(c, K_TC, i),
                                  seq.edges[i][E_ABS], seq.edges[j][E_ABS]))
                break
    return ramps


def ramp_shape(func, tc, u, T):
    """Fraction of the way from the start value to the end value at time u (ms since the ramp
    start) for a ramp of duration T with time constant tc.  Shapes follow the formula nodes in
    'Functions and derivatives for fit.vi' with the two end points fixed ("two-point fit with
    time constant"):
      Exponential   y = a0*exp(-x/t) + a2
      Optical       P = P0/(x/tau + 1)^2 + C
      Cubic         P = P0*(2.777 u + 5.440 u^2 + 3.663 u^3) + C,  u = x/tau
      Linear        y = a0*x + a2
    Gaussian and Blackman are pulses (t ignored): baseline = start value, peak = end value at
    the middle of the interval, width = the interval.  Custom and anything unknown: linear.
    """
    import math
    if T <= 0:
        return 1.0
    f = func or u""
    x = min(max(u, 0.0), T)
    if f.startswith(u"Exponential") and tc > 0:
        k = math.exp(-T / tc)
        return (1.0 - math.exp(-x / tc)) / (1.0 - k) if k != 1.0 else x / T
    if f.startswith(u"Optical") and tc > 0:
        k = 1.0 / (T / tc + 1.0) ** 2
        return (1.0 - 1.0 / (x / tc + 1.0) ** 2) / (1.0 - k) if k != 1.0 else x / T
    if f.startswith(u"Cubic") and tc > 0:
        g = lambda v: 2.777 * v + 5.440 * v ** 2 + 3.663 * v ** 3
        d = g(T / tc)
        return g(x / tc) / d if d else x / T
    if f.startswith(u"Gaussian"):
        w = T / 4.0
        return math.exp(-2.0 * (x - T / 2.0) ** 2 / (w * w)) if w else 0.0
    if f.startswith(u"Blackman"):
        a = T / 2.0
        if a <= 0:
            return 0.0
        return 0.42 + 0.5 * math.cos(math.pi * (x - a) / a) + 0.08 * math.cos(2 * math.pi * (x - a) / a)
    return x / T


def _ramp_levels(v0, v1, t0, t1, step, func, tc=0.0):
    """The discrete levels Supertime outputs for a ramp: one new value every `step` ms from t0,
    following ramp_shape(), ending on v1 at t1 (pulse shapes end back on the start value)."""
    T = t1 - t0
    if T <= 0 or step <= 0:
        return [(t0, v0), (t1, v1)]
    n = int(T / step + 1e-9)
    if n > 20000:                                   # keep plots responsive on huge ramps
        step = T / 20000.0
        n = 20000
    pulse = is_pulse_shape(func) and not (func or u"").startswith(u"Custom")
    pts = []
    for k in range(n + 1):
        t = t0 + k * step
        if t >= t1 - 1e-9:
            break
        frac = ramp_shape(func, tc, t - t0, T)
        pts.append((t, v0 + (v1 - v0) * frac))
    pts.append((t1, v0 if pulse else v1))
    return pts


def _trace(seq, ch, s=0):
    """(time, value) points describing the channel over the cycle as a step function: the value
    holds between edges, and an enabled ramp (nonzero time constant) is drawn as the discrete
    staircase Supertime outputs, one step per step-size interval."""
    c = seq.grid[ch][s]
    digital = c[K_SIG] == 1
    pts = []
    cur = None
    order = seq.edge_order()
    skip_until = None
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
        if skip_until == i:                         # end of a ramp already drawn
            skip_until = None
            cur = v
            continue
        if cur is not None:
            pts.append((t, cur))
        pts.append((t, v))
        cur = v
        if Sequence.cell_value(c, K_TC, i):
            for j in order[k + 1:]:
                v1 = Sequence.cell_value(c, K_ANLG, j)
                if not lvcore.is_nan(v1):
                    t1 = seq.edges[j][E_ABS]
                    levels = _ramp_levels(v, v1, t, t1, Sequence.cell_value(c, K_STEP, i),
                                          Sequence.cell_value(c, K_FUNC, i), Sequence.cell_value(c, K_TC, i))
                    prev = v
                    for tt, vv in levels[1:]:
                        pts.append((tt, prev))
                        pts.append((tt, vv))
                        prev = vv
                    cur = v1
                    skip_until = j
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
            if not r.func:
                problems.append(("ramp enabled (time constant set) but no ramp function", r, None, su))
            if su < min_step_us:
                problems.append(("step too small", r, None, su))
            elif abs(r.step * 1000.0 - su) > 1e-6:
                problems.append(("step not a whole us", r, None, su))
    # ramps between equal values output nothing unless the function is a pulse shape
    real = sorted([r for r in all_ramps if r.t1 > r.t0 and (r.v0 != r.v1 or is_pulse_shape(r.func))],
                  key=lambda r: r.t0)
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
Sequence.ramp_report = ramp_report
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


# ---------------------------------------------------------------- variable clean-up
def simplify_variable_name(name):
    """' 000 Spin Echo pulse p2' -> 'Spin Echo pulse p2', '0:  0: Helmholtz...' -> 'Helmholtz...'."""
    import re
    n = name.strip()
    n = re.sub(r"^(?:\d+\s*:\s*|\d{2,}\s*)+", "", n)       # '0: ', '1: 0: ', '000', '001 '
    n = re.sub(r"\s+", " ", n).strip()
    return n or name.strip()


def _norm_key(name):
    import re
    return re.sub(r"[^a-z0-9]+", " ", simplify_variable_name(name).lower()).strip()


def _simplify_variables(seq, dry_run=False, merge_similar=True, drop_unused=True):
    """Rename variables to their simplified names, merge duplicates (same simplified name and
    same value), repoint the edges that use them, and remove unused variables.

    Returns a report dict: renamed [(old, new)], merged [(old, into)], removed [name],
    kept_apart [(a, b)] for same-name variables with different values that are both used.
    Edge times are unchanged by construction (every edge keeps a variable of equal value).
    """
    V = seq.variables
    E = seq.edges
    used = collections_counter_used(E, len(V))
    newname = [simplify_variable_name(v[V_NAME]) for v in V]
    target = list(range(len(V)))                       # variable k is replaced by target[k]
    report = {"renamed": [], "merged": [], "removed": [], "kept_apart": []}
    if merge_similar:
        by_key = {}
        for k, v in enumerate(V):
            key = _norm_key(v[V_NAME])
            by_key.setdefault(key, []).append(k)
        for key, ks in by_key.items():
            if len(ks) < 2:
                continue
            # prefer a used variable, then the first one, as the survivor of each value group
            by_val = {}
            for k in ks:
                by_val.setdefault(round(V[k][V_VAL], 9), []).append(k)
            for val, group in by_val.items():
                group.sort(key=lambda k: (0 if used[k] else 1, k))
                keep = group[0]
                for k in group[1:]:
                    target[k] = keep
                    report["merged"].append((V[k][V_NAME].strip(), V[keep][V_NAME].strip()))
            if len(by_val) > 1:
                # only a real conflict when more than one value is actually used by an edge
                vals = sorted((val, g) for val, g in by_val.items() if any(used[k] for k in g) or not drop_unused)
                if len(vals) > 1:
                    report["kept_apart"].append(tuple(u"%s = %g" % (V[g[0]][V_NAME].strip(), val) for val, g in vals))
    # repoint edges
    for e in E:
        e[E_VARS] = [target[k] if k < len(V) else k for k in e[E_VARS]]
    used = collections_counter_used(E, len(V))
    # decide which survive
    survivors = [k for k in range(len(V)) if target[k] == k and (used[k] or not drop_unused)]
    for k in range(len(V)):
        if target[k] == k and not used[k] and drop_unused:
            report["removed"].append(V[k][V_NAME].strip())
    # unique simplified names among survivors
    final = {}
    seen = {}
    for k in survivors:
        n = newname[k]
        if n in seen:
            seen[n] += 1
            n = u"%s (%d)" % (n, seen[n])
        else:
            seen[n] = 1
        final[k] = n
        if n != V[k][V_NAME]:
            report["renamed"].append((V[k][V_NAME], n))
    if dry_run:
        return report
    newindex = {k: i for i, k in enumerate(survivors)}
    seq.data["Variable Array"] = [{V_NAME: final[k], V_VAL: V[k][V_VAL]} for k in survivors]
    for e in E:
        e[E_VARS] = [newindex[k] for k in e[E_VARS] if k in newindex]
    seq.recompute_times()
    return report


def collections_counter_used(E, nvars):
    used = [0] * nvars
    for e in E:
        if e[E_TYPE] == 1:
            for k in e[E_VARS]:
                if 0 <= k < nvars:
                    used[k] += 1
    return used


Sequence.simplify_variables = _simplify_variables
