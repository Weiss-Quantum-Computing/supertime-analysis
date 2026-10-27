# External sequence editor: plan

**Status 2026-10-27:** v1 implemented in `supertime_editor/` (Tkinter, Python 2.7/3): grid
editor, edge/variable/channel editing, compare + unify. Not yet run on the XP machine.


Goal: edit Supertime sequences (`.dt4`) outside LabVIEW, because Supertime itself is slow and
runs out of memory on the longest sequences (1,400 to 1,550 edges, 56 channels, up to 2.4 MB).

## What a sequence file is (established 2026-10-27)

* A `.dt4` is the flattened LabVIEW `data cluster.ctl`, with no header. `lvflat.py` decodes
  it with the type descriptor taken from any `supertime*.log` header, and `encode_dt4` writes
  it back. All 1,922 readable files on the control PC round-trip byte for byte.
* Contents: **edges** (named time points; each is defined relative to a parent edge, with an
  optional timing variable), **variables** (named times in ms), and a 2-D **channel array**
  [channel x data set]. A data set is one iteration of a scan (`run, iteration #3`); most
  files have one set. Each channel holds, per edge: analog value (NaN = no change), digital
  value (-1 = no change), ramp function (Linear, Exponential, Optical, Cubic, Custom...),
  step size and time constant. Ramps are expanded by Supertime at generate time, not stored.
* The file does not contain the compiled card data; Supertime regenerates that on load.

## Sizes that matter (2024-2026 files)

| year | files | edges (median / max) | channels | variables (max) |
|---|---|---|---|---|
| 2024 | 42 | 1335 / 1367 | 29-56 | 60 |
| 2025 | 77 | 70 / 1343 | 30-56 | 1860 (block files) |
| 2026 | 79 | 1351 / 1554 | 54-56 | 244 |

The big ones are the 9-plane cooling and microwave sequences. A 1,500 x 56 grid is small for
any ordinary program; the slowness is LabVIEW 6.1 recomputing and redrawing everything.

## Building blocks already in place

1. `lvflat.decode_dt4` / `encode_dt4`: lossless read and write.
2. `dt4json.py`: the same data as editable JSON (`channels[set][channel].edges[k] =
   [analog, digital, time_constant, function, step]`).
3. `dt4dump.py`: human-readable view (timeline, per-channel values).

## What the editor must do

* Load a `.dt4`, show edges as a timeline and channels as a grid (edge x channel), edit
  values, ramp types and step sizes, add/remove/rename edges and variables, and save a `.dt4`
  that Supertime loads unchanged.
* Recompute absolute edge times from parent + relative time + variable, the way
  `Calculate Times.vi` does (the file stores both; Supertime recalculates on load, so the
  stored absolute time only needs to be consistent).
* Keep the invariants Supertime relies on: every channel has exactly one entry per edge,
  arrays stay aligned when an edge is inserted or deleted, ramp start/end pairs stay matched,
  simultaneous ramps use step sizes with a common multiple of 2 us (the 2025 readme bug).
* Splice blocks: the `blocks/` and `cooling blocks/` folders are partial sequences that get
  spliced into full ones; the editor should be able to append a block's edges and channel
  columns to a sequence.
* Diff two sequences (which edges/values changed), since the files are mostly copies of each
  other with small edits.

## Suggested shape

A single-page web app (plain HTML/JS, runs from a file, no server) backed by the JSON from
`dt4json.py`, or a Python desktop app. Either way the Python decode/encode stays the single
source of truth for the file format; the UI only edits the JSON model. The grid view is the
core: edges as columns in time order, channels as rows, cells showing value and ramp
function, with a timeline strip above it.

Open questions for Maarten: web page vs desktop app; whether editing happens on the control
PC (Python 2.7, XP) or on the Mac with files moved over; which views matter most day to day.
