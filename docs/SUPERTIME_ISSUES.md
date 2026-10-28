# Supertime (LabVIEW 6.1): known issues, slowdowns and memory behaviour

Read from the reconstructed block diagrams in `vi_diagrams/` and the diagram comments in
`supertime_tools/*_text_labels.txt` (2026-10-27). Nothing here has been changed in the LabVIEW
code; this is what to be aware of. Numbers are for the 2026 sequences in `sequences/2026`.

## 1. Why long sequences run out of memory: ramps are expanded by inserting edges

`Frame 4` of the main VI calls `Generate Array Data.vi`, which calls `add ramps only.vi`. That VI
does not compute the ramp samples into a separate output buffer. For every enabled ramp it
**inserts one new edge per ramp step into the Edge Array and into every channel's per-edge
arrays** (`Put ramp and new edges in arrays.vi` -> `put new edge in channels.vi`, diagram comment
"Insert ramp into Edge Value array for this channel and insert appropriate edges in Edge array").
`put new edge in channels.vi` loops over all channels and inserts an element into each of the five
per-edge arrays (analog value, digital value, time constant, function type, step size).

Consequences, with the 9-planes cooling sequence as the example:

| | edges | per-channel ramp steps | unique time points after expansion | channel array after expansion |
|---|---|---|---|---|
| Cooling 9 planes | 1,400 | 28,696 | 21,262 | ~32 MB (56 channels x 27 bytes/point) |
| Cooling 843nm | 1,388 | 32,538 | 25,478 | ~39 MB |
| uwaves 9 planes | 154 | 8,389 | 5,134 | ~7 MB |
| hopping 9 planes | 69 | 120 | 167 | < 1 MB |

* **Quadratic time.** Each insertion reallocates and copies all 280 per-edge arrays (56 channels x
  5 arrays) plus the Edge Array. Tens of thousands of insertions into arrays that grow to ~21,000
  elements means on the order of 10^11 element copies per compile. This is the "calculation
  takes minutes" behaviour, and it grows with the square of the number of ramp steps, not
  linearly.
* **Memory fragmentation.** LabVIEW 6.1 on 32-bit XP needs each array in one contiguous block.
  Growing 281 arrays by one element tens of thousands of times, while the dataflow keeps extra
  copies of the whole 30-40 MB channel array alive (every wire branch, local variable and
  subVI boundary can copy it; `Sort Edge Array.vi` is called inside the DDS branch of the same
  loop), fragments the heap. "Memory is full" is LabVIEW's message when a single contiguous
  allocation fails, which happens well before physical RAM is exhausted. This is why the
  cooling sequences (the only ones with >20,000 expanded points) are the ones that fail.
* **What costs the most.** Per-channel ramp steps, not edges. In the cooling sequence the four
  Trek HV channels contribute ~5,000-7,800 steps each and the Lattice X2 ramp down (2,500 steps of
  2 us over 5 ms) and Lattice X (1,000 steps) the largest single ramps. The editor's Ramp list
  tab gives this per ramp. Doubling a step size halves the cost of that ramp.
* Everything downstream is linear and small: the analog output buffer is only 21,262 points x
  33 channels x 2 bytes = 1.4 MB, the timing-card pattern 85 KB.

## 2. Other things that take time on every run

* **Conversion VIs are loaded from disk and re-read their calibration file on every call.**
  `Convert UD units to Volts.vi` opens each channel's conversion VI by reference
  (`TrekXEO1_20250731.vi`, `HelmholtzX.vi`, `x lattice 2.vi`, ...), runs it, closes it. Each of
  those VIs calls `Read From Spreadsheet File.vi` and `Spline Interpolant.vi` (or
  `Threshold 1D Array`) every time, over the expanded point list. The diagram comment says it:
  "If speed is more important than memory, put all the conversion files you use here. This will
  load and keep them all in memory, saving time." Sixteen channels use conversion VIs.
* **A nonlinear fit per ramp.** `Two-point fit with time const.vi` runs
  `Local copy Nonlinear Lev-Mar Fit.vi` to get the exponential/optical coefficients from the two
  end points and the time constant (557 ramps in the cooling sequence). Closed-form
  expressions exist for every shape.
