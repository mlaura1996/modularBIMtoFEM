#!/usr/bin/env python3
"""Despikes the base shear signal for the hysteretic-loop figure.

WHY THIS EXISTS. The completed time-history's base_reaction data carries
numerical spikes - individual time steps where the summed base reaction
jumps by 2-4 orders of magnitude (a genuine measurement: one recorded step
reached 1.4e9 N, 157x the structure's own weight, immediately preceded and
followed by values around 1e5-1e6 N) before returning to a physically
plausible level a step or two later. The roof displacement (Rd) over the
SAME steps stays perfectly smooth - no discontinuity - which is why this is
treated as a reaction-force artifact rather than a real event: a real
sudden impact would leave a mark on the displacement too, and it does not.

This is not a fluke of this one run. It matches a limitation already
documented in this repository before this run existed
(docs/source/developer_guide/known_issues.md, "Still open" section):
ASDConcrete3D combined with Task A contact interfaces was already known not
to converge cleanly - a smaller test case saw NormDispIncr fail outright
with an oscillating norm. This run used EnergyIncr instead (Chapter 6's own
convergence criterion), which can stay satisfied while the LOCAL force
distribution still oscillates - small energy increments do not require a
smooth force field, only that force x displacement stays small - so
"0 non-converged steps" in the run's own log does not mean the reaction
signal is clean. Mechanically: once an element's damage approaches 1.0 its
tangent stiffness collapses toward zero, and a near-zero-stiffness element
pinned to a stiff neighbour through a tie or contact constraint is exactly
the situation where IMPLEX's extrapolate-then-correct scheme can produce a
large one-step force overshoot before self-correcting.

WHAT WAS CHECKED BEFORE TRUSTING THIS. A single global threshold does not
separate the good steps from the bad ones - the raw peak is 157x the
structure's weight, and even keeping only the best 95% of steps by
magnitude still leaves a "peak" at 3.6x the weight, because the
contamination is not a handful of isolated points but a fraction of steps
across most of the record with escalating (not binary) severity. A
Hampel filter - a local median and a robust scale estimate (MAD, median
absolute deviation) evaluated in a window around each point, applied
iteratively - is used instead. It was verified before use in three ways:

  1. it correctly catches the KNOWN spike (t=14.480s, 1.4e9 N) and its
     immediate near-neighbours (also elevated, 1.06e8 and 2.62e8 N),
     replacing them with the ~1-4e6 N level the smoothly-varying
     surrounding signal actually supports;
  2. near the record's real strong-motion peak (t=12.0-12.6s, around the
     12.345s PGA) it flags 14.0% of steps - close to the 12.1% global
     rate, not dramatically higher, i.e. it is not disproportionately
     eating the real seismic peak it exists to preserve;
  3. the resulting peak base shear coefficient (BS/W) drops from 157.7 to
     1.78 - the SAME order of magnitude as Chapter 6's own experimental
     reference (~1.2), where the raw figure was two orders of magnitude
     off. Not an exact match (a different aggregate, different material
     calibration, different damage state), which is expected and not
     itself a sign anything is wrong.

A SECOND PASS, after despiking: the Hampel-cleaned curve still LOOKS
visibly jagged when plotted against displacement - a real hysteretic loop
traced by a mass-spring-damper system is smooth, and this was not, even
though its peak was already down to a plausible scale. That is because a
Hampel filter only removes points that are extreme RELATIVE TO THEIR OWN
NEIGHBOURHOOD - it leaves smaller, still-spurious noise (a few percent to
a few tens of percent of the local signal) untouched, and that residual
noise is exactly what was making the loop look ragged rather than smooth.
The spikes and this residual noise share the same origin (the near-zero
local stiffness/IMPLEX interaction described above) and the same
signature: they appear and vanish within one or two steps, i.e. they are
HIGH FREQUENCY, while the structure's own dynamic response lives near its
fundamental period (T1 = 0.173 s, 5.786 Hz) and stays there even during
strong shaking - a structure does not respond faster than its own natural
frequencies allow. So a zero-phase (filtfilt, no time-shift) 4th-order
Butterworth low-pass at 15 Hz - comfortably above every mode this
structure's mass actually participates in, comfortably below the 200 Hz
sample rate - removes the residual noise by what it IS (frequency content
no real structural response has) rather than by how large it happens to
be at any one instant. Checked across cutoffs 10/15/20/25 Hz before
picking 15: the resulting peak moves only from 0.619 to 0.646 W - stable,
not sensitive to the exact choice, which is what a real feature of the
signal looks like rather than a filtering artifact tuned to produce a
particular number.

WHAT THIS DOES NOT DO. It does not touch principal_strains.csv or
damage_map.csv - those are per-element PEAK values (one number per
element over the whole run), not a time series, so a Hampel filter's
"replace an isolated point with its temporal neighbourhood" logic does
not apply to them the same way. Whether individual elements' peak strain
figures need a separate treatment is a different question, deliberately
left open here.

    python scripts/clean_hysteretic_response.py [results_dir]

results_dir defaults to output/castelnuovo/results_timehistory - the
small, git-tracked postprocessing output, not the raw recorders. Writes
response_clean.csv (all of response.csv's columns, plus BS_clean_N,
BS_clean_over_W - despiked AND low-pass filtered - spike_flag, and
cumulative_dissipated_energy_clean_J) into the same directory.

The last of those matters beyond the hysteretic loop: energy.csv
(postprocess_timehistory.py's own output) integrates the RAW base shear
and is dominated by the same contamination - checked directly, 92% of its
final total comes from the 12% of intervals touching a flagged spike.
energy.csv is left as-is (an honest record of what the raw recording
contains) rather than overwritten; cumulative_dissipated_energy_clean_J
here is the one to plot or quote instead.
"""
import csv
import json
import os
import sys

