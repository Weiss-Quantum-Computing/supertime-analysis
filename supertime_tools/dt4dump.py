#!/usr/bin/env python3
"""Human-readable dump of a Supertime .dt4 sequence file.

usage: dt4dump.py <supertime.log (for the type descriptor)> <file.dt4> [--edges] [--channels] [--json]
"""
import sys
import json
from lvflat import read_datalog_header, decode_dt4


def dump(data, show_edges=True, show_channels=True):
    chans = [c for row in data["Channel Array"] for c in row]
    edges = data["Edge Array"]
    variables = data["Variable Array"]
    print("File name field : %s" % data["File name"])
    print("External vi     : %s" % data["External vi"])
    print("Target resolution (us): %g   Digital I/O: %s   cards: %d   timing card dev: %d"
          % (data["Target \nResolution (us):"], data["Digital I/O"],
             data["Number of installed cards"], data["Device number for timing card"]))
    print("Sets: %s   sets to run: %s" % (data["Set Name Array Input"], data["Sets To Run Array Input"]))
    print("Channels: %d   Edges: %d   Variables: %d" % (len(chans), len(edges), len(variables)))

    print("\n--- Variables (ms) ---")
    for v in variables:
        print("  %-40s %g" % (v["Variable Name"], v["Variable Value (ms)"]))

    if show_edges:
        print("\n--- Edges (sorted by absolute time, ms) ---")
        order = sorted(range(len(edges)), key=lambda i: edges[i]["Absolute Time (ms)"])
        for i in order:
            e = edges[i]
            ref = e["Defined with Respect to"]
            refname = edges[ref]["Edge Name"] if ref < len(edges) else "?"
            vars_ = [variables[k]["Variable Name"] if k < len(variables) else "?" for k in e["Var Names         Time (ms)"]]
            print("  [%3d] %12.4f  %-40s  = %-30s + %10.4f  type=%d %s"
                  % (i, e["Absolute Time (ms)"], e["Edge Name"], "'" + refname + "'",
                     e["Relative Time(ms)"], e["Time Type:"], ("vars=" + "+".join(vars_)) if vars_ else ""))

    if show_channels:
        print("\n--- Channels ---")
        for c in chans:
            n = len(c["Edge Value (Anlg)"])
            print("  %-34s card %d ch %2d  sig=%d  edges=%d  conv=%s"
                  % (c["Channel Name"], c["Card #"], c["Channel #"], c["Signal\nType"], n,
                     c["Conversion VI"].split("\\")[-1] if c["Conversion VI"] else "-"))
            if n and show_edges:
                for k in range(n):
                    ft = c["Function type"][k] if k < len(c["Function type"]) else ""
                    ss = c["Step size (ms)"][k] if k < len(c["Step size (ms)"]) else ""
                    tc = c["Time constant"][k] if k < len(c["Time constant"]) else ""
                    ename = edges[k]["Edge Name"] if k < len(edges) else "?"
                    a = c["Edge Value (Anlg)"][k]
                    d = c["Edge Value (Dig)"][k] if k < len(c["Edge Value (Dig)"]) else ""
                    if ft or (a == a and d != 0) or a == a:  # a==a filters NaN
                        print("        %-40s anlg=%-10s dig=%-3s %-20s step=%s tc=%s"
                              % (ename, ("%g" % a) if a == a else "NaN", d, ft, ss, tc))


if __name__ == "__main__":
    log, path = sys.argv[1], sys.argv[2]
    td, _ = read_datalog_header(log)
    data, used, size = decode_dt4(path, td)
    if used != size:
        print("WARNING: consumed %d of %d bytes" % (used, size))
    if "--json" in sys.argv:
        print(json.dumps(data, indent=1))
    else:
        dump(data, show_edges="--channels" not in sys.argv, show_channels="--edges" not in sys.argv)
