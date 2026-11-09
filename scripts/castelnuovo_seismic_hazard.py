"""Seismic hazard at Castelnuovo di Porto under NTC 2018, compared with the
record applied in the nonlinear time-history analysis of Chapter 8, and a
set of artificial spectrum-compatible accelerograms for the site.

Hazard parameters
-----------------
ag, F0 and Tc* come from the reference grid of NTC 2008 Allegato B, which
NTC 2018 (paragraph 3.2) still adopts: resources/hazard/ntc_reticolo_allegatoB.csv,
10,751 nodes, nine return periods, ag in g/10 as in the official table.
At the site they are interpolated as prescribed by Allegato A:
  - in space, the inverse-distance mean of the four grid nodes surrounding
    the site;
  - in return period, log(p) linear in log(TR) between the two tabulated
    return periods bracketing TR.

Return periods: nominal life VN = 50 years, use class II (CU = 1.0), so
VR = 50 years and TR = 30, 50, 475, 975 years for SLO, SLD, SLV, SLC.

Elastic spectrum: NTC 2018 eq. 3.2.2 with 5% damping (eta = 1), for the
subsoil and topographic categories given on the command line (the site was
not characterised; A-T1 gives the reference rock spectrum).

Applied record: resources/records/castelnuovo/montenegro1979_run21_long.txt
(the motion recorded on the SERA-AIMS shake table, PGA 0.593 g), with its
time axis stretched by sqrt(2) as in the analysis, over the 27.58 s
analysed. Its 5% damped pseudo-acceleration spectrum is computed with the
exact piecewise-linear (Nigam-Jennings) recurrence.

Artificial accelerograms (NTC 2018 paragraph 3.2.3.6): stationary Gaussian
noise shaped by a trapezoidal envelope (2 s rise, 15 s strong part, decay
to 30 s), Fourier amplitudes iteratively corrected until the 5% spectrum
matches the target SLV spectrum, then baseline-corrected. The set of seven
is checked against the code rule: the mean spectrum must not fall more than
10% below the target between 0.15 s and 2.0 s (and 2 T1).

    python scripts/castelnuovo_seismic_hazard.py [lat lon] [--soil A] [--topo T1]

Outputs in output/castelnuovo/hazard/:
  hazard_parameters.csv      ag, F0, Tc*, S, TB, TC, TD per limit state
  spectra.csv                NTC spectra and the record's spectrum
  artificial_accel_SLV.csv   time, seven artificial accelerograms [m/s2]
  artificial_spectra_SLV.csv their spectra and the mean
  record_descaled.csv        the applied record on its stretched time axis
  summary.json
"""
import argparse
import json
import math
import os

import numpy as np

G = 9.80665
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID = os.path.join(REPO, "resources/hazard/ntc_reticolo_allegatoB.csv")
RECORD = os.path.join(REPO, "resources/records/castelnuovo/montenegro1979_run21_long.txt")
OUT = os.path.join(REPO, "output/castelnuovo/hazard")
TR_GRID = [30, 50, 72, 101, 140, 201, 475, 975, 2475]
LIMIT_STATES = {"SLO": 0.81, "SLD": 0.63, "SLV": 0.10, "SLC": 0.05}   # PVR
T1_MODEL = 1.0 / 6.2875   # fundamental period of the eigenvalue analysis [s]

ap = argparse.ArgumentParser()
# Historic centre of Castelnuovo di Porto, around the Rocca Colonna
# (WGS84; the ~100 m shift to the ED50 datum of the grid is irrelevant
# against its ~5.5 km spacing).
ap.add_argument("lat", nargs="?", type=float, default=42.1265)
ap.add_argument("lon", nargs="?", type=float, default=12.5000)
ap.add_argument("--soil", default="A", choices="ABCDE")
ap.add_argument("--topo", default="T1", choices=["T1", "T2", "T3", "T4"])
ap.add_argument("--vn", type=float, default=50.0)
ap.add_argument("--cu", type=float, default=1.0)
ap.add_argument("--n-acc", type=int, default=7)
ap.add_argument("--seed", type=int, default=2026)
args = ap.parse_args()
os.makedirs(OUT, exist_ok=True)

# --- hazard parameters at the site -----------------------------------------
grid = np.genfromtxt(GRID, delimiter=",", names=True)
lon, lat = grid["LON"], grid["LAT"]


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