import numpy as np
from scipy.signal import butter, filtfilt

# 4th-order zero-phase Butterworth low-pass. See the module docstring's
# "second pass" section for why 15 Hz and why it is not sensitive to the
# exact choice.
LOWPASS_CUTOFF_HZ = 15.0
LOWPASS_ORDER = 4

RESULTS_DIR = (sys.argv[1] if len(sys.argv) > 1
               else "output/castelnuovo/results_timehistory")

# Window in SAMPLES (15 samples x 0.005 s = 0.075 s - well under the
# structure's own fundamental period, T1 = 0.173 s, so a real half-cycle
# of the dominant response is never mistaken for a run of spikes).
# n_sigma=4 on a robust (MAD-based) scale estimate is the conventional
# "clearly an outlier, not just a large sample" threshold for a Hampel
# filter. Both were tuned against the actual data (see module docstring's
# three checks) rather than picked a priori.
WINDOW = 15
N_SIGMA = 4.0
MAX_ITERATIONS = 5


def hampel_filter(x, window=WINDOW, n_sigma=N_SIGMA, iterations=MAX_ITERATIONS):
    """Returns a boolean array flagging x's outliers.

    Iterative: a first pass can leave a flagged point's neighbours still
    biased by it if two spikes land close together, so each pass recomputes
    the local median/MAD on the PROGRESSIVELY cleaned series (flagged
    points replaced by their local median before the next pass) and only
    adds newly-detected outliers - a point already flagged is never
    un-flagged, so this converges (bounded above by len(x), and stops as
    soon as a pass finds nothing new).
    """
    x = np.asarray(x, dtype=float).copy()
    flagged = np.zeros(len(x), dtype=bool)
    n = len(x)
    typical_scale = np.median(np.abs(x[x != 0])) if np.any(x != 0) else 1.0
    for _ in range(iterations):
        med = np.empty(n)
        mad = np.empty(n)
        for i in range(n):
            lo, hi = max(0, i - window), min(n, i + window + 1)
            med[i] = np.median(x[lo:hi])
            mad[i] = np.median(np.abs(x[lo:hi] - med[i]))
        sigma = np.maximum(1.4826 * mad, 1e-6 * typical_scale)
        newly = (np.abs(x - med) > n_sigma * sigma) & ~flagged
        if not newly.any():
            break
        flagged |= newly
        x[newly] = med[newly]
    return flagged


def despike(t, x):
    """Flags x's outliers and returns (cleaned, flagged) - cleaned replaces
    flagged points with a linear interpolation over the surviving ones, so
    the result is a continuous series suitable for a time-history or
    hysteretic-loop plot rather than a series with holes in it."""
    flagged = hampel_filter(x)
    cleaned = x.copy()
    if flagged.any():
        good = ~flagged
        cleaned[flagged] = np.interp(t[flagged], t[good], x[good])
    return cleaned, flagged


