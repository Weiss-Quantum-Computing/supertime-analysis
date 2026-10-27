This folder contains Maarten's updated sequences. A few things to note here

1. 	This folder was created on 04/14/2025
2. 	This folder was created to differentiate sequences that use the split EOM technique, wherein we
	separate and drive separately the 2 EOMs for the X lattice. That is to say, the x lattice now uses 
	3 channels, a coarse channel for EO X#1, a course channel for EO X#2, and a fine tune for EO X #2.
3. 	We did this so that we can attempt to have better extinction ratio in the X lattice polarization.
	We have seen that the ER VS voltage for a single EOM has a U shape, where the best extinction ratios 
	are at the 0 degree and 90 degree rotation points for a linear input polarization. With two EOMs, 
	things are more complicated, but our hope is that we can improve the ER where the lattice is 
	at its most shallow, which is where the polarization has been rotated 90 degrees by the combination
	of the two EOMS.
4.	By rotating the EOMs sequentially, rather than in parallel, we hope that we can take advantage of 
	this "U" shape.

5.	We have added a channel (Card 7 Ch 3 at this point) for the second trek, and renamed the channels 
	to match the new reality for the EOMs
6.	The fine tune channel, at this stage, is associated only with the first EOM in the beam path, 
	which is inconveniently labeled as X EO#2, which we might update later, I'll let you know.
7.	We also made a test program for the extinction ratio measurements, modified from the microwave/clearing 
	sequence.


20250731
adding conversion vi for EO voltages for X, Y, Z to uwave sequence to test conversion vi
modifying conversion vi for EO voltages in cooling sequence

Old conversion vi's and interpolation txt file
C:\Documents and Settings\Experiment control\Desktop\Supertime\supertime sub vi's\EOM_X_2022.txt
C:\Documents and Settings\Experiment control\Desktop\Supertime\supertime sub vi's\TrekX_v2.vi

New conversion vi's and txt files
C:\Documents and Settings\Experiment control\Desktop\Supertime\supertime sub vi's\EOM_XEO1_20250731.txt
C:\Documents and Settings\Experiment control\Desktop\Supertime\supertime sub vi's\TrekXEO1_20250731.vi
C:\Documents and Settings\Experiment control\Desktop\Supertime\supertime sub vi's\EOM_XEO2_20250731.txt
C:\Documents and Settings\Experiment control\Desktop\Supertime\supertime sub vi's\TrekXEO2_20250731.vi

Also added conversion vi's for y and z to uw sequence
When using a conversion vi, the inputs are (obviously) converted to an output by a lookup table
At the all off stage, where you want the output to be zero, it may be possible that a zero input
does not lead to a zero output, so in some cases you have to put in a nonzero input to get a zero output

For trek x#1, input -.371 (added this to the lookup table, change if changing eo zeros)
for trek x#2, input 0.012
for trek y#1, input 0.196 (added this to the lookup table, change if changing eo zeros)
for trex z#1, input 0.056

20250806
modified cooling two photon sequence to remove two photon spin echo and hotter atom clearing
for checking base cooling and x2 imaging
named checkcooling
need to move pins for eos since eos are in opposite directions

20250807
fixed bug in sequence,
in supertime, if two channels are ramped simultaneously, their step sizes should have a common multiple greater than
or equal to the minimum timestep, which in our case is 2us (1MHz supertime clock)
If this isn't the case, when supertime attempts to interpolate them it will create timing edges designed to be output 
every 1us, but it will actually push them every 2us, breaking the sequence.
We noticed this first when we added the second trek control. The ramp down for trekx#2 (the original control channel),
had a 2us stepsize at the ramp down after the x2 detect. This is allowed, but it was inconsistent with every other 
step size for the eo ramps (5us). When I (maarten) added the channel for trek x#1, I hand copied each ramp up and ramp down,
but used 5us steps for all eo ramps, including the ramp down after x2 detection, creating the problem.
With 5us steps and 2us steps happening simultaneously, we effectively attempted 1us steps.

20250811
reverted negative sign added to trek x#2 lookup table (after swapping the pins on x#1)
modified cooling sequence to close repump shutter after cooling.
also fixed one place where repump shutter turns off for 100us for no reason after initial op before cooling
added change of EO vi's to 2 photon sequence
in op sequence,
changed lattice y initial on to full power (same as x and z, likely a mistake that does nothing different)
stopped mot shutter closing for 100us for no reason
removed test trigger 2 (I added it some time ago to have an edge to trigger off, we don't need it now)
added trek conversion vi's to xyz
rename y fine tune to y#1 fine tune and z fine tune to z#1 fine tune
added trek amplifier channels for y and z to pgc sequence
added trek conversion vi's to pgc sequence
added lc triggers ti PGC sequence to help imaging
added field monitor trigger to be consistent with other sequences
added test trigger to be consistent with other sequences


20250911
changed mot beam conversion vi to accurately reflect real powers, renamed as mot20250910
peak mot power 40mw, low light at 15mw. precool at 2-3mw (undecided, will explore later
fixed loading issue with hopping sequence, pre cool stage was far longer than it shoul have been (50ms vs 2ms)
we will explore using this precool to decreas the background atoms later, it might be that imaging is better with less background.





