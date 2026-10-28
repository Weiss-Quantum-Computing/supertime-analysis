# -*- coding: utf-8 -*-
"""Build a cooling spin-echo sequence for the campaign-20261014 custom ramps, and its ramp path table.

usage: python -m supertime_tools.newramps RECORD [--base FILE] [--out FILE] [--table ramp_table.csv]
                                                  [--paths OUT.csv] [--old-paths ramp path.csv]

Each spin-echo leg becomes four Custom ramps on Trek X#1 / X#2 (rows 47 / 48): up (EO ramp up 0 ->
EO ramp up 3), hold (up 3 -> down 3), down (down 3 -> down 0) and after (down 0 -> the next leg's up 0,
or "1: EO after end" for leg 2).  Durations and cell voltages come from the campaign's ramp_table.csv;
a chunk marked "held value" gets its cells set and no ramp.  The inert intermediate edges of the old
three-segment ramps (up 1, up 2, down 2, down 1) are removed and each leg gets its own duration
variables.  The path table lists the chunk files at the ramp numbers the built sequence actually has.
"""
from __future__ import print_function, division
import argparse, csv, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from supertime_editor.model import (Sequence, E_NAME, E_PARENT, E_REL, E_TYPE, E_VARS, K_NAME,
                                    K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP, V_NAME, V_VAL, cost)
from supertime_editor.audit import audit

HERE = os.path.dirname(os.path.abspath(__file__))
SEQ = os.path.join(os.path.dirname(HERE), "sequences", "2026")
BASE = os.path.join(SEQ, "Cooling(30+10)_3ms_X2detect_2EOx_checkcooling_9planes_changed imaging.dt4")
TABLE = os.path.join(SEQ, "Ramps", "campaign-20261014", "ramp_table.csv")
OLD_PATHS = os.path.join(SEQ, "Ramps", "ramp path.csv")
PC_DIR = u"C:\\Documents and Settings\\Admin\\My Documents\\2026\\Ramps\\campaign-20261014\\"
CH = {"X1": "Trek HV Amplifier X#1", "X2": "Trek HV Amplifier X#2"}
LEG_SPACING_MS = 16.67            # the records' up starts are 16670 us apart
CHUNKS = ("up", "hold", "down", "after")
# chunk -> (start edge, end edge) per leg; {p} is "" for leg 1 and "1: " for leg 2
EDGES = {"up": ("{p}EO ramp up 0", "{p}EO ramp up 3"), "hold": ("{p}EO ramp up 3", "{p}EO ramp down 3"),
         "down": ("{p}EO ramp down 3", "{p}EO ramp down 0"),
         "after": ("{p}EO ramp down 0", {"1": "1: EO ramp up 0", "2": "1: EO after end"})}
INERT = ("EO ramp up 1", "EO ramp up 2", "EO ramp down 2", "EO ramp down 1")
OLD_VARS = ("EO upRamp1 Time Leg 2", "EO upRamp2 Time Leg 2", "EO upRamp3 Time Leg 2",
            "EO dnRamp1 Time Leg 2", "EO dnRamp2 Time Leg 2", "EO dnRamp3 Time Leg 2")


def _open_csv(path):
    if sys.version_info[0] == 2:
        return open(path, "rb")
    return open(path, "r", newline="")


def read_table(path, record):
    rows = [r for r in csv.DictReader(_open_csv(path)) if r["record"] == record]
    if not rows:
        raise SystemExit("record %s not in %s" % (record, path))
    T = {}
    for r in rows:
        T[(r["channel"], r["leg"], r["chunk"])] = r
    return T


