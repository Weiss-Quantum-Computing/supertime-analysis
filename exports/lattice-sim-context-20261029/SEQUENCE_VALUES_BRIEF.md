# Reading Supertime sequences for the lattice simulation: from `.dt4` values to what the atoms see

For the lattice-sim project (or any agent working on it). It explains how the experiment's settings
are stored, how a number in a sequence file becomes a control voltage, which calibration file fixes
the physical meaning of that number, and what is *not* in the files. The worked example is the
molasses power during the 1 s hold of the PGC vapor-loading sequence. Everything here was read from
the files on the control PC's disk copy on 2026-10-29 (paths below); the conversion VIs were decoded
from their LabVIEW 6.1 block diagrams and front-panel defaults.

Companion files (in `exports/lattice-sim-context-20261029/` of the supertime-analysis repository):

| File | What |
|---|---|
| `PGC_vapor_loading_9 planes.dt4` | the sequence itself |
| `PGC_vapor_loading_9 planes.values.json` / `.csv` / `.txt` | every analog channel at every edge: value in user units, card volts, fraction of the AOM table maximum, ramps |
| `calibration tables/*.txt` | the conversion tables the control PC uses (copied 2026-10-29) |
| `calibration tables/aomlist.txt`, `aomlog_2024-2026.tsv` | AOMrescale's channel list and the history of "maximum power" values typed in |

Regenerate the values for any sequence with the tool in `supertime_tools/stage_values.py`:

```
python -m supertime_tools.stage_values "sequences/2026/PGC_vapor_loading_9 planes.dt4" --all --json out.json --csv out.csv
python -m supertime_tools.stage_values FILE.dt4 --channels "Molasses beams,Repump" --edges "Pic before I done,Junk image 3 start"
```

## 1. The chain from a sequence number to a beam

```
value in the .dt4 (user units, e.g. 0.6)
   -> Supertime's "Convert UD units to Volts.vi" opens the channel's conversion VI by reference
   -> the conversion VI reads its calibration table (a two-column text file, x = card volts, y = user units)
      and finds the x where y crosses the value (piecewise linear, LabVIEW "Threshold 1D Array")
   -> that voltage goes to the analog output card (card #, channel # from the sequence)
   -> the card drives the AOM RF driver (or coil driver, Trek amplifier, piezo ...)
   -> optical power in the beam
```

So the number in the sequence is in the units of the table's y column, and the table's y column is
whatever was measured when the table was made, rescaled since by AOMrescale (section 4). For the beam
channels the lab's convention is optical power in mW at the point where the maximum was last measured.

Where things live on the control PC (Windows XP). The disk copy used here is the folder
`Supertime Computer` next to the supertime-analysis repository, with the same layout:

| What | Path on the PC |
|---|---|
| Sequences (`.dt4`) | `C:\Documents and Settings\Admin\My Documents\2026\` |
| Conversion VIs and their tables | `C:\Documents and Settings\Experiment control\Desktop\Supertime\supertime sub vi's\` |
| AOMrescale (channel list, log) | `C:\Documents and Settings\Admin\Desktop\AOMrescale\` |

## 2. Reading a `.dt4`

Use the editor's model (Python 2.7 or 3, standard library only; run from the supertime-analysis folder):

```python
from supertime_editor.model import Sequence, E_NAME, E_ABS, K_NAME, K_ANLG, K_DIG, K_TC, K_FUNC, K_STEP, K_CONV, K_CARD, K_CHAN, K_SIG
s = Sequence.load(path)
s.edges        # list of dicts: name, absolute time (ms), parent, relative time, variable indices, time type
s.grid         # channels: s.grid[row][set] -> dict with name, card, channel #, signal type, conversion VI,
               #   and five per-edge lists: analog value, digital value, time constant, function, step size
