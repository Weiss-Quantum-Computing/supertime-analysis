# Custom-ramp chunks for Supertime, campaign 2026-10-14

The 31 spin-echo records trained and optically closed on 14-15 Oct 2026, cut into the chunks
Supertime's custom-ramp slots take. One folder per record (`S47E2`, `SF130E2`, ...), with the two
channels' full closed drives (`<stem>_X1_full_keeper.csv`, 2 us grid, AWG volts) and the chunks
`<stem>_<X1|X2>_leg<1|2>_<up|hold|down|after>.csv`. `ramp_table.md` / `.csv` list every chunk's
timing and end voltages. Made by `tools\supertime_chunks.py` in the EOM-ILC checkout.

## Chunk format

Two columns, comma separated, no header: `index, value`, as the September files. Values are the
closed drive in AWG volts on the 2 us grid; Supertime interpolates at its step and rescales the
shape onto the cell voltages, so the scale of the values does not matter, only the shape.

## What each chunk is, and where it goes in the sequence

| chunk | runs from | to | sequence edges (leg 1; leg 2 with the "1: " prefix) |
|---|---|---|---|
| up | 100 us before the target's rise starts (the drive leads the target) | 200 us into the flat top | EO ramp up 0 -> EO ramp up 3 |
| hold | 200 us into the flat top | 200 us before its end | EO ramp up 3 -> EO ramp down 3 (a Custom cell with time constant 1 at up 3) |
| down | 200 us before the flat top's end | 100 us after the fall | EO ramp down 3 -> EO ramp down 0 |
| after | 100 us after the fall | 100 us before the next leg's rise (leg 1) / the record's end (leg 2) | EO ramp down 0 -> 1: EO ramp up 0 (leg 1), a Custom cell at down 0 |

The hold and after chunks carry the optical close's slow corrections (the creep over the hold, the
relaxation after the fall); the brief's option 2 puts them in their own Custom ramps, which inserts
ramps and renumbers: leg 1 = 128 up, 129 hold, 130 down, 131 after, leg 2 = 132-135, and
`ramp path.csv` rows 47 (X1) and 48 (X2) must be re-pointed accordingly. A chunk marked
"held value" in the table changes by under 2 mV end to end: set its cells, no shape is needed, and
the numbering drops by one for each such chunk left out.

Every boundary sits on a 10 us grid, so a 10 us step fits every chunk exactly; the table gives the
duration and the number of points. Set the edge times from the table (EO upRamp1 / Hold / dnRamp1
Time Leg 2 are the up, hold and down durations; the sum of the four chunks is the 16.668 ms leg
spacing). A different duration stretches the shape in time.

## Voltages

The table gives each chunk's start and end value three ways:

* AWG volts, as played on the bench through the 4063B -> preconditioning -> Trek path;
* degrees of rotation at the EOM, from the measured chain gains (557 V per AWG volt on X1, 601 on
  X2, the linear region) and V90 (5128.3 / 5137.4 V);
* Supertime card volts, converted from degrees with the day-log 90-degree points per crystal
  (11.412 V X1, 9.99 V X2, the "180 degree point" of the pair). This column is derived; confirm it
  with one test ramp on the Trek monitor before trusting the absolute level. The resting value in the
  sequence is 0.012 V; the chunks' rest ends sit within a few mV of zero at the AWG.

X2's chain saturates near 5575 V on the hold (the preconditioning stage before the Trek), which is
why the 14 stop-scan, survey and handover records were rebuilt on 15 Oct with X2 ending at its
90-degree point (5137 V); nothing in this folder asks X2 for more than that.

## Before the first run

1. One test ramp: load a chunk, set its cells to the table's voltages, and compare Supertime's
   Channel Plot or the Trek monitor on a scope with the chunk's shape, to confirm the rescale
   (f - f_first) x (v_end - v_start) / (f_last - f_first) and the card-volt conversion.
2. Recount the enabled Trek ramps on rows 47 and 48 after adding the hold and after Custom cells,
   and fix `ramp path.csv`.
3. Both channels ramp on the same edges with the same step, as always.
