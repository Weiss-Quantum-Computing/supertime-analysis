#!/usr/bin/env python3
"""Convert a Supertime .dt4 sequence to an editable JSON file and back.

usage:
  dt4json.py <supertime.log or .head> export <file.dt4> <file.json>
  dt4json.py <supertime.log or .head> import <file.json> <file.dt4>

The JSON keeps every field of the LabVIEW data cluster, so import(export(x)) == x
byte for byte.  Layout of the JSON:

  settings    the card/clock settings and the file name
  sets        data-set names and which sets to run
  variables   [{name, value_ms}]
  edges       [{name, time_ms, parent, relative_ms, time_type, vars:[...]}]  (parent = edge index)
  channels    [{name, card, channel, signal_type, conversion_vi, edges:[per-edge entries]}]
              per-edge entry: [analog, digital, time_constant, function_type, step_ms]
              analog is null where the channel does not change at that edge (NaN in the file)

Channels are stored per data set: channels[set][channel].
"""
import json
import struct
import sys
from lvflat import read_datalog_header, decode_dt4, encode_dt4

# Supertime writes "no change" as a NaN with all bits set; keep that exact pattern on import
FILE_NAN = struct.unpack(">d", b"\xff" * 8)[0]

SETTINGS = ["Target \nResolution (us):", "Digital I/O",
            "Device number for analog card which does digital outputs", "Number of installed cards",
            "Virtual device number used to enter pseudo-digital outputs", "Device number for timing card",
            "File name", "Device and channel used to reset counters", "External vi"]


def to_json(data):
    nset = len(data["Channel Array"][0]) if data["Channel Array"] else 0
    channels = []
    for s in range(nset):
        col = []
        for row in data["Channel Array"]:
            c = row[s]
            per_edge = []
            for k in range(len(c["Edge Value (Anlg)"])):
                a = c["Edge Value (Anlg)"][k]
                per_edge.append([None if a != a else a,
                                 c["Edge Value (Dig)"][k],
                                 c["Time constant"][k],
                                 c["Function type"][k],
                                 c["Step size (ms)"][k]])
            col.append({"name": c["Channel Name"], "card": c["Card #"], "channel": c["Channel #"],
                        "edge_name_index": c["Edge Name"], "signal_type": c["Signal\nType"],
                        "conversion_vi": c["Conversion VI"], "edges": per_edge})
        channels.append(col)
    return {
        "format": data.get("_format", "dt4"),
        "settings": {k.replace("\n", " "): data[k] for k in SETTINGS},
        "sets": {"names": data["Set Name Array Input"], "to_run": data["Sets To Run Array Input"]},
        "variables": [{"name": v["Variable Name"], "value_ms": v["Variable Value (ms)"]} for v in data["Variable Array"]],
        "edges": [{"name": e["Edge Name"], "time_ms": e["Absolute Time (ms)"], "parent": e["Defined with Respect to"],
                   "relative_ms": e["Relative Time(ms)"], "time_type": e["Time Type:"],
                   "vars": e["Var Names         Time (ms)"]} for e in data["Edge Array"]],
        "channels": channels,
    }


def from_json(j):
    nset = len(j["channels"])
    nchan = len(j["channels"][0]) if nset else 0
    rows = []
    for ci in range(nchan):
        row = []
        for s in range(nset):
            c = j["channels"][s][ci]
            pe = c["edges"]
            row.append({"Channel Name": c["name"], "Card #": c["card"], "Channel #": c["channel"],
                        "Edge Name": c["edge_name_index"],
                        "Edge Value (Anlg)": [FILE_NAN if x[0] is None else x[0] for x in pe],
                        "Edge Value (Dig)": [x[1] for x in pe],
                        "Time constant": [x[2] for x in pe],
                        "Signal\nType": c["signal_type"],
                        "Function type": [x[3] for x in pe],
                        "Conversion VI": c["conversion_vi"],
                        "Step size (ms)": [x[4] for x in pe]})
        rows.append(row)
    settings = {k: j["settings"][k.replace("\n", " ")] for k in SETTINGS}
    data = {"Channel Array": rows,
            "Edge Array": [{"Absolute Time (ms)": e["time_ms"], "Edge Name": e["name"],
                            "Defined with Respect to": e["parent"], "Relative Time(ms)": e["relative_ms"],
                            "Var Names         Time (ms)": e["vars"], "Time Type:": e["time_type"]} for e in j["edges"]],
            "Variable Array": [{"Variable Name": v["name"], "Variable Value (ms)": v["value_ms"]} for v in j["variables"]],
            "Set Name Array Input": j["sets"]["names"], "Sets To Run Array Input": j["sets"]["to_run"],
            "_format": j.get("format", "dt4")}
    data.update(settings)
    return data


if __name__ == "__main__":
    td, _ = read_datalog_header(sys.argv[1])
    cmd, src, dst = sys.argv[2:5]
    if cmd == "export":
        data, _, _ = decode_dt4(src, td)
        json.dump(to_json(data), open(dst, "w"), indent=1)
    elif cmd == "import":
        data = from_json(json.load(open(dst if False else src)))
        open(dst, "wb").write(encode_dt4(data, td))
    else:
        sys.exit("unknown command %s" % cmd)