s.variables    # named times (ms) that variable-timed edges use
s.ramps(row)   # the enabled ramps of one channel in time order
```

Semantics the simulation must apply:

* **Edges are instants; values hold.** A channel's entry at an edge is NaN (analog) or -1 (digital)
  when nothing changes there. The value in force at any time is the one set at the last earlier edge
  that has a value. Edge times come from a parent chain and are already in `E_ABS`; the Edge Array is
  in time order in every Supertime-saved file.
* **Ramps.** If a cell's time constant is nonzero, the channel ramps from that cell's value to the next
  later edge where it has a value, with the cell's function (Linear, Exponential, Optical, Custom ...)
  and step size; Supertime outputs one level per step. Time constant 0 with a function set is inert.
* **Analog vs digital.** Signal type 0 is an analog line (the analog value counts; a digital value
  there is ignored), 1 is a digital line (the digital value counts). A few files carry analog
  numbers on digital lines; Supertime ignores them.
* **Sets.** `s.grid[row][set]`; the 2026 files have one set ("run"). Use set 0.
* **Variables.** An edge with time type 1 takes its relative time from the listed variables; the
  model resolves that for you.

The export `values.json` already applies all of this: for each edge (`stages`, in time order) it
lists each analog channel's value in force, where it was set (`since`), the card volts, and a `ramp`
record when a ramp starts there.

## 3. The conversion VIs

Each analog channel names a conversion VI in the sequence (`K_CONV`); channels with an empty name
send the user value to the card unchanged. All conversion VIs are copies of one template:

* **Method "table"** (the one in use): `Read From Spreadsheet File` reads the calibration file whose
  path is a front-panel default of the VI, builds (x, y) points from columns 0 and 1, and `Threshold
  1D Array` returns the x at which y first reaches the requested value, linearly interpolated between
  table rows. Below the first row it returns the first x; above the last row the last x (so a value
  above the table maximum saturates). The template's other methods, a spline through the same table
  and a hand-entered fit formula, exist in every VI; the Helmholtz VIs use the formula method.
* **Upstream channels.** The template can make one channel's conversion depend on another's value.
  None of the 2026 channels uses this.
* **Two-table variants.** `MOT20250910.vi` (MOT beams), `repump.vi` (Repump) and `MOTAO.vi` (MOT
  frequency) carry a second table for low values, switched by a front-panel "High/low threshold (mW)"
  whose value I could not decode. Their low-table path points at `E:\...\MOT 55MHz 12-15-09.txt`, a
  drive that no longer exists on the PC, so either the threshold is below every value the sequences
  use or the low table is never found. Treat the high table as the one in force and confirm with a
  power meter if a low MOT value (the 2 mW PGC) matters to you.

Channel registry (2026 files; table maximum and date as of 2026-10-29):

| Channel | Conversion VI | Table (x = card V, y = user units) | y max | Units of the sequence value |
|---|---|---|---|---|
| Molasses beams | molasses.vi | OM-2014-9-3.txt (27 Oct 2026 03:03) | 24.0 | mW (AOMrescale "Molasses") |
| MOT beams | MOT20250910.vi | MOT-20250910.txt (high); MOT 55MHz 12-15-09.txt (low) | 44.0 | mW (AOMrescale "MOT") |
| Repump | repump.vi | repump_MOT_path_20171025.txt (5 rows) | 400 | repump table units; see the caveat below |
| MOT frequency | MOTAO.vi | MOT-AO-20111115.txt | -65.6 .. 21.4 | MHz (the lab's detuning scale; -8.7 loading, -20 CMOT, -25 PGC and imaging) |
| Optical Pumping | OP AO 4-4.vi | OP 4-4_20120410.txt | 200 | OP table units (AOMrescale "OP") |
| Lattice X2 | LatticeX2.vi | LatticeX2.txt | 742 | X2 table units (AOMrescale "Lat. X2") |
| Lattice X / Y / Z | none | raw | - | volts to the intensity-lock setpoint (4.2 = full depth, 2.7 = lowered) |
| Lattice X/Y/Z freq, Repump Frequency | none | raw | - | volts to a DDS / VCO |
| Helmholtz X / Y / Z | HelmholtzX/Y/Z.vi | formula inside the VI (no table) | - | mG |
| MOT field | none | raw | - | volts to the quadrupole coil driver |
| Trek X#1, X#2, Y#1, Z#1 | TrekXEO1/2_20250731.vi, TrekY/Z_v2.vi | EOM_XEO1/XEO2_20250731.txt, EOM_Y/Z_2022.txt | 12 | EO volts (11.412 = X1 90 deg, 9.99 = X2 90 deg) |
| Objective Z position | Piezomechanik.vi | piezo-20250829.txt (0, 1, 10 -> 0, 1.2, 12 V) | 10 | objective units (planes 0..8 = 0..9.6 V) |
| Addressing H / V | AddressingH/V.vi | AddressingH/V.txt | 2.7 / 4.7 | addressing units |

Repump caveat: `aomlist.txt` tells AOMrescale to rescale `repump MOT path 20111110.txt` (max 800,
rescaled 10 Sep 2025), but the repump VI's default path is `repump_MOT_path_20171025.txt`, a five-row
table with max 400 that AOMrescale never touches. The sequences use 400 (MOT), 201 (PGC), 150
(imaging), 240 (end of cycle) in that file's units. Which file the VI really reads at run time is its
saved default, i.e. the 2017 one; worth confirming on the PC.

## 4. What AOMrescale does to the meaning of a number

`AOMrescale.py` (Admin\Desktop\AOMrescale) multiplies a table's whole y column by new max / old
max when the lab re-measures the maximum power, so the table's maximum equals the measured maximum
and a sequence value stays in physical units. Consequences for the simulation:

* The **real power behind a sequence value** is value x (true maximum / maximum entered). As long as
  the entered maximum was measured right before the run, the sequence value is the power in mW at
  the measurement point.
* The lab also uses the rescale the other way round: entering a different "maximum" shifts the whole
  calibration, so the same sequence value delivers a different real power. The AOM log shows this
  being done for the molasses on the evening of 27 Oct (entered maximum 20 -> 32 in 2 mW steps, then
  16 -> 28, then back to 24). For such a scan, real power = sequence value x 24 / entered value if 24
  is the true maximum. The log (`aomlog_2024-2026.tsv`, column Molasses) gives the entered value at
  every change, with timestamps, so a run can be matched to it.
* Low-drive nonlinearity is in the table: between 0 and 1.5 V the molasses table is flat at about
  0.12 mW (the meter floor or leakage), so the sequence cannot ask for less than that except 0.

Molasses maximum entered recently (from the log): 23 on 30 Sep, 22 / 21 / 25 / 24 on 22 Oct, 22 on
23 Oct, 20 / 18 on 26 Oct, the scans on 27 Oct, and 24.0 from 03:03 on 27 Oct, which is the state of
the table copied here.

## 5. Worked example: molasses during the PGC vapor-loading hold

Sequence `PGC_vapor_loading_9 planes.dt4` (29 Oct 2026), set "run", times from the cycle start.
Card volts from the tables above with the Threshold method; the molasses table is piecewise linear
between 1.8 V (0.44 mW) and 1.9 V (0.67 mW), so 0.6 mW lands at 1.870 V.

| Stage (edge) | t (ms) | Molasses beams | MOT beams | Repump | MOT freq | Helmholtz X/Y/Z | Lattice X/Y/Z | Objective |
|---|---|---|---|---|---|---|---|---|
| MOT on | 275.1 | 0 | 40 mW (3.695 V) | 400 (4.50 V) | -8.7 MHz | -200 / 0 / 200 mG | 4.2 V | 0 |
| MOT light low end (CMOT) | 1777.1 | 0 | 14 mW (2.957 V) | 400 | -20 MHz | -130 / 130 / 50 | 4.2 (off 1807-1832) | 0 |
| MOT field off | 1837.2 | 0 | 0 | 0 (since 1836.1) | -25 MHz | 0 / 0 / 0 | 4.2 | 0 |
| PGC light on (2 ms) | 1857.2 | 0 | 2 mW (2.500 V) | 201 (2.70 V) | -25 MHz | 0 | 4.2 | 0 |
| Pic before A .. I (9 x 100 ms) | 1929.2 | 5 mW (2.402 V, 0.21 of max) | 0 | 150 (2.486 V) | -25 MHz | 0 | 4.2 | 0 .. 8 |
| **Hold: Pic before I done** | **2989.2** | **0.6 mW (1.870 V, 0.025 of max)** | 0 | 150 | -25 MHz | 0 | 4.2 | 5 |
| Junk image 3 start (hold ends) | 3989.2 | 0 | 0 | 150 | -25 MHz | 0 | 4.2 | 2 |
| Pic after A .. I | 4059.2 | 5 mW | 0 | 150 | -25 MHz | 0 | 4.2 | 0 .. 8 |
| Bkg picture done | 5139.2 | 0 | 0 | 240 | -8.7 MHz | 0 | 4.2 | 2 |

So during the hold the atoms sit in the full-depth lattice (4.2 V setpoint on all three axes) at zero
bias field with 0.6 mW of molasses light (one eighth of the 5 mW used for imaging, 2.5 % of the AOM
maximum) and the repump at 150 of 400 table units, for 1000 ms. The MOT-frequency channel is at
-25 MHz throughout the pictures and the hold.

## 6. What the files do not contain (ask the lab)

* **Where "mW" is measured** for each beam (after the fibre, before the splitter, at the chamber),
  the number of beams the power is shared by, their waists at the atoms and polarisation
  configuration. Without these the sequence gives relative power only.
* **The molasses beams' detuning.** The sequence has a "MOT frequency" channel (-25 MHz during
  PGC, imaging and the hold) but no molasses-frequency channel; an old `molassesFreq.vi` and table
  exist but no 2026 channel uses them. Whether the molasses beams follow the MOT frequency channel
  depends on the optics; the lab knows.
* **Repump detuning** (the "Repump Frequency" channel is a raw VCO voltage, 1.8 then 2.17 V).
* **Lattice depth** per volt of setpoint (4.2 V full, 2.7 V lowered in the cooling files) and the
  lattice wavelength / geometry; the 2006 "lattice calibration" tables in the VI folder belong to
  conversion VIs no longer used.
* **Helmholtz calibration** in mG per volt is inside the Helmholtz VIs' formula nodes (not decoded);
  the absolute zero is set each cycle by the field-correction step, not by the numbers.
* The **true current AOM maxima**: the log gives what was typed in, not an independent measurement.
