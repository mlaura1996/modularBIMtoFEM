"""
Follow-up to the user's sharper question: not "is there a visible hole" but
"could the geometric kernel be treating these volumes as basically separate
- fragment() only catching a razor-thin sliver where they happen to be
exactly coincident, while the REAL, intended contact (e.g. a slab resting
on a wall's full top surface) is actually a few mm/cm off everywhere else,
because the source STEP geometry was never perfectly abutted there".

This is a different, more fundamental check than
render_volume118_check.py / render_volume106_check.py: those proved the
fragment()-found surface IS a genuine shared-node boundary (not a false
positive), but did not ask whether that surface is the FULL intended
contact or just a lucky sliver of a much larger near-miss.

Method: for each (target, neighbour) pair, look at ALL boundary faces of
both volumes (not just the one fragment() fused), find face pairs that are
roughly PARALLEL and CLOSE (bounding boxes within a generous search
radius), and report:
  - the fragment()-fused face's own area (already known)
  - the largest NEARBY-but-not-fused face pair's bounding-box overlap area
    and the gap (perpendicular offset) between them
If a much bigger nearby face pair exists with only a small gap (mm-cm
scale), that supports the "real joint is bigger, source geometry just
doesn't quite meet" hypothesis. If nothing nearby is larger, the small
fused area is genuinely the full extent of that pair's contact - not a
tolerance artifact.
"""
import sys

sys.path.insert(0, "/app")

import numpy as np
import gmsh
from apeGmsh import apeGmsh

from core.mesh_generation.wall_interfaces import InterfaceDetection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
PAIRS = [(118, 71), (118, 110), (106, 71), (106, 92)]
SEARCH_RADIUS_M = 1.5  # how far to look for a "nearby but not fused" face

with apeGmsh(model_name="diagnose_joint_gaps") as g:
    g.mesh.sizing.set_size_sources(from_points=False)
    g.model.io.load_step(STEP_PATH)
    gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
    gmsh.model.occ.synchronize()
    all_vols = gmsh.model.getEntities(3)
    print(f"{len(all_vols)} volumes loaded.")

    candidates = InterfaceDetection.find_touching_surface_pairs()
    cand_by_pair = {}
    for c in candidates:
        cand_by_pair.setdefault((min(c["volume_a"], c["volume_b"]),
                                  max(c["volume_a"], c["volume_b"])), []).append(c)

    def volume_faces(vol):
        """List of (surf_tag, area, centroid, normal, bbox) for every
        boundary face of `vol`."""
        out = []
        boundary = gmsh.model.getBoundary([(3, vol)], oriented=False, combined=False)
        for _bdim, bsurf in boundary:
            s = abs(bsurf)
            area = gmsh.model.occ.getMass(2, s)
            com = np.array(gmsh.model.occ.getCenterOfMass(2, s))
            normal = np.array(gmsh.model.getNormal(s, [0.5, 0.5]))
            bbox = gmsh.model.occ.getBoundingBox(2, s)
            out.append((s, area, com, normal, bbox))
        return out

    for target, other in PAIRS:
        print(f"\n{'='*70}\nVolume {target} <-> volume {other}\n{'='*70}")
        key = (min(target, other), max(target, other))
        fused = cand_by_pair.get(key, [])
        fused_area = sum(c["area_m2"] for c in fused)
        print(f"fragment()-fused area: {fused_area:.4f} m^2 across {len(fused)} face(s)")
        for c in fused:
            print(f"  fused face centroid={[round(x,3) for x in c['centroid']]} "
                  f"area={c['area_m2']:.4f}")

        faces_t = volume_faces(target)
        faces_o = volume_faces(other)
        fused_tags = {c["surface"] for c in fused}

        # Look for the largest NEARBY (bbox-proximity), roughly-parallel,
        # NOT-already-fused face pair between the two volumes - a bigger
        # "almost touching" pair would indicate the real/intended contact
        # is larger than what got fused.
        best = None
        for s1, a1, c1, n1, bb1 in faces_t:
            if s1 in fused_tags:
                continue
            for s2, a2, c2, n2, bb2 in faces_o:
                if s2 in fused_tags:
                    continue
                # roughly parallel (or anti-parallel) normals
                cos_angle = abs(float(np.dot(n1, n2)))
                if cos_angle < 0.9:
                    continue
                gap = float(np.linalg.norm(c1 - c2))
                if gap > SEARCH_RADIUS_M:
                    continue
                cand_area = min(a1, a2)
                if best is None or cand_area > best[0]:
                    best = (cand_area, gap, s1, a1, c1, s2, a2, c2)

        if best is None:
            print(f"No other nearby (<{SEARCH_RADIUS_M} m), roughly-parallel "
                  f"un-fused face pair found - the fused area above is the "
                  f"full extent of what these two volumes have near each "
                  f"other, not a sliver of a bigger near-miss.")
        else:
            cand_area, gap, s1, a1, c1, s2, a2, c2 = best
            print(f"Largest NEARBY un-fused face pair: surf {s1} (area "
                  f"{a1:.3f} m^2, centroid {[round(x,3) for x in c1]}) vs "
                  f"surf {s2} (area {a2:.3f} m^2, centroid "
                  f"{[round(x,3) for x in c2]}) - centroid-to-centroid "
                  f"distance {gap:.4f} m.")
            if gap < 0.1:
                print("  -> WITHIN 10cm: this looks like it COULD be the "
                      "same intended joint, just not exactly coincident - "
                      "worth checking in the render.")
            else:
                print("  -> more than 10cm apart - a different, unrelated "
                      "face pair, not evidence of a bigger missed joint.")

print("\nDone.")
