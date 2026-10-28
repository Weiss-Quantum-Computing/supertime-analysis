# Why the 26 Oct "(1009)" custom-ramp build turns every ramp into a step - notes for Xiao

Compared (all from the control PC copy, `Documents and Settings\Admin\Desktop\`):

| Build | File | Saved | Size | Block diagram | Front-panel default data (DFDS) |
|---|---|---|---|---|---|
| in use, works | `supertime-CustomRamp-ExternalTrigger-pauseChannelUpdateV0.vi` | 9 Oct 11:56 | 6.25 MB | 902 KB | **4,223 KB** |
| broken | `supertime-CustomRamp-ExternalTrigger-pauseChannelUpdateV0 (1009).vi` | 26 Oct 16:52 | 2.00 MB | 936 KB | **25 KB** |
| same name, in V2 Xiao | `V2 Xiao\supertime-CustomRamp-...V0 (1009).vi` | 9 Oct 14:55 | 6.37 MB | 1,003 KB | 4,224 KB |

Extracted with pylabview and the diagrams reconstructed (`supertime_tools/lvdiagram6.py`).

## What is the same

* All three link the same ramp machinery: `Generate Array Data (v6).vi` -> `add ramps only (v5).vi` for
  the run, `add ramps only (v7).vi` in the edit frame, `Two-point fit with time const (v6).vi` ->
  `Define Custom Ramp (v4).vi` / `Read From Spreadsheet File.vi`, `Put ramp and new edges in arrays (v4).vi`
  -> `Ramp (v4).vi` -> `Evaluate Custom Ramp.vi`.
* `Generate Array Data (v6)` is wired identically in the 9 Oct and 26 Oct builds: the same 16 wires on the
  same terminals, fed by the same local variables and front-panel terminals (frame 4, the node at
  diagram position (-200,253)). Nothing in the generation path was rewired.

## What differs

1. **The ramp-path table is no longer stored in the VI.** The 9 Oct build (and the 9 Oct V2 Xiao copy)
   carries a 4.2 MB default-data block: that is the `Ramp Path Array` front-panel control with its
   100 x 1000 table of paths saved as default values. The 26 Oct build has 25 KB of default data: the
   table was saved empty. The 4 MB file-size difference is entirely this.
2. **The 26 Oct build fills the table at run time instead.** New in its frame 0: `read array.vi` (reads
   `ramp path.csv`, splits lines on commas, String To Path) inside a Case structure whose selector comes
   from a tunnel of the outer sequence (not the Save button; it is a gate computed elsewhere, probably a
   first-iteration flag), then `Extract Ramp Names.vi` + `Sync Ramp Paths by Name.vi` (the 9 Oct V2 Xiao
   copy used `Extract Ramp Mask.vi` + `Sync Ramp Paths.vi`, index/mask based), and `write path array.vi`
   behind the `Save` button. New front-panel items: `Ramp Names`, `Ramp Path Array 2`, `Save`, and a
   `Ramp Names` array constant that seeds a shift register of the main loop.
3. Nothing else of substance: the remaining differences are 2 local variables, 11 constants, 5 primitives
   and 3 case structures around that load/sync/save logic, and one extra `Get Edge Names.vi` call for
   the name sync.

## Why that makes ALL ramps steps, not just the custom ones

The ramp-path array goes from a local variable into `Generate Array Data (v6)` terminal 0 (`Array`) and
from there straight into `add ramps only (v5)`'s `Array` input, which enters the outer per-channel For
loop of that VI through an input tunnel. The diagram comment on that loop reads "Indexing input sets
value for N but cannot be used in loop because we change other elements": the loop count N is taken
from an auto-indexed input. If the path array is one of the auto-indexed inputs (a 2-D array indexes
row by row), LabVIEW runs the loop min(rows, channels) times. With the table saved empty and not
loaded (gate false, CSV not found at the hard-coded path, or the name sync returning an empty array
because the current names do not match the seeded `Ramp Names`), rows = 0, the loop executes zero
times, no channel gets its ramps inserted, and every ramp - linear, optical, custom - comes out as a
direct step. In the 9 Oct build the table has 100 rows, more than the 56 channels, so N = 56 as before.

This is the one mechanism consistent with "all ramps become steps" rather than "custom ramps misbehave".
I cannot read the tunnel type (auto-indexing or not) or the Case gate value out of the heap, so treat
it as the first thing to check, not as proven.

## How to confirm in LabVIEW (two minutes)

1. Open the 26 Oct build, look at the `Ramp Path Array` control before running: is it empty?
2. Put a probe on the `Array` input of `add ramps only (v5)` inside `Generate Array Data (v6)` and on
   the For loop's N during a run: expect an empty 2-D array and N = 0.
3. Check the path constant feeding `read array.vi` and the selector of its Case: the CSV on the PC is at
   `C:\Documents and Settings\Admin\Desktop\V2 Xiao\ramp path.csv` and a copy at
   `...\Admin\My Documents\2026\Ramps\ramp path.csv` (100 rows x 1000 columns, entries at rows 47/48,
   columns 0, 1, 128-131).

## Fixes, least invasive first

* Load the table (Load / read array) and then "Make Current Values Default" on `Ramp Path Array` and
  save: restores what the 9 Oct build has, keeps the new CSV load/save as a convenience.
* Make `read array.vi` run unconditionally at start-up from a fixed path, and never let the sync
  return an array with fewer rows than channels (pad to 100 rows, or sync in place).
* Decouple the loop count from the path array: feed the channel array as the only auto-indexed input
  and fetch the channel's path row with Index Array inside the loop, so an empty table can only cost
  the custom ramps, not every ramp.
* `Sync Ramp Paths by Name` keys on ramp-start edge names. Edge names changed in the 2026 files on 27 Oct
  (splice prefixes removed), so a name-based sync seeded with old names will not match; the mask/index
  version (`Sync Ramp Paths.vi`, as in the V2 Xiao 9 Oct copy) does not have that problem.
