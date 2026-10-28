# Briefing: the cooling spin-echo sequence and Supertime's custom EO ramps

For an agent that has the lab flash drive ("MAARTEN USB") and must cut and format EO ramp shapes for the
custom-ramp slots of the cooling spin-echo sequence. Everything below was read out of the files on the drive
and the reconstructed LabVIEW diagrams; the one thing marked UNVERIFIED should be confirmed with a single
test ramp before relying on it.

## 1. What is on the drive and where

Paths are relative to the drive root. The control PC's disk copy is under `Supertime Computer\`
(Windows XP layout), so a path the PC knows as `C:\Documents and Settings\...` is
`Supertime Computer\Documents and Settings\...` on the drive.

| What | Where |
|---|---|
| Sequences in use (`.dt4`) | `Supertime Computer\Documents and Settings\Admin\My Documents\2026\` and its subfolders |
| First-try collision sequences and the ramp CSVs they used | `...\My Documents\2026\Ramps\` : `Cooling(30+10)_3ms_X2detect_2EOx_checkcooling_9planes_test_quarterDepthAllSequence_rampFinetune.dt4` (8 Oct, the last of that series), `EO Ramp Tests.dt4`, `drive_*_i15_upramp.csv` / `drive_*_i15_downramp.csv`, `ramp path.csv` |
| Older ramp CSVs ("fixed", "scaled" variants) | `...\Admin\Desktop\Ramps\` |
| The custom-ramp build of Supertime and its sub-VIs | `...\Admin\Desktop\V2 Xiao\` : `supertime-CustomRamp-ExternalTrigger-pauseChannelUpdateV0 (0929).vi`, `(1008).vi`, `(1009).vi`, `(copy).vi` (all dated 9 Oct; (1009) 14:55 is the newest by time stamp, (copy) 14:33 next, (0929) 14:09, (1008) 09:43), `Load Custom Ramp.vi`, `Define Custom Ramp*.vi`, `Evaluate Custom Ramp.vi`, `Ramp (v4).vi`, `Sync Ramp Paths.vi`, `read array.vi`, `write path array.vi`, `ramp path.csv` |
| The regular (non-custom) Supertime | `Supertime Computer\Documents and Settings\Experiment control\Desktop\Supertime\supertime-ExternalTrigger-pauseChannelUpdateV0.vi` (2 Sep) |
| A Python reader/writer for `.dt4` files (Python 3 or 2.7, standard library only) | `Supertime Computer updates\sequence editor updates\20261027\supertime-analysis\supertime_editor\` : `lvcore.py` (decode/encode), `model.py` (Sequence class: edges, variables, channels, ramps, plots, checks), `app.py` (Tkinter editor). `README.md` next to it explains the editor. |
| Edited sequences from 27-28 Oct (simplified names, new X2 detection) | `Supertime Computer updates\sequence updates\20261027\` |

Read a sequence from Python with the editor's model (run from the `supertime-analysis` folder):

```python
from supertime_editor.model import Sequence, E_ABS, E_NAME, E_PARENT, E_REL, E_TYPE, E_VARS, K_NAME, K_ANLG, K_TC, K_FUNC, K_STEP
s = Sequence.load(path)           # s.edges (list of dicts), s.variables, s.grid (channels), s.ramps(ch)
```
`s.ramps(ch)` returns the enabled ramps of channel index `ch` in time order with `.t0 .t1 .v0 .v1 .func .step`.
If you write a `.dt4`, use `Sequence.save()`: it keeps the two orderings Supertime depends on (Edge Array
sorted by time, Variable Array sorted by name). A file without them loads but Supertime hangs in
"calculating".

## 2. How a `.dt4` sequence is organised

A sequence is a cluster with a Channel Array, an Edge Array and a Variable Array (format details in
`supertime_tools/FORMAT_NOTES.md` in the same folder).

* **Edges** are the time points. Each has a name, a parent edge ("Defined with Respect to", an index),
  and either a fixed relative time (Time Type 0) or a time taken from a variable (Time Type 1). Absolute
  time = parent's absolute time + relative time, rounded to the 1 us clock.
* **Channels** are the hardware lines (56 in the cooling file). Each channel holds one entry per edge:
  analog value (NaN = no change at this edge), digital value (-1 = no change), time constant, function
  type, step size (ms).
* **Ramps.** A ramp starts at an edge where the channel's time constant is nonzero. It runs from that
  edge's value to the next edge (in time) where the channel has a value, using that start cell's
  function type and step size; Supertime outputs one discrete level per step interval. A cell with a
  function set but time constant 0 is inert (the value just steps). Function types: '', Exponential,
  Optical, Optical with offset, Linear, Depth lin freq const, Gaussian, Blackman, Cubic, Custom.
* Supertime expands every ramp step into an edge internally, so the number of ramp steps is what costs
  memory and compile time; 10 us steps are the norm for EO ramps (a 2 us test in July changed nothing).

Channel grid rows that matter here (0-based index in the Channel Array, the same index the custom-ramp
code uses):

| Row | Channel | Card / channel |
|---|---|---|
| 47 | Trek HV Amplifier X#1 (EO x1) | card 7, ch 3 |
| 48 | Trek HV Amplifier X#2 (EO x2) | card 6, ch 3 |
| 49, 51, 53 | the "- Fine Tune" channels (EO zero offsets, set once at "turn off field") | card 7 |

EO voltages: 11.412 V is x1's nominal 180 degree point, 9.99 V x2's (from the day-log headers). The
sequences use 10.97 V (x1) and 10.27 V (x2) as the rotated values and 0.012 V as the resting value.

## 3. The spin-echo section of the cooling sequence

Current file: `Cooling(30+10)_3ms_X2detect_2EOx_checkcooling_9planes_changed imaging.dt4` (28 Oct) in the
`sequence updates\20261027` folder; the first-try collision version is the `..._rampFinetune.dt4` in
`2026\Ramps\`. The structure is identical; only the leg lengths, hold and the rotated voltage differ.
Times below are relative to "Start Spin Echo Begin" in the current file; variables in brackets.

```
 0.000  Start Spin Echo Begin      DDS trigger high (microwave pi/2)         [hold before spin echo start = 40 after Intensity lock enable]
 0.080  Start Spin Echo Mid        DDS trigger low                            [Spin Echo Pulse time = 0.08]
 0.120  Start Spin Echo End
 0.130  Transfer Pulse Begin  ... Transfer Pulse mid ... Transfer pulse end   [edge gap 0.01, Transfer pulse time 0.08, Transfer time p2 0.04]
 0.260  EO ramp up 0     Trek X#1 = 0.012 Custom step 0.01 tc 1  <- RAMP 128 starts here (x1 and x2)
 1.260  EO ramp up 1                                             [EO upRamp1 Time Leg 2 = 1.0]
 1.270  EO ramp up 2                                             [EO upRamp2 Time Leg 2 = 0.01]
 1.280  EO ramp up 3     Trek X#1 = v_rot (value, tc 0)          [EO upRamp3 Time Leg 2 = 0.01]  <- ramp 128 ends here
 1.290  EO ramp down 3   Trek X#1 = v_rot Custom step 0.01 tc 1   [EO Hold Time Leg 2 = 0.01]     <- RAMP 129 starts (the hold is up 3 -> down 3)
 1.300  EO ramp down 2                                           [EO dnRamp3 Time Leg 2 = 0.01]
 1.310  EO ramp down 1                                           [EO dnRamp2 Time Leg 2 = 0.01]
 2.310  EO ramp down 0   Trek X#1 = 0.012 (value, tc 0)          [EO dnRamp1 Time Leg 2 = 1.0]   <- ramp 129 ends here
 2.320  Transfer pulse begin / mid / end