d = haversine(args.lat, args.lon, lat, lon)
# the four nodes of the grid cell holding the site: the nearest node in
# each quadrant around it
quads = []
for sy in (1, -1):
    for sx in (1, -1):
        m = (np.sign(lat - args.lat) * sy >= 0) & (np.sign(lon - args.lon) * sx >= 0)
        quads.append(np.flatnonzero(m)[np.argmin(d[m])])
nodes = np.array(quads)
w = 1.0 / d[nodes]


def node_param(tr, p):
    key = f"T{tr}{p}"
    return grid[key][nodes]


def site_param(tr_target, p):
    """Allegato A: inverse-distance mean in space, log-log in TR."""
    if tr_target in TR_GRID:
        vals = node_param(tr_target, p)
        return float((vals * w).sum() / w.sum())
    i = np.searchsorted(TR_GRID, tr_target)
    tr1, tr2 = TR_GRID[i - 1], TR_GRID[i]
    p1, p2 = site_param(tr1, p), site_param(tr2, p)
    return float(math.exp(math.log(p1) + math.log(p2 / p1) * math.log(tr_target / tr1)
                          / math.log(tr2 / tr1)))


def soil_factors(soil, ag, F0, tcs):
    if soil == "A":
        return 1.0, 1.0
    rules = {"B": (1.40, 0.40, 1.20, 1.10, -0.20), "C": (1.70, 0.60, 1.50, 1.05, -0.33),
             "D": (2.40, 1.50, 1.80, 1.25, -0.50), "E": (2.00, 1.10, 1.60, 1.15, -0.40)}
    a, b, smax, c1, c2 = rules[soil]
    return float(np.clip(a - b * F0 * ag, 1.0, smax)), float(c1 * tcs ** c2)


ST = {"T1": 1.0, "T2": 1.2, "T3": 1.2, "T4": 1.4}[args.topo]
VR = args.vn * args.cu
params = {}
for ls, pvr in LIMIT_STATES.items():
    tr = -VR / math.log(1 - pvr)
    tr = round(tr)        # 30, 50, 475, 975 for VR = 50
    ag = site_param(tr, "ag") / 10.0      # table in g/10
    F0 = site_param(tr, "F0")
    tcs = site_param(tr, "Tc")
    SS, CC = soil_factors(args.soil, ag, F0, tcs)
    S = SS * ST
    TC = CC * tcs
    params[ls] = dict(TR=tr, ag_g=ag, F0=F0, Tc_star=tcs, SS=SS, ST=ST, S=S,
                      CC=CC, TB=TC / 3, TC=TC, TD=4 * ag + 1.6, PGA_site_g=ag * S)


def elastic_spectrum(T, p, eta=1.0):
    """NTC 2018 eq. 3.2.2, horizontal, in g."""
    ag, S, F0, TB, TC, TD = p["ag_g"], p["S"], p["F0"], p["TB"], p["TC"], p["TD"]
    T = np.asarray(T, float)
    se = np.where(T < TB, ag * S * eta * F0 * (T / TB + (1 - T / TB) / (eta * F0)),
         np.where(T < TC, ag * S * eta * F0,
         np.where(T < TD, ag * S * eta * F0 * TC / np.maximum(T, 1e-9),
                  ag * S * eta * F0 * TC * TD / np.maximum(T, 1e-9) ** 2)))
    return se


# --- 5% response spectrum, exact piecewise-linear recurrence ----------------
def response_spectrum(acc, dt, periods, zeta=0.05):
    """Pseudo-acceleration spectrum [same units as acc] (Nigam & Jennings 1969)."""
    sa = np.empty(len(periods))
    for k, T in enumerate(periods):
        wn = 2 * math.pi / T
        wd = wn * math.sqrt(1 - zeta ** 2)
        e = math.exp(-zeta * wn * dt)
        s, c = math.sin(wd * dt), math.cos(wd * dt)
        z = zeta / math.sqrt(1 - zeta ** 2)
        a11 = e * (z * s + c); a12 = e * s / wd
        a21 = -wn / math.sqrt(1 - zeta ** 2) * e * s; a22 = e * (c - z * s)
        t1 = (2 * zeta ** 2 - 1) / (wn ** 2 * dt); t2 = 2 * zeta / (wn ** 3 * dt)
        b11 = e * ((t1 + zeta / wn) * s / wd + (t2 + 1 / wn ** 2) * c) - t2
        b12 = -e * (t1 * s / wd + t2 * c) - 1 / wn ** 2 + t2
        b21 = (e * ((t1 + zeta / wn) * (c - z * s) - (t2 + 1 / wn ** 2) * (wd * s + zeta * wn * c))
               + 1 / (wn ** 2 * dt))
        b22 = -e * (t1 * (c - z * s) - t2 * (wd * s + zeta * wn * c)) - 1 / (wn ** 2 * dt)
        u = v = 0.0
        umax = 0.0
        for i in range(len(acc) - 1):
            p0, p1 = -acc[i], -acc[i + 1]
            u, v = a11 * u + a12 * v + b11 * p0 + b12 * p1, a21 * u + a22 * v + b21 * p0 + b22 * p1
            if abs(u) > umax:
                umax = abs(u)
        sa[k] = wn ** 2 * umax
    return sa


