# Supertime file formats (reverse-engineered 2026-10-27)

Source: `MAARTEN USB/Supertime Computer/Documents and Settings/...`
The control PC runs Windows XP with **LabVIEW 6.1** (`Program Files/National Instruments/LabVIEW 6.1`).
All binary files are big-endian LabVIEW "flattened data".

## Where things live

| Path | What |
|---|---|
| `Experiment control/Desktop/Supertime/` | The live program. `supertime-ExternalTrigger-pauseChannelUpdateV0.vi` (Sep 2 2026) is the main VI the Admin shortcuts point to; `Xiao supertime-...vi` (Sep 9) and `supertime.vi` (Jan 2026) are variants. The rest of the folder is image analysis (SPE, count atoms, flatfield). |
| `.../Supertime/supertime sub vi's/` | 190 subVIs, the typedefs (`channel.ctl`, `edge.ctl`, `variable.ctl`, `data cluster.ctl`), the AOM/EOM calibration lookup tables (`*.txt`, two tab-separated columns: input -> output), and the run logs `supertime*.log`. |
| `.../Supertime/Copy of Supertime/` | Older snapshot of the same folder (lacks the 2025 two-EOM additions). |
| `Admin/Desktop/Supertime/` | Another older snapshot (2019-2021 era VIs). |
| `Admin/Desktop/supertime-CustomRamp-ExternalTrigger-pauseChannelUpdateV0*.vi`, `Admin/Desktop/V2 Xiao/` | Development copies adding "Custom" ramps (ramp shape loaded from CSV). |
| `Admin/My Documents/<year>/...` | 1897 sequence files `*.dt4` (plus 2007-08 `*.dt3`), organised by year. `2025 Readme.txt` is the change log. |
| `Admin/Desktop/Ramps`, `My Documents/2026/Ramps` | ILC-learned EOM drive waveforms (`drive_*_i15.csv`, `time_us,voltage_V`) and the split `_upramp/_downramp.csv` (`index,value`) that the Custom ramp reads. |
| `Admin/Desktop/Waveform-Editor-GUI` | Python 2.7 editor that makes those ramp files (README + transfer note). |
| `Admin/Desktop/AOMrescale` | Python 2.7 tool (Ted Corcovilos 2013) that rescales the calibration `.txt` tables; `aomlog.txt` is the history of max-power values. |
| `Admin/Desktop/SavedMatrices` | Text dumps of the compiled output matrices (analog voltages / DIO values per card, times). |
| `Documents and Settings/Old supertime logs/` | Five more 2 GB run logs, 2017-2018. |

## `.dt4` sequence file

A flattened `data cluster.ctl` (no header, no type info). The type descriptor is embedded in the
header of every `supertime*.log` datalog file, which is how `lvflat.py` learns the layout:

```
data cluster.ctl  (cluster, 14 fields)
  Channel Array            2-D array [nchannels x 1] of channel.ctl
  Edge Array               1-D array of edge.ctl
  Variable Array           1-D array of {Variable Name: string, Variable Value (ms): DBL}
  Set Name Array Input     array of string          (e.g. ['run'])
  Sets To Run Array Input  array of I32
  Target Resolution (us)   DBL                      (1 us)
  Digital I/O              bool (1 byte)
  Device number for analog card which does digital outputs   U8
  Number of installed cards    I32                  (9)
  Virtual device number used to enter pseudo-digital outputs U8
  Device number for timing card  I16                (5)
  File name                string                   (the .dt4 name)
  Device and channel used to reset counters  array of U8
  External vi              path  ('Main external dispatch.vi')   <- absent in .dt3

channel.ctl (11 fields)
  Channel Name   string
  Card #         U16   (U8 in the 2007-08 .dt3 files)
  Channel #      U8
  Edge Name      I32   (index of the edge currently shown on the panel)
  Edge Value (Anlg)  array of DBL, one per edge; NaN = "no change at this edge"
  Edge Value (Dig)   array of I8,  one per edge; -1 = no change, 0/1 = level
  Time constant      array of DBL, one per edge
  Signal Type        I32  (0 = analog, 1 = digital)
  Function type      array of enum16 per edge: '', Exponential, Optical: 1/(1+t)^2,
                     Optical with offset, Linear, Depth lin freq const, Gaussian,
                     Blackman, Cubic, Custom
  Conversion VI      path (lookup-table VI, e.g. TrekXEO1_20250731.vi)
  Step size (ms)     array of DBL per edge (ramp step; must share a common multiple >= 2 us)

edge.ctl (6 fields)
  Absolute Time (ms)       DBL
  Edge Name                string
  Defined with Respect to  U16  (index of the parent edge)
  Relative Time(ms)        DBL
  Var Names                array of I32 (indices into Variable Array)
  Time Type                I32  (0 = fixed relative time, 1 = time comes from the variable)
```

