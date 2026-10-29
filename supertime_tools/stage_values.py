# -*- coding: utf-8 -*-
"""Values the experiment takes at the stages of a Supertime sequence, in user units and card volts.

usage: python -m supertime_tools.stage_values FILE.dt4 [--edges "Pic before A,Pic before I done"] [--all]
                                              [--channels "Molasses beams,MOT beams"] [--calib DIR]
                                              [--json OUT.json] [--csv OUT.csv]

For every requested edge (default: every edge at which something changes) the tool lists each
channel's value as written in the sequence (the "user units" the conversion VI assumes), the card
voltage Supertime sends (inverse lookup in the conversion VI's calibration table, as the VI's
Threshold-1D-Array method does: first crossing of the table's y column, x interpolated linearly),
and for AOM-driven beams the fraction of the table's maximum, which is the "max value" the lab last
typed into AOMrescale.  A value holds from the last edge that set it; a ramp is reported as
"ramp -> next value".  Channels without a conversion VI send the user value as volts.

The CONVERSIONS registry below was read out of the conversion VIs' front-panel defaults on
2026-10-29 (see docs/SEQUENCE_VALUES_BRIEF.md); re-check it when a conversion VI changes.
"""
from __future__ import print_function, division
import argparse, csv, io, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from supertime_editor.model import (Sequence, E_NAME, E_ABS, E_TYPE, K_NAME, K_CARD, K_CHAN, K_SIG, K_CONV,
                                    K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP)
from supertime_editor import lvcore

HERE = os.path.dirname(os.path.abspath(__file__))
CALIB = os.path.join(os.path.dirname(os.path.dirname(HERE)), "Supertime Computer", "Documents and Settings",
                     "Experiment control", "Desktop", "Supertime", "supertime sub vi's")

# conversion VI basename -> how it converts.  kind: table (one y->x table), two-table (a second table
# below "High/low threshold"), formula (fit function inside the VI, not decoded), none.
CONVERSIONS = {
    "molasses.vi":          dict(kind="table", table="OM-2014-9-3.txt", units="mW", aom="Molasses"),
    "MOT20250910.vi":       dict(kind="two-table", table="MOT-20250910.txt", low="MOT 55MHz 12-15-09.txt",
                                 units="mW", aom="MOT"),
    "repump.vi":            dict(kind="two-table", table="repump_MOT_path_20171025.txt", low="MOT 55MHz 12-15-09.txt",
                                 units="repump units (table y)", aom="Repump",
                                 note="AOMrescale rescales 'repump MOT path 20111110.txt', which this VI does not read"),
    "MOTAO.vi":             dict(kind="two-table", table="MOT-AO-20111115.txt", low="MOT 55MHz 12-15-09.txt", units="MHz"),
    "OP AO 4-4.vi":         dict(kind="table", table="OP 4-4_20120410.txt", units="OP units (table y)", aom="OP"),
    "LatticeX2.vi":         dict(kind="table", table="LatticeX2.txt", units="X2 units (table y)", aom="Lat. X2"),
    "AddressingH.vi":       dict(kind="table", table="AddressingH.txt", units="addressing units"),
    "AddressingV.vi":       dict(kind="table", table="AddressingV.txt", units="addressing units"),
    "Piezomechanik.vi":     dict(kind="table", table="piezo-20250829.txt", units="objective units"),
    "TrekXEO1_20250731.vi": dict(kind="table", table="EOM_XEO1_20250731.txt", units="EO V (11.412 = 90 deg)"),
    "TrekXEO2_20250731.vi": dict(kind="table", table="EOM_XEO2_20250731.txt", units="EO V (9.99 = 90 deg)"),
    "TrekY_v2.vi":          dict(kind="table", table="EOM_Y_2022.txt", units="EO V"),
    "TrekZ_v2.vi":          dict(kind="table", table="EOM_Z_2022.txt", units="EO V"),
    "HelmholtzX.vi":        dict(kind="formula", units="mG"),
    "HelmholtzY.vi":        dict(kind="formula", units="mG"),
    "HelmholtzZ.vi":        dict(kind="formula", units="mG"),
}
RAW_UNITS = {"Lattice X": "V setpoint (intensity lock)", "Lattice Y": "V setpoint (intensity lock)",
             "Lattice Z": "V setpoint (intensity lock)", "MOT field": "V (coil driver)",
             "Repump Frequency": "V (VCO)", "Lattice X freq": "V (DDS)", "Lattice Y freq": "V (DDS)",
             "Lattice Z freq": "V (DDS)", "PI Intensity lock GC": "V", "400nmLED": "V", "Cs cartridge": "V",
             "Clearing Beam": "V", "Lattice noise monitor": "V"}


