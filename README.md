# Supertime Analysis

Tools and reverse-engineering notes for **Supertime**, the LabVIEW 6.1 experiment-control
program on the lab's Windows XP control PC. Started 2026-10-27 from a copy of the control
PC's disk (kept separately, not in this repository).

## What is here

| Path | Contents |
|---|---|
| `supertime_tools/FORMAT_NOTES.md` | Everything worked out about the file formats: `.dt4` sequence files, the `supertime*.log` run logs, the LabVIEW 6.1 front-panel/block-diagram heaps, and the partially decoded data-space defaults. |
| `supertime_tools/lvflat.py` | LabVIEW type-descriptor parser and unflattener. Decodes `.dt4`/`.dt3` sequence files using the descriptor embedded in a run-log header. |
| `supertime_tools/dt4dump.py` | Readable dump of a sequence file: variables, edges (absolute times, parents), channels with per-edge values and ramp functions. |
| `supertime_tools/logscan.py` | Walks a run log: lists every run (date, time, sequence file, cycle length) and can recover any run's sequence as a `.dt4`. |
| `supertime_tools/checkall.py` | Decodes every sequence file under a folder and reports failures. |
| `supertime_tools/lvheap6.py`, `lvdiagram6.py` | Raw walker and netlist reconstructor for LabVIEW 6.1 block diagrams (run on a VI extracted with pylabview `readRSRC -x`). |
| `supertime_tools/vi_calltree.py` | SubVI call tree and text labels for a folder of VIs. |
| `supertime_tools/lvdstm.py` | Exploration tool for the data-space type map and default-data block (constant values, unfinished). |
| `supertime_tools/lv61_strings.json` | String tables from LabVIEW 6.1's `labview.rsc`; the `CURS` table maps primitive ids to names. |
| `vi_diagrams/` | One text netlist per VI (209), `MAIN_*.txt` is the main program. |
| `vi_printouts/` | The 2009 front-panel printout rendered from PostScript. |
| `supertime_tools/subvi_calltree.txt`, `subvi_text_labels.txt`, `main_vi_text_labels.txt` | Call graph and all panel/diagram text, including diagram comments. |

## Sequence editor (`supertime_editor/`)

A Tkinter desktop app that opens, edits, compares and saves `.dt4` sequences outside LabVIEW.
Python 2.7 (the XP control PC) and Python 3 (Mac), standard library only.

```bash
python3 -m supertime_editor.app "some sequence.dt4"     # Mac/Linux, or double-click supertime_editor.command
supertime_editor.bat "some sequence.dt4"                 # Windows XP (uses C:\Python27)
```

* Grid of channels (rows) by edges in time order (columns); cells show the analog or digital
  value and a ramp marker (L linear, E exponential, O optical, C cubic, K custom). Double-click
  a cell to edit value, ramp, step size and time constant; double-click a column header to
  edit the edge (name, parent, relative time, variable); the Edges and Variables tabs list
  everything and jump the grid to the selected edge.
* Add/delete edges, variables and channels; absolute times are recomputed exactly the way
  Supertime does (parent + relative or variable time, rounded to the clock resolution).
* **Compare with...** opens a second sequence and lists every difference: cell values,
  ramps and step sizes, edge times/parents/variables, missing edges or channels, variables,
  settings. Select rows and copy A->B or B->A, or unify everything in one go; save either side.
  Two 1,400-edge cooling sequences compare in 0.1 s and unify in under a second.
* Files whose channel arrays are shorter than the edge list (over half of the 2024-2026
  files) are read tolerantly; **File > Repair channel arrays** pads them.

`supertime_editor/lvcore.py` is the canonical reader/writer (`record.td` carries the LabVIEW
type descriptor so no log file is needed); `model.py` the editable model; `diff.py` the
comparison and unify logic; `app.py` the GUI.

![editor grid](docs/editor_grid.png)

## Requirements

Python 3 (standard library only for the sequence tools). `pylabview` and ghostscript were
used to extract VIs and render the printouts.

## Typical use

```bash
python3 supertime_tools/dt4dump.py <supertime.log-or-its-1MB-head> <sequence.dt4>
python3 supertime_tools/logscan.py <supertime.log>
```