Encoding rules: strings and arrays are prefixed by I32 length / dimension sizes; paths are
`'PTH0'`, I32 length, I16 type, I16 segment count, Pascal segments; enums are U16; bools 1 byte.

## `supertime*.log` run history

LabVIEW datalog: `'DTLG'`, version, I32 record count, I32 offset of the master index block,
then the record type descriptor, then 512-byte index blocks (128 I32 record offsets each).
Each record is `{date string, time string, data cluster.ctl}` - the complete sequence that was
running at that moment, so the logs are a full, timestamped history of every run.

| Log | Records | Span |
|---|---|---|
| supertime20221010.log | 3051 | 2022-07-21 .. 2022-10-10 |
| supertime20230413.log | 5812 | 2022-10-10 .. 2023-04-13 |
| supertime20230921.log | 3322 | 2023-04-13 .. 2023-09-20 |
| supertime 20260218.log | 4077 | 2025-08-20 .. 2026-02-17 |
| supertime.log (current) | 882 | 2026-09-03 .. 2026-10-27 |
| Old supertime logs/*.log | not yet scanned | 2017-2018 |

`Step time variables.log` and `2026/Ramps/step time series log` are datalogs with a different
record type (a variable-step scan: Variable Array, Channel Array, Edge Array, Variable steps,
Number of steps, vi path, flags). Same tooling applies; `logscan.py --list` assumes the run-log type.

## Tools in this folder

```
python3 lvflat.py  <supertime.log>                 # print the type tree
python3 dt4dump.py <supertime.log> <file.dt4>      # readable dump (--edges / --channels / --json)
python3 logscan.py <supertime.log>                 # list every run (idx, date, time, file, edges, vars, cycle)
python3 logscan.py <log> --extract N out.dt4       # recover the sequence of run N as a .dt4
python3 checkall.py <supertime.log> <folder>       # decode every .dt4/.dt3 under a folder
```

Verified: 1895 of 1897 `.dt4` under `My Documents` and all 27 `.dt3/.dt4` in the sub-VI folder
decode with zero bytes left over. The two failures (`2016/Copy of uwave.dt4`,
`2016/Cooling/Coolingxyzpart_500us ramp_100us OP_20171109.dt4`, both dated 2017-12-11) end
mid-way through a channel's conversion-VI path: truncated saves, not a format variant.

## Not yet readable

* `.vi` / `.ctl` (LabVIEW 6.1 binaries): only names, labels and the linked-subVI list can be
  pulled out with `strings`. Block-diagram logic needs LabVIEW, or the open-source `pylabview`
  parser (LV 6/7 diagrams are not compressed, so it can dump them to XML).
* `supertime.ps` / `supertime1.ps` (7-page PostScript printouts of the VI from 2009-01-06):
  render with ghostscript (not installed).
* `SupertimeLog.rar`, `supertime_050411.rar`: need `unar`/7-zip (not installed).
* `.spe` camera images: Princeton Instruments WinView format, 4100-byte header; readable with a
  small reader if wanted.

## LabVIEW 6.1 block-diagram / front-panel heaps (BDHP, FPHP) - reverse-engineered 2026-10-27

pylabview (`readRSRC -x`) splits a VI into blocks but cannot parse the LabVIEW 6.1 heaps.
`lvheap6.py` walks them raw; `lvdiagram6.py` turns a block diagram into a readable netlist.
Findings, all verified against the 208 VIs in `supertime sub vi's` plus the main VI:

* Heap = 0x38-byte header, then records `[I32 size][I32 chunk][I32 class id][payload]`.
  A payload word is a reference when it equals another record's start + 0xC. Memory
  pointers from the saving machine are serialised as-is (ignore them).
* `0x07` pointer list `[count][ptr..]`; `0x7e` heap root; `0x1b` diagram (w2 node list,
  w4 wire list, w5 background colour); `0x1d` per-diagram holder of FP terminals and
  structure-border terminals; `0x0a` text label (w1 owner, w4/w5 bounds as
  top<<16|left, bottom<<16|right).  Label text is not in the heap: it is the `TRec`
  resource whose stored rectangle matches the label bounds (+-1 px).  Labels of
  FP terminals and of constants have no TRec (text comes from the control / the data).
* Nodes share a header: w0 flags, w1 owning diagram, w2 terminal list, w3 label, w4/w5
  bounds.  `0x15` terminal: w1 owner, w2 wire, w3 per-class descriptor.  `0x17` wire:
  w2 list of the terminals it joins (connectivity); `0x18` its on-screen path.
* `0x16` front-panel terminal: w3 = offset of the control's DCO (`0x12`) in the FPHP
  heap; DCO w5 = the control; the control's parts list holds its caption label.
* `0x31` subVI call: label = VI name; terminal descriptors `0x33`, w9 = connector-pane
  index; parameter names come from the callee's `CPTM` block (type descriptors with
  the control labels, in connector order).
* `0x2f` primitive: last word >> 16 is a `CURS` string-resource id in LabVIEW 6.1's
  `resource/labview.rsc` (table in `lv61_strings.json`): 1102 = Equal?, 1050 = Add,
  1052 = Multiply, 1809 = Array Size, ...  Terminal descriptors `0x30`.
* `0x32` local variable (descriptor `0x67`, w3 = FPHP offset of the control's DCO).
  `0x8c` property node (label = control name, `0x8e` property terminals, `0x8d` refnum).
* Structures: `0x20` For loop (`0x24` i, `0x26` N), `0x21` While loop (`0x25` stop),
  `0x2c` Case (`0x2d` tunnels, `0x2e` selector), `0x29` Sequence (`0x2a` tunnels /
  locals, `0x2b` frame terminal).  Sub-diagrams are the list in w13; `0x22`/`0x23`
  loop tunnels; `0x27`/`0x28` shift registers.  Border terminals owned by a `0x1d`
  holder are the inner side.
* `0x13` diagram constant (DCO): w5 = display object (`0x50` numeric, `0x51` string,
  `0x52` array, `0x57` enum/ring, `0x5b` boolean, `0x64` cluster).  Values live in the
  `DFDS` default-data block, which is not decoded yet; enum/ring and labelled constants
  show their text.
* Built-in nodes that are not primitives have their own classes.  Best guesses from
  terminal patterns: `0x44` Index Array, `0x63` Bundle/Unbundle By Name, `0x93` Format
  Into String, `0x3a`, `0xb9`, `0x48`, `0x4a`, `0x34`, `0x36` unknown.

Outputs: `../vi_diagrams/<VI>.txt` (one per VI, main VI as `MAIN_*.txt`).  Each lists the
diagram tree (frames of every structure), nodes with ids, bounds and names, and every wire
as the list of terminals it connects (`N12.3`, `N5.tunnel@(x,y).in`, `N7.Edge Names`).

## Data space (DSTM) and default data (DFDS) - partial, 2026-10-27

* `DSTM` is one cluster descriptor listing the VI's data space in memory order.  Member
  code `0x63` = raw slot (I16 ?, I16 size, I16 align); `0x83` wraps another descriptor
  (handle slots); each front-panel control owns an `ext` cluster `{udf{flg,oRt,eof},
  <data type labelled with the control name>, dfd, txd, old, ext}`.
* Data-space layout is byte-packed: scalars natural size, strings/arrays/paths 4-byte
  handles, fixed-size arrays inline.  Checked against the DS offsets carried by the DCO
  records (`0x12`/`0x13` word 6) and the DFDS header table.
* A block-diagram constant's DCO (`0x13`) has w6 = DS offset of its value slot and
  w7 = DSTM offset of its type, which is a top-level member flagged `0x28`
  (strings/enums `0x60`/`0x68`).  Front-panel DCOs point w7 at their `ext` cluster.
* `DFDS` = [43 x I32 header: (count, DS offset, DSTM offset) triples and other fields]
  [fill stream] [init table: little-endian (DS offset | flags, DSTM offset) pairs].
  The fill stream holds, in DSTM order, the defaults of the members flagged `0x20`
  (numeric min/max/increment triples, array index clusters, control default data);
  strings are I32-length `LStr`, paths `PTH0`+I32 len+content, variable arrays I32 dims
  + elements, fixed arrays I32 count + elements.  The walk tiles about a quarter of the
  VIs exactly and drifts in the rest, so one or more member kinds are still mis-sized.
* The `0x28`/`0x68` constant members are NOT in that fill stream; where their values
  are stored is still unknown.  String constants can be spotted in DFDS as `LStr`
  text (e.g. 'supertime.log', '%-26.25s%4.3f') but not yet attributed to a DCO
  mechanically.  `lvdstm.py` prints the member list and the fill walk for a VI.
