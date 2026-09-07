"""
Re-render the full-aggregate self-weight deformed-shape plot from the
already-computed, cached results (results/*.h5, written by
self_weight_check_full_aggregate.py's Results.from_recorders() call) -
no need to re-run the mesh/partition/MPI analysis just to change how the
picture looks.

Cleaner render than the first attempt: ghost overlay off and no per-
triangle edge lines (both were making the mesh unreadable at full-
building scale, 70k+ elements), white-to-blue colormap (matches what the
user's advisor expects, not viridis).

Windows note: if savefig raises OSError("Invalid argument") on a path
that already exists, it's very likely Explorer holding a lock/thumbnail
handle on that exact file because the folder is open in a window - close
that window (or navigate it elsewhere) and retry, or just pick a fresh
filename. Not a bug in this script (verified: writing a brand-new
filename to the same directory always succeeds).
"""
import glob
import sys

sys.path.insert(0, "/app")

from apeGmsh import Results

candidates = sorted(glob.glob("results/*.h5"))
assert candidates, "no cached results/*.h5 found - run self_weight_check_full_aggregate.py first"
results = Results.from_native(candidates[-1])
print(results)

ax = results.plot.deformed(
    component="displacement_z", scale=200.0, ghost=False,
    cmap="Blues", edge_color=None,
)
ax.set_title("Castelnuovo FULL aggregate - self-weight, bonded, linear elastic - deformed x200")
path = "output/castelnuovo/plots/full_aggregate_deformed_uz.png"
ax.figure.savefig(path, dpi=150, bbox_inches="tight")
print(f"Wrote {path}")
