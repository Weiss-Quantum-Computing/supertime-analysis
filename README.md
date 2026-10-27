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

## Requirements

Python 3 (standard library only for the sequence tools). `pylabview` and ghostscript were
used to extract VIs and render the printouts.

## Typical use

```bash
python3 supertime_tools/dt4dump.py <supertime.log-or-its-1MB-head> <sequence.dt4>
python3 supertime_tools/logscan.py <supertime.log>
```