def main():
    in_path = os.path.join(RESULTS_DIR, "response.csv")
    if not os.path.isfile(in_path):
        sys.exit(f"Missing {in_path} - run scripts/postprocess_timehistory.py first.")
    with open(in_path) as fh:
        rows = list(csv.DictReader(fh))
    t = np.array([float(r["time_s"]) for r in rows])
    bs = np.array([float(r["BS_N"]) for r in rows])
    rd = np.array([float(r["Rd_m"]) for r in rows])

    summary_path = os.path.join(RESULTS_DIR, "summary_postprocess.json")
    weight = None
    run_summary_path = os.path.join(
        os.path.dirname(RESULTS_DIR.rstrip("/\\")),
        "recorders_" + os.path.basename(RESULTS_DIR).replace("results_", "", 1),
        "summary.json")
    if os.path.isfile(run_summary_path):
        with open(run_summary_path) as fh:
            weight = json.load(fh).get("self_weight_N")
    if weight is None:
        # Known value for this model (self-weight check, 0.026% match
        # across every run in this chapter) - used only if the analysis's
        # own summary.json is not reachable from here.
        weight = 8_862_669.0
        print(f"NOTE: self_weight_N not found via {run_summary_path}; "
              f"using the known Castelnuovo value {weight:,.0f} N.")

    print(f"Despiking BS_N ({len(bs)} steps, window={WINDOW} samples "
          f"= {WINDOW * (t[1] - t[0]):.3f} s, threshold={N_SIGMA} sigma)...")
    bs_hampel, flag = despike(t, bs)
    print(f"  {flag.sum()} of {len(bs)} steps flagged as spikes "
          f"({100 * flag.sum() / len(bs):.1f}%)")
    print(f"  raw peak:            {np.abs(bs).max():.3e} N = "
          f"{np.abs(bs).max() / weight:.2f} W")
    print(f"  after despiking:     {np.abs(bs_hampel).max():.3e} N = "
          f"{np.abs(bs_hampel).max() / weight:.4f} W")

    dt = t[1] - t[0]
    fs = 1.0 / dt
    b, a = butter(LOWPASS_ORDER, LOWPASS_CUTOFF_HZ / (fs / 2), btype="low")
    bs_clean = filtfilt(b, a, bs_hampel)
    print(f"  after {LOWPASS_CUTOFF_HZ:g} Hz low-pass: "
          f"{np.abs(bs_clean).max():.3e} N = "
          f"{np.abs(bs_clean).max() / weight:.4f} W")
    i = np.argmax(np.abs(bs_clean))
    print(f"  final cleaned peak occurs at t = {t[i]:.3f} s")

    # Cumulative dissipated hysteretic energy, recomputed from the CLEANED
    # signal. The original energy.csv (postprocess_timehistory.py) used the
    # raw BS_N and is dominated by the same contamination: checked directly
    # against this run - 92% of its final total comes from the intervals
    # touching a flagged spike (2.6e6 J from the clean 88% of intervals vs
    # 3.10e7 J from the 12% touching a spike, out of a 3.36e7 J total), so
    # it is not a small correction, it is most of the number. That file is
    # NOT overwritten here (it is a direct, honestly-labelled record of what
    # the raw recording contains) - this is the one to use instead.
    d_rd = np.diff(rd)
    bs_mid_raw = 0.5 * (bs[1:] + bs[:-1])
    bs_mid_clean = 0.5 * (bs_clean[1:] + bs_clean[:-1])
    incr_raw = np.abs(bs_mid_raw * d_rd)
    incr_clean = np.abs(bs_mid_clean * d_rd)
    cum_clean = np.concatenate(([0.0], np.cumsum(incr_clean)))
    print(f"  cumulative dissipated energy: raw-signal total = "
          f"{incr_raw.sum():.3e} J (dominated by spikes); "
          f"cleaned total = {cum_clean[-1]:.3e} J")

    out_path = os.path.join(RESULTS_DIR, "response_clean.csv")
    with open(out_path, "w") as fh:
        fh.write("time_s,Rd_m,drift_ratio,BS_N,BS_over_W,"
                 "BS_clean_N,BS_clean_over_W,spike_flag,"
                 "cumulative_dissipated_energy_clean_J\n")
        for i, r in enumerate(rows):
            fh.write(f"{t[i]:.4f},{rd[i]:.8e},{r['drift_ratio']},"
                     f"{bs[i]:.6e},{bs[i] / weight:.6e},"
                     f"{bs_clean[i]:.6e},{bs_clean[i] / weight:.6e},"
                     f"{int(flag[i])},{cum_clean[i]:.6e}\n")
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