def read_table(path):
    rows = []
    for line in io.open(path, "r", encoding="latin-1").read().replace("\r", "").split("\n"):
        parts = line.split("\t") if "\t" in line else line.split(",")
        if len(parts) < 2:
            continue
        try:
            rows.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    return rows


def volts_for(table, y):
    """Threshold 1D Array on points (x = volts, y = user units): x at the first crossing of y."""
    if not table:
        return None, "no table"
    ys = [p[1] for p in table]
    if y <= ys[0]:
        return table[0][0], ("below table" if y < ys[0] else "")
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if (y0 <= y <= y1) or (y1 <= y <= y0):
            if y1 == y0:
                return x0, ""
            return x0 + (x1 - x0) * (y - y0) / (y1 - y0), ""
    return table[-1][0], "above table max %g" % max(ys)


class Converter(object):
    def __init__(self, calib_dir):
        self.dir = calib_dir
        self.tables = {}

    def table(self, name):
        if name not in self.tables:
            p = os.path.join(self.dir, name)
            self.tables[name] = read_table(p) if os.path.exists(p) else None
        return self.tables[name]

    def info(self, name):
        t = self.table(name)
        p = os.path.join(self.dir, name)
        if t is None:
            return dict(file=name, missing=True)
        return dict(file=name, points=len(t), x_volts=[t[0][0], t[-1][0]], y_max=max(y for _, y in t),
                    modified=time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(p))))

    def convert(self, conv_vi, chname, value):
        base = conv_vi.replace("\\", "/").split("/")[-1] if conv_vi else ""
        c = CONVERSIONS.get(base)
        if not conv_vi:
            return dict(volts=value, units=RAW_UNITS.get(chname, "V (no conversion VI)"), how="raw")
        if c is None:
            return dict(volts=None, units="?", how="unknown VI %s" % base)
        if c["kind"] == "formula":
            return dict(volts=None, units=c["units"], how="formula in %s (not decoded)" % base)
        t = self.table(c["table"])
        v, note = volts_for(t, value)
        out = dict(volts=v, units=c["units"], how="table " + c["table"], note=note)
        if t and c.get("aom"):
            ymax = max(y for _, y in t)
            out["fraction_of_max"] = value / ymax if ymax else None
            out["table_max"] = ymax
        if c["kind"] == "two-table":
            lt = self.table(c["low"])
            lv, lnote = volts_for(lt, value) if lt else (None, "missing")
            out["low_table"] = c["low"]
            out["volts_if_low_table"] = lv
            out["note"] = (note + "; " if note else "") + "two-table VI (low table %s below its threshold)" % c["low"]
        if c.get("note"):
            out["note"] = (out.get("note", "") + "; " if out.get("note") else "") + c["note"]
        return out


