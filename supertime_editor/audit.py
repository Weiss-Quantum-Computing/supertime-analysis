# -*- coding: utf-8 -*-
"""Audit a sequence for likely mistakes.

usage: python -m supertime_editor.audit <file.dt4> [...]

Checks (each finding carries a severity: error = Supertime will misbehave or the file is
inconsistent; warn = suspicious, worth a look; note = informational):
  * structure: channel arrays shorter/longer than the edge list, bad parent/variable indices,
    parent-chain cycles, duplicate channel names, two channels on the same card/pin
  * timing: edges at negative times, edges closer than the 1 us clock, two edges at exactly
    the same time on one channel with conflicting values, relative times not a whole us
  * ramps: step below 2 us or not a whole us, simultaneous ramps whose steps have no common
    multiple >= 2 us, enabled ramp without a function, enabled ramp with no later value to
    end on, ramp spanning many intermediate edges, disabled ramp that looks intended
    (function + step set, value changes, time constant 0)
  * values: analog value on a digital channel / digital value on an analog channel, variables
    that nothing uses, edges timed by a variable that does not exist
"""
from __future__ import print_function, division
import collections
import sys

from . import lvcore
from .model import (Sequence, K_NAME, K_CARD, K_CHAN, K_SIG, K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP,
                    E_ABS, E_NAME, E_PARENT, E_REL, E_VARS, E_TYPE, V_NAME, step_us, is_pulse_shape)


class Finding(object):
    def __init__(self, severity, kind, where, text):
        self.severity, self.kind, self.where, self.text = severity, kind, where, text

    def __repr__(self):
        return "[%s] %s: %s  (%s)" % (self.severity, self.kind, self.text, self.where)