* **Hardware-repeat duplicates the whole point array** per data set ("Duplicate timing points for
  each set to run (hardware mode)", with the comment "FIXME: this could be done without
  duplication"). Running N sets in hardware mode multiplies the expanded arrays by N.
* **The idle main loop polls.** Every iteration (`Wait Until Next ms Multiple`, constant not
  decoded) it re-reads the controls through ~270 local variables and runs
  `compare channel array 2D except NaNs.vi` over the entire channel array (56 x 1,400 cells x
  several fields) to detect edits. With a large sequence loaded the panel feels sluggish even
  when nothing is running; the "Inf loop?" indicator is its watchdog.
* **The step program gets a flattened copy.** `Send arrays to step program.vi` flattens the
  Edge, Channel and Variable arrays to strings and hands them to `Main external dispatch.vi`
  by VI reference on every run.
* **Logging appends the full sequence every run.** `Log Data.vi` appends `{date, time, whole data
  cluster}` (about 2 MB for a cooling sequence) to the datalog. LabVIEW 6.1 file offsets are
  32-bit, so a log must stay under 2 GB; the past logs were rotated at a few hundred MB to 2 GB.
  Keep rotating `supertime.log` before it gets there.

## 3. Hacks and silenced errors in the output path (from the diagram comments)

* `Write analog data to analog cards.vi`: the check that the per-card buffer fits the 6713's
  16 KB on-board FIFO now has its message disabled ("disable the error msg here, old version is
  saved with 2015 in the end"). Buffers larger than the FIFO are streamed from PC memory; a
  late DMA transfer would show as a glitch rather than an error.
* `Generate Array Data.vi`: "Make sure array length is even ... And don't forget to add an extra
  timing point to trigger it"; "Not necessary for digital cards, I think, but must keep consistent
  with analog array length or they get out of sync". The even-length padding adds a point at the
  end of every column when the count is odd.
* The DDS branch of `add ramps only.vi` adds 12 extra points for a frequency change ("so the end is
  24 x resolution later") and 4 for an amplitude change, only if not already there.
* Main VI comments: "Shared edges: last channel wins"; "Don't change values such that
  ramp-related edges move past each other or chaos results! And don't switch methods without
  starting over with a new data set or you'll get a 'defined with respect to' loop";
  "For update rate--seems to cause problems" (software repeat loop); "If not using the D-A-D
  kludge, there is no need to generate the whole array, so this saves time"; "Now all that we do
  here is convert 0/1 to T/F. This could probably be accomplished by a built-in function much
  faster. FIXME."
* `Adiabatic Changer.vi` and all edge-moving logic were removed in 2008 ("I'm sure we never
  will!").
* Step-size conflicts (simultaneous ramps whose steps have no common multiple >= 2 us) are not
  checked by Supertime; they produced the August 2025 failures. The editor's Check ramps and
  audit catch them.

## 4. What can be done without touching LabVIEW

* Keep per-channel ramp steps down: fewer steps per ramp (larger step sizes on the Trek and
  lattice ramps where the hardware does not resolve 2 us anyway), shorter ramps, no ramps on
  channels that do not need them. The Ramp list tab shows where the steps are.
* Watch the expanded point count rather than the edge count. Roughly: cooling-class sequences
  at 20,000-25,000 expanded points are at the limit on the current machine; 5,000 is comfortable.
  The editor shows this as the "sequence cost" in the status bar and the Ramp list tab
  (`Sequence.cost()` in `model.py`: per-channel ramp steps, expanded points, array size, level).
* Rotate the run log before 2 GB.

## 5. What would fix it in LabVIEW (for when someone opens the VIs)

* `add ramps only.vi`: compute each ramp's samples into preallocated arrays (or build the
  expanded per-channel arrays once with `Initialize Array` + `Replace Array Subset`) instead of
  inserting one edge per step into every channel. This alone turns the compile from quadratic to
  linear and removes the fragmentation.
* Load the conversion VIs once (the hook for it is already in `Convert UD units to Volts.vi`) and
  cache the calibration tables.
* Replace the Levenberg-Marquardt two-point fit by the closed-form coefficients.
* Build the output buffers directly from the expanded arrays instead of transposing the whole
  2-D array several times.