16.667  Echo Pulse Begin / Mid / End   (pi pulse)                 [Spin Echo Leg Time = 16.667, parent = Start Spin Echo Begin/Mid/End]
16.797  Transfer pulse begin / mid / end
16.927  1: EO ramp up 0 ... 1: EO ramp up 3                      <- RAMP 130 (second leg up), same variables
17.957  1: EO ramp down 3 ... 1: EO ramp down 0                  <- RAMP 131 (second leg down)
33.334  Echo Ending Pulse Begin / Mid / End (second pi/2)        [Spin Echo Leg Time again, parent = Echo Pulse *]
33.434  Pause Intensity Lock, Return to full depth (+1.5 ms), Return to full depth end
```

Notes:
* In the current file the custom ramps are "parked": v_rot = 0.012 on both channels, so the shape is
  evaluated between equal end points and produces no motion. In the rampFinetune file v_rot = 10.97 (x1)
  / 10.27 (x2), legs 4.48 ms (EO upRamp1 / dnRamp1 Time Leg 2 = 4.48), hold 0.5 ms, "hold before spin
  echo start" 100 ms. The 24 Sep log also records legs of 5.652 ms up / 5.308 ms down with a 0.5 ms hold.
* The second leg is the same block with the edge names prefixed "1: " and the same variables, so both
  legs always have the same leg times; only the shapes (ramp numbers 130, 131) can differ.
* The Trek X#1 and X#2 cells on these edges are the ONLY places the EO voltage is set during the echo;
  the lattices sit at 2.7 (lowered) with the intensity lock on from "Intensity lock enable" to "Pause
  Intensity Lock". The three polarization-rotation blocks after the echo ("Rotate / Return Lattice
  Polarization") write the Treks back to 0.012 with linear ramps, so a drifting end value must be
  returned to 0.012 by the last custom ramp, not left high.
* "edge gap" (0.01 ms) separates every pulse end from the next ramp start.

## 4. How the custom-ramp build consumes a shape

From the V2 Xiao sub-VIs (Evaluate Custom Ramp, Ramp (v4), Put ramp and new edges in arrays (v4), read
array, Sync Ramp Paths):

* **Addressing.** `ramp path.csv` is a 100 x 1000 table of Windows paths: row = channel grid row, column
  = ramp number. The ramp number is the 0-based position of the ramp among that channel's ENABLED ramps
  in time order (counted the same way `Sequence.ramps(ch)` lists them). In the cooling files Trek X#1 and
  X#2 each have 128 enabled ramps before the spin echo (the 40 cooling cycles x 3 rotations, the six
  clearing rotations, the two polarization rotations before the spectroscopy pulse), so the echo ramps
  are 128 (leg 1 up), 129 (leg 1 down), 130 (leg 2 up), 131 (leg 2 down). In `EO Ramp Tests.dt4` the
  same two ramps are numbers 0 and 1. Current table entries: row 47 cols 128-131 ->
  `...\2026\Ramps\drive_P92PX1H_i15_upramp.csv` / `_downramp.csv` / up / down; row 48 ->
  `drive_P92PX2A_i15_upramp.csv` / `_downramp.csv` / up / down; cols 0 and 1 of both rows still point at
  the Sep "fixed" files used with EO Ramp Tests.
  Consequence: anything that adds or removes an enabled Trek ramp before the echo (a cooling cycle, a
  clearing rotation, a ramp on the hold edge) shifts the numbers. Inside Supertime "Sync Ramp Paths"
  tries to follow such shifts by mask/name while the program runs; the CSV is what persists.
* **File format.** Two columns, comma separated, no header: `index_or_time, value`. The first column is
  not used (existing files have 1..N in one set and 0,2,4,...us in another). Row count is free (2500 and
  2837 both exist). Values are volts in the existing files but see the next point.
* **Mapping onto the ramp (UNVERIFIED in one detail).** `Evaluate Custom Ramp` takes the whole value
  column, maps the first row to the ramp's start time and the last row to its end time (start = the edge
  with the Custom cell, end = the next edge where the channel has a value), interpolates linearly between
  rows at every step-size interval, and rescales the shape so that the first row lands on the start
  cell's voltage and the last row on the end cell's voltage (Delta Y = v_end - v_start). So the file
  supplies the shape; the cell values supply the end points. The interactive loader
  (`Define Custom Ramp (Outside)`) additionally has T0/T1 (0-100 %) window controls and a preview step
  size, but the sequence path (`Ramp (v4)`) passes T0 = 0 and T1 = T, i.e. the whole file. What is
  unverified is whether the rescale is exactly (f - f_first) * Delta Y / (f_last - f_first); the diagram
  reads that way but the constants are not decodable. Test it once: a CSV whose values run 0..1 with a
  kink, and check the generated ramp with the editor's Plot (which draws Custom as linear, so compare
  against Supertime's "Channel Plot" or a scope on the Trek monitor).
* **Sampling.** Number of output points = ramp length / step size, rounded (I16), so keep
  length / step an integer; 10 us steps for 1-5 ms legs give 100-500 points. The CSV can have more rows
  than that; it is interpolated, not decimated.
* **End points are forced by the cells.** A shape cannot move the voltage at a ramp's end away from the
  end cell's value. To end a segment at a drifted voltage, put that voltage in the end cell.

## 5. What the drift correction implies for the shapes

The polarization drift means the EO voltage has to follow a slowly changing correction over the whole
echo, including the nominal hold between "EO ramp up 3" and "EO ramp down 3" and the resting intervals.
With the mechanics above there are two ways to cover the hold:

1. **One shape per leg.** Remove the value at "EO ramp up 3" (set its Trek cells to no change) so ramp 128
   runs from "EO ramp up 0" to "EO ramp down 0" (up + hold + down in one shape, 2.31 ms at the current
   leg times). Then the leg has one ramp, the ramp numbers become 128 (leg 1) and 129 (leg 2), and the
   path table needs two entries per channel, not four. The "EO Hold Time Leg 2" and the up/down leg
   variables still set where in time the shape's features land, since the file is stretched over the
   whole duration; design the CSV with the hold at the right fraction of its length.
2. **Three shapes per leg.** Keep up (128) and down, and give the hold its own Custom ramp: time
   constant 1 on the Trek cells at "EO ramp up 3", with the end value at "EO ramp down 3" set to the
   drifted voltage. This inserts a ramp, so the numbers become 128 up, 129 hold, 130 down, 131/132/133
   for leg 2, and the table must be re-pointed.

Either way the resting level after "EO ramp down 0" and before the next leg is a plain held value
(0.012), and the polarization blocks after the echo return it to 0.012 with linear ramps; if the
correction has to continue through the rest, those intervals need Custom cells too and the count goes up
again.

Keep both Trek channels (rows 47 and 48) in step: in every existing file x1 and x2 ramp on the same edges
with the same step size, and the ILC training ("serial ramps, x1 first then x2") from 24 Sep is in the
day log of `Camera Control\20260924\log.txt` runs 022-026.

## 6. Checks before handing a sequence back

* Do not create two edges at the same instant or closer than 2 us, and keep every ramp's step a whole
  number of microseconds; simultaneous ramps on different channels must have step sizes with a common
  multiple >= 2 us (5 us against 2 us breaks Supertime). `python -m supertime_editor.audit file.dt4`
  and the editor's "Check ramps" report all of this.
* Edge names and variable names must stay unique; the Edge Array must stay sorted by time and the
  Variable Array by name (the editor's save does both).
* After changing which Trek cells carry a time constant, recount the enabled ramps on rows 47 and 48 and
  fix `ramp path.csv` to match; the editor's Ramp list tab shows every enabled ramp in time order.