def timeline(seq, s=0):
    """Per edge (time order): the state of every channel after that edge."""
    E = seq.edges
    order = seq.edge_order()
    state = {}
    out = []
    for i in order:
        changes = {}
        for ch, row in enumerate(seq.grid):
            c = row[s]
            name = c[K_NAME]
            a, d, tc = c[K_ANLG][i], c[K_DIG][i], c[K_TC][i]
            if lvcore.is_nan(a) and d == -1 and not tc:
                continue
            if c[K_SIG] == 1:
                val = d if d != -1 else (a if not lvcore.is_nan(a) else None)
            else:
                val = a if not lvcore.is_nan(a) else None
            if val is None:
                continue
            st = dict(value=val, since=E[i][E_NAME], t_ms=E[i][E_ABS])
            if tc:
                # ramp to the next edge (in time) where this channel has a value
                nxt = None
                for j in order:
                    if E[j][E_ABS] > E[i][E_ABS] and (not lvcore.is_nan(c[K_ANLG][j]) or c[K_DIG][j] != -1):
                        nxt = j
                        break
                if nxt is not None:
                    st["ramp"] = dict(func=c[K_FUNC][i], step_ms=c[K_STEP][i], to=c[K_ANLG][nxt],
                                      until=E[nxt][E_NAME], t1_ms=E[nxt][E_ABS])
            state[name] = st
            changes[name] = st
        out.append(dict(edge=E[i][E_NAME], t_ms=E[i][E_ABS], changes=changes, state=dict(state)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--edges", help="comma-separated edge names (default: edges where a requested channel changes)")
    ap.add_argument("--all", action="store_true", help="every edge")
    ap.add_argument("--channels", help="comma-separated channel names (default: all analog channels)")
    ap.add_argument("--calib", default=CALIB)
    ap.add_argument("--json")
    ap.add_argument("--csv")
    a = ap.parse_args(argv)
    seq = Sequence.load(a.file)
    conv = Converter(a.calib)
    chans = [c.strip() for c in a.channels.split(",")] if a.channels else \
            [row[0][K_NAME] for row in seq.grid if row[0][K_SIG] == 0]
    convvi = dict((row[0][K_NAME], row[0][K_CONV]) for row in seq.grid)
    pins = dict((row[0][K_NAME], (row[0][K_CARD], row[0][K_CHAN])) for row in seq.grid)
    tl = timeline(seq)
    if a.edges:
        want = [e.strip() for e in a.edges.split(",")]
        stages = [st for st in tl if st["edge"] in want]
    elif a.all:
        stages = tl
    else:
        stages = [st for st in tl if any(c in st["changes"] for c in chans)]
    rows = []
    for st in stages:
        print("\n== %s  (t = %.3f ms)" % (st["edge"], st["t_ms"]))
        for ch in chans:
            if ch not in st["state"]:
                continue
            s = st["state"][ch]
            cv = conv.convert(convvi.get(ch, ""), ch, s["value"]) if isinstance(s["value"], float) else dict(volts=None, units="digital", how="")
            mark = "*" if ch in st["changes"] else " "
            ramp = ("  ramp %s -> %g by %s" % (s["ramp"]["func"], s["ramp"]["to"], s["ramp"]["until"])) if "ramp" in s else ""
            frac = ("  %.3f of max %g" % (cv["fraction_of_max"], cv["table_max"])) if cv.get("fraction_of_max") is not None else ""
            volts = ("%.4f V" % cv["volts"]) if cv.get("volts") is not None else "-"
            print(" %s %-32s %10g %-28s %10s  card %d ch %d%s%s  %s" % (mark, ch, s["value"], cv["units"], volts,
                  pins[ch][0], pins[ch][1], frac, ramp, cv.get("note", "") or ""))
            rows.append(dict(edge=st["edge"], t_ms=st["t_ms"], channel=ch, value=s["value"], units=cv["units"],
                             volts=cv.get("volts"), card=pins[ch][0], pin=pins[ch][1], since=s["since"],
                             fraction_of_max=cv.get("fraction_of_max"), table=cv.get("how"), note=cv.get("note", ""),
                             ramp=s.get("ramp")))
    if a.json:
        tables = {}
        for c in CONVERSIONS.values():
            for key in ("table", "low"):
                if c.get(key):
                    tables[c[key]] = conv.info(c[key])
        json.dump(dict(file=os.path.basename(a.file), calibration_dir=a.calib, tables=tables,
                       conversions=dict((k, v) for k, v in CONVERSIONS.items()),
                       channels=dict((ch, dict(conversion_vi=convvi.get(ch, ""), card=pins[ch][0], pin=pins[ch][1]))
                                     for ch in chans),
                       stages=rows), open(a.json, "w"), indent=1, sort_keys=True)
        print("\nwrote", a.json)
    if a.csv:
        with open(a.csv, "w") as f:
            w = csv.writer(f)
            w.writerow(["edge", "t_ms", "channel", "value", "units", "volts", "card", "pin", "since", "fraction_of_max", "table", "note"])
            for r in rows:
                w.writerow([r[k] for k in ("edge", "t_ms", "channel", "value", "units", "volts", "card", "pin", "since", "fraction_of_max", "table", "note")])
        print("wrote", a.csv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