try:                      # the loop above in plain Python is slow; numba if present
    import numba
    response_spectrum = numba.njit(response_spectrum)
except Exception:          # noqa: BLE001
    pass

periods = np.unique(np.concatenate([np.geomspace(0.02, 4.0, 90), [T1_MODEL, 0.15, 2.0]]))

# --- applied record ----------------------------------------------------------
rec = np.loadtxt(RECORD, comments="#")
dt_rec = 0.005 * math.sqrt(2)
n_an = 3900                          # 27.58 s analysed
rec = rec[:n_an]
t_rec = np.arange(len(rec)) * dt_rec
sa_rec = np.asarray(response_spectrum(rec, dt_rec, periods)) / G
pga_rec = float(np.abs(rec).max() / G)

# --- artificial spectrum-compatible accelerograms (target SLV) ---------------
pS = params["SLV"]
target = lambda T: elastic_spectrum(T, pS) * G            # m/s2
DT, DUR = 0.01, 30.0
n = int(round(DUR / DT))
t = np.arange(n) * DT
env = np.where(t < 2.0, (t / 2.0) ** 2, np.where(t < 17.0, 1.0, np.exp(-0.35 * (t - 17.0))))
freqs = np.fft.rfftfreq(n, DT)
f_lo, f_hi = 0.2, 25.0
band = (freqs >= f_lo) & (freqs <= f_hi)
rng = np.random.default_rng(args.seed)
per_match = periods[(periods >= 0.04) & (periods <= 4.0)]


def baseline(a):
    """Remove a quadratic trend from the displacement, so that velocity and
    displacement end close to zero, then re-impose the envelope edges."""
    v = np.cumsum(a) * DT
    dsp = np.cumsum(v) * DT
    c = np.polyfit(t, dsp, 3)
    trend_acc = np.polyval(np.polyder(c, 2), t)
    return a - trend_acc


acc_set, sa_set = [], []
for j in range(args.n_acc):
    # The Fourier amplitudes of a STATIONARY signal are corrected at each
    # iteration and the envelope is applied once to the result, so that it
    # does not compound over the iterations.
    S = np.fft.rfft(rng.standard_normal(n))
    S[~band] = 0
    f_p = 1.0 / per_match[::-1]
    for it in range(30):
        a = baseline(np.fft.irfft(S, n) * env)
        sa = np.asarray(response_spectrum(a, DT, per_match))
        ratio = target(per_match) / sa
        if np.max(np.abs(ratio - 1)) < 0.05:
            break
        # period -> frequency, interpolate the correction on the FFT grid
        S = S * np.interp(freqs, f_p, ratio[::-1], left=ratio[-1], right=ratio[0])
        S[~band] = 0
    acc_set.append(a)
    sa_set.append(np.asarray(response_spectrum(a, DT, periods)) / G)
    print(f"accelerogram {j + 1}: {it + 1} iterations, PGA {np.abs(a).max() / G:.3f} g, "
          f"max misfit {np.max(np.abs(ratio - 1)) * 100:.1f}%")
acc_set, sa_set = np.array(acc_set), np.array(sa_set)
sa_mean = sa_set.mean(axis=0)
tgt_g = elastic_spectrum(periods, pS)
chk = (periods >= 0.15) & (periods <= max(2.0, 2 * T1_MODEL))
ratio_mean = sa_mean[chk] / tgt_g[chk]
code_ok = bool(ratio_mean.min() >= 0.90)