def build(seq, T):
    def E(name):
        i = seq.find_edge(name)
        if i < 0:
            raise KeyError(name)
        return i
    # 1. the inert intermediate edges carry nothing: drop them
    for p in ("", "1: "):
        for n in INERT:
            i = E(p + n)
            for ch in range(len(seq.grid)):
                if seq.cell_is_change(ch, i):
                    raise SystemExit("%s has a value on %s" % (p + n, seq.grid[ch][0][K_NAME]))
            seq.delete_edge(i)
    # 2. per-leg duration variables (ms); leg 2 keeps the existing "EO Hold Time Leg 2"
    dur = lambda leg, chunk: float(T[("X1", leg, chunk)]["duration_us"]) / 1000.0
    for leg in ("1", "2"):
        for chunk, vname in (("up", "EO up Time Leg %s"), ("hold", "EO Hold Time Leg %s"), ("down", "EO down Time Leg %s")):
            vname %= leg
            k = seq.find_variable(vname)
            if k < 0:
                k = seq.add_variable(vname, dur(leg, chunk))
            else:
                seq.variables[k][V_VAL] = dur(leg, chunk)
    k_after = seq.add_variable("EO after Time Leg 2", dur("2", "after"))
    for n in OLD_VARS:
        k = seq.find_variable(n)
        if k >= 0:
            seq.delete_variable(k)
    k_leg = seq.find_variable("Spin Echo Leg Time")
    seq.variables[k_leg][V_VAL] = LEG_SPACING_MS
    # 3. wire the leg edges to their variables
    for leg, p in (("1", ""), ("2", "1: ")):
        for chunk, (a, b) in (("up", ("EO ramp up 0", "EO ramp up 3")), ("hold", ("EO ramp up 3", "EO ramp down 3")),
                              ("down", ("EO ramp down 3", "EO ramp down 0"))):
            vname = {"up": "EO up Time Leg %s", "hold": "EO Hold Time Leg %s", "down": "EO down Time Leg %s"}[chunk] % leg
            e = seq.edges[E(p + b)]
            e[E_PARENT] = E(p + a); e[E_TYPE] = 1; e[E_VARS] = [seq.find_variable(vname)]
            e[E_REL] = seq.variables[seq.find_variable(vname)][V_VAL]
    seq.add_edge("1: EO after end", E("1: EO ramp down 0"), dur("2", "after"), time_type=1, var_indices=[k_after])
    seq.recompute_times()
    # 4. Trek cells from the table: start cell of every chunk (Custom, 10 us) and the final end cell
    func = seq.grid[seq.find_channel(CH["X1"])][0][K_FUNC][E("EO ramp up 0")] or u"Custom"
    for chn, chname in CH.items():
        ch = seq.find_channel(chname)
        for leg, p in (("1", ""), ("2", "1: ")):
            for chunk in CHUNKS:
                r = T[(chn, leg, chunk)]
                a, b = EDGES[chunk]
                a = a.format(p=p)
                held = bool(r["note"].strip())
                fields = {K_ANLG: float(r["start_V_supertime"]), K_DIG: -1}
                if held:
                    fields.update({K_TC: 0.0, K_FUNC: u"", K_STEP: 1.0})
                else:
                    fields.update({K_TC: 1.0, K_FUNC: func, K_STEP: float(r["step_us"]) / 1000.0})
                seq.set_cell(ch, E(a), **fields)
        r = T[(chn, "2", "after")]
        seq.set_cell(ch, E("1: EO after end"), **{K_ANLG: float(r["end_V_supertime"]), K_DIG: -1, K_TC: 0.0,
                                                   K_FUNC: u"", K_STEP: 1.0})
    for i, e in enumerate(seq.edges):            # variable-timed edges store the variable value, as Supertime does
        if e[E_TYPE] == 1 and e[E_VARS]:
            e[E_REL] = seq.relative_time(i)
    seq.recompute_times()
    return seq


def ramp_numbers(seq, T):
    """{(channel, leg, chunk): ramp number} from the enabled ramps the built sequence has."""
    out = {}
    for chn, chname in CH.items():
        ch = seq.find_channel(chname)
        by_start = {}
        for n, r in enumerate(seq.ramps(ch)):
            by_start.setdefault(seq.edges[r.i0][E_NAME], n)
        for leg, p in (("1", ""), ("2", "1: ")):
            for chunk in CHUNKS:
                if T[(chn, leg, chunk)]["note"].strip():
                    continue
                out[(chn, leg, chunk)] = by_start[EDGES[chunk][0].format(p=p)]
    return out


def write_paths(old_csv, out_csv, seq, T, numbers):
    raw = open(old_csv, "rb").read()
    nl = b"\r\n" if b"\r\n" in raw else b"\n"
    rows = [line.decode("latin-1").split(",") for line in raw.split(nl)]
    for chn, chname in CH.items():
        row = seq.find_channel(chname)
        for col in list(range(128, 160)):               # clear the echo slots, keep 0/1 (EO Ramp Tests)
            rows[row][col] = ""
        for (c, leg, chunk), n in numbers.items():
            if c == chn:
                rows[row][n] = PC_DIR + T[(c, leg, chunk)]["file"].replace("/", "\\")
    open(out_csv, "wb").write(nl.join(",".join(r).encode("latin-1") for r in rows))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("record")
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out")
    ap.add_argument("--table", default=TABLE)
    ap.add_argument("--paths")
    ap.add_argument("--old-paths", default=OLD_PATHS)
    a = ap.parse_args(argv)
    out = a.out or a.base.replace(".dt4", "_newramps.dt4")
    paths = a.paths or os.path.join(os.path.dirname(a.old_paths), "ramp path_%s_newramps.csv" % a.record)
    T = read_table(a.table, a.record)
    seq = build(Sequence.load(a.base), T)
    seq.save(out)
    seq = Sequence.load(out)
    numbers = ramp_numbers(seq, T)
    write_paths(a.old_paths, paths, seq, T, numbers)
    print("wrote", out)
    print("wrote", paths)
    print("edges %d, variables %d, cycle %.3f ms, cost: %s" % (len(seq.edges), len(seq.variables), seq.cycle_length(),
          ", ".join("%s=%s" % (k, cost(seq)[k]) for k in ("points", "steps", "level_text"))))
    for key in sorted(numbers, key=lambda k: (k[0], int(k[1]), CHUNKS.index(k[2]))):
        print("  ramp %3d  %s leg %s %-5s %s" % (numbers[key], key[0], key[1], key[2], T[key]["file"].split("/")[-1]))
    probs = seq.check()
    warns = [f for f in audit(seq) if f.severity == "error"]
    print("check:", probs or "ok", "| audit errors:", warns or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