def audit(seq, s=0, min_step_us=2):
    F = []
    E = seq.edges
    n = len(E)
    res_us = seq.data.get("Target \nResolution (us):") or 1.0

    # ---- structure
    for p in seq.check():
        F.append(Finding("error" if "cycle" in p or "out of range" in p else "warn", "structure", "", p))
    names = collections.Counter(seq.channel_names())
    for nm, c in names.items():
        if c > 1:
            F.append(Finding("error", "channels", nm, "channel name used %d times" % c))
    pins = collections.defaultdict(list)
    for row in seq.grid:
        c = row[s]
        pins[(c[K_CARD], c[K_CHAN], c[K_SIG])].append(c[K_NAME])
    for (card, pin, sig), lst in pins.items():
        if len(lst) > 1:
            F.append(Finding("error", "channels", u", ".join(lst), "share card %d channel %d" % (card, pin)))

    # ---- timing
    order = seq.edge_order()
    for i in order:
        if E[i][E_ABS] < 0:
            F.append(Finding("error", "timing", E[i][E_NAME], "edge at negative time %g ms" % E[i][E_ABS]))
        rel_us = E[i][E_REL] * 1000.0
        if E[i][E_TYPE] == 0 and abs(rel_us - round(rel_us)) > 1e-6:
            F.append(Finding("warn", "timing", E[i][E_NAME], "relative time %g ms is not a whole us" % E[i][E_REL]))
        if E[i][E_TYPE] == 1 and not E[i][E_VARS]:
            F.append(Finding("error", "timing", E[i][E_NAME], "timed by a variable but none assigned"))
        for v in E[i][E_VARS]:
            if E[i][E_TYPE] == 1 and not (0 <= v < len(seq.variables)):
                F.append(Finding("error", "timing", E[i][E_NAME], "variable index %d does not exist" % v))
    # edges too close together (whole sequence)
    times = sorted((E[i][E_ABS], i) for i in range(n))
    for (t0, a), (t1, b) in zip(times, times[1:]):
        d_us = (t1 - t0) * 1000.0
        if 0 < d_us < res_us - 1e-6:
            F.append(Finding("error", "timing", u"%s / %s" % (E[a][E_NAME], E[b][E_NAME]),
                             "edges %.3f us apart, below the %g us clock" % (d_us, res_us)))
    # same-instant conflicts per channel
    by_time = collections.defaultdict(list)
    for i in range(n):
        by_time[round(E[i][E_ABS], 6)].append(i)
    for row in seq.grid:
        c = row[s]
        digital = c[K_SIG] == 1
        for t, idx in by_time.items():
            if len(idx) < 2:
                continue
            vals = []
            for i in idx:
                v = Sequence.cell_value(c, K_DIG if digital else K_ANLG, i)
                if (digital and v != -1) or (not digital and not lvcore.is_nan(v)):
                    vals.append((v, i))
            if len(set(v for v, _ in vals)) > 1:
                F.append(Finding("warn", "timing", c[K_NAME], "two different values at the same instant %g ms: %s"
                                 % (t, u", ".join(u"%s@%s" % (v, E[i][E_NAME]) for v, i in vals))))

    # ---- ramps
    probs, ramps = seq.check_ramps(s, min_step_us)
    for kind, r1, r2, g in probs:
        where = u"%s @ %s" % (seq.grid[r1.ch][s][K_NAME], E[r1.i0][E_NAME])
        if r2:
            where += u"  +  %s @ %s" % (seq.grid[r2.ch][s][K_NAME], E[r2.i0][E_NAME])
        F.append(Finding("error", "ramps", where, kind + (" (common step %d us)" % g if r2 else "")))
    for r in ramps:
        between = [i for i in order if r.t0 < E[i][E_ABS] < r.t1]
        if len(between) > 20:
            F.append(Finding("note", "ramps", u"%s @ %s" % (seq.grid[r.ch][s][K_NAME], E[r.i0][E_NAME]),
                             "ramp spans %d intermediate edges (%g ms, %s -> %s)" % (len(between), r.t1 - r.t0, r.v0, r.v1)))
    for ch, row in enumerate(seq.grid):
        c = row[s]
        if c[K_SIG] == 1:
            continue
        pos = {i: k for k, i in enumerate(order)}
        for i in order:
            v = Sequence.cell_value(c, K_ANLG, i)
            tc = Sequence.cell_value(c, K_TC, i)
            f = Sequence.cell_value(c, K_FUNC, i)
            st = Sequence.cell_value(c, K_STEP, i)
            if lvcore.is_nan(v):
                if tc:
                    F.append(Finding("warn", "ramps", u"%s @ %s" % (c[K_NAME], E[i][E_NAME]),
                                     "time constant %g set on a cell with no value (no ramp starts here)" % tc))
                continue
            nxt = None
            for j in order[pos[i] + 1:]:
                if not lvcore.is_nan(Sequence.cell_value(c, K_ANLG, j)):
                    nxt = j
                    break
            if tc and nxt is None:
                F.append(Finding("error", "ramps", u"%s @ %s" % (c[K_NAME], E[i][E_NAME]),
                                 "ramp enabled but no later value to ramp to (unterminated ramp)"))
            if not tc and f and nxt is not None and st != 1.0:
                v1 = Sequence.cell_value(c, K_ANLG, nxt)
                if v1 != v or is_pulse_shape(f):
                    F.append(Finding("warn", "ramps", u"%s @ %s" % (c[K_NAME], E[i][E_NAME]),
                                     "looks like an intended %s ramp (%g -> %g, step %g ms) but the time constant is 0, so it steps"
                                     % (f, v, v1, st)))

    # ---- values
    for row in seq.grid:
        c = row[s]
        digital = c[K_SIG] == 1
        for i in range(n):
            a = Sequence.cell_value(c, K_ANLG, i)
            d = Sequence.cell_value(c, K_DIG, i)
            if digital and not lvcore.is_nan(a):
                F.append(Finding("warn", "values", u"%s @ %s" % (c[K_NAME], E[i][E_NAME]),
                                 "analog value %g on a digital channel (ignored)" % a))
            if not digital and d != -1:
                F.append(Finding("warn", "values", u"%s @ %s" % (c[K_NAME], E[i][E_NAME]),
                                 "digital value %d on an analog channel (ignored)" % d))
            if digital and d not in (-1, 0, 1):
                F.append(Finding("error", "values", u"%s @ %s" % (c[K_NAME], E[i][E_NAME]), "digital value %d" % d))
    used = set()
    for e in E:
        if e[E_TYPE] == 1:
            used.update(e[E_VARS])
    for k, v in enumerate(seq.variables):
        if k not in used:
            F.append(Finding("note", "variables", v[V_NAME], "variable is not used by any edge"))
    return F


def summarize(F):
    c = collections.Counter((f.severity, f.kind) for f in F)
    return ", ".join("%d %s/%s" % (n, s_, k) for (s_, k), n in sorted(c.items()))


if __name__ == "__main__":
    for path in sys.argv[1:]:
        seq = Sequence.load(path)
        F = audit(seq)
        print("==== %s: %d findings (%s)" % (path.split("/")[-1], len(F), summarize(F) or "none"))
        for f in F:
            print("   ", f)