# --- outputs ------------------------------------------------------------------
with open(f"{OUT}/hazard_parameters.csv", "w") as fh:
    fh.write("limit_state,TR_years,ag_g,F0,Tc_star_s,SS,ST,S,CC,TB_s,TC_s,TD_s,PGA_site_g\n")
    for ls, p in params.items():
        fh.write(f"{ls},{p['TR']},{p['ag_g']:.4f},{p['F0']:.3f},{p['Tc_star']:.3f},{p['SS']:.3f},"
                 f"{p['ST']:.2f},{p['S']:.3f},{p['CC']:.3f},{p['TB']:.3f},{p['TC']:.3f},"
                 f"{p['TD']:.3f},{p['PGA_site_g']:.4f}\n")
with open(f"{OUT}/spectra.csv", "w") as fh:
    fh.write("T_s," + ",".join(f"Se_{ls}_g" for ls in params) + ",Sa_record_g,Sa_artificial_mean_g\n")
    for i, T in enumerate(periods):
        fh.write(f"{T:.4f}," + ",".join(f"{float(elastic_spectrum(T, p)):.5f}" for p in params.values())
                 + f",{sa_rec[i]:.5f},{sa_mean[i]:.5f}\n")
np.savetxt(f"{OUT}/artificial_accel_SLV.csv", np.column_stack([t, acc_set.T]), delimiter=",",
           header="time_s," + ",".join(f"acc{j + 1}_m_s2" for j in range(args.n_acc)),
           comments="", fmt="%.6g")
np.savetxt(f"{OUT}/artificial_spectra_SLV.csv", np.column_stack([periods, sa_set.T, sa_mean]),
           delimiter=",", header="T_s," + ",".join(f"Sa{j + 1}_g" for j in range(args.n_acc))
           + ",Sa_mean_g", comments="", fmt="%.6g")
np.savetxt(f"{OUT}/record_descaled.csv", np.column_stack([t_rec, rec]), delimiter=",",
           header="time_s,acc_m_s2", comments="", fmt="%.6g")

i1 = int(np.argmin(np.abs(periods - T1_MODEL)))
summary = {
    "site_lat": args.lat, "site_lon": args.lon,
    "grid_nodes": [{"ID": int(grid["ID"][k]), "lat": float(lat[k]), "lon": float(lon[k]),
                    "distance_km": float(d[k])} for k in nodes],
    "VN": args.vn, "CU": args.cu, "VR": VR, "soil": args.soil, "topo": args.topo,
    "limit_states": params,
    "record_PGA_g": pga_rec,
    "record_over_SLV_PGA": pga_rec / params["SLV"]["PGA_site_g"],
    "record_over_SLC_PGA": pga_rec / params["SLC"]["PGA_site_g"],
    "T1_model_s": T1_MODEL,
    "Sa_record_T1_g": float(sa_rec[i1]),
    "Se_SLV_T1_g": float(tgt_g[i1]),
    "Se_SLC_T1_g": float(elastic_spectrum(T1_MODEL, params["SLC"])),
    "record_peak_Sa_g": float(sa_rec.max()), "record_peak_Sa_T_s": float(periods[np.argmax(sa_rec)]),
    "artificial": {"n": args.n_acc, "dt_s": DT, "duration_s": DUR, "seed": args.seed,
                   "PGA_g": [float(np.abs(a).max() / G) for a in acc_set],
                   "mean_over_target_min_0.15_2s": float(ratio_mean.min()),
                   "mean_over_target_max_0.15_2s": float(ratio_mean.max()),
                   "NTC_3.2.3.6_lower_bound_ok": code_ok},
}
with open(f"{OUT}/summary.json", "w") as fh:
    json.dump(summary, fh, indent=2)
print(json.dumps({k: summary[k] for k in ("grid_nodes", "record_PGA_g", "record_over_SLV_PGA",
                                          "Sa_record_T1_g", "Se_SLV_T1_g", "artificial")}, indent=1))
for ls, p in params.items():
    print(f"{ls}: TR {p['TR']:4d}  ag {p['ag_g']:.4f} g  F0 {p['F0']:.3f}  Tc* {p['Tc_star']:.3f} s"
          f"  S {p['S']:.2f}  PGA {p['PGA_site_g']:.3f} g  plateau {p['ag_g'] * p['S'] * p['F0']:.3f} g")
