"""Ties the walls that the source geometry left disconnected.

Why
---
~21 wall-to-wall junctions in the cleaned Castelnuovo STEP have their two
solids drawn 1.5-47 mm apart, so ``fragment()`` never fuses them and the
walls carry no load to each other - visible directly in the mode shapes as
a wall swinging out of plane with its bracing walls standing still.

Fixing it in the geometry was tried first and did not work: every standard
gmsh/OCC lever failed (import tolerance and ``removeAllDuplicates`` do
nothing, ``OCCSewFaces`` destroys the model, boolean tolerance recovers
only 10/21), and three variants of a custom bridge-solid healing each made
the topology worse rather than better (open junctions went 21 -> 145 ->
479 as each bridge introduced more near-coincident faces than it closed).

So the connection is restored at the FE level instead, with multi-point
constraints between the facing nodes - the standard way to couple
non-matching meshes, and the exact reverse of
``core.mesh_generation.wall_interfaces.NodeSplitter``, which deliberately
splits shared nodes to DEcouple a Task A contact interface.

What it does NOT do
-------------------
This does not pretend to be tied contact: a proper tied interface
interpolates a node onto the opposing FACE, whereas this ties node to
nearest node. Pairs are therefore only tied when they are genuinely close
(``max_tie_distance``), so each constraint stands in for two points that
should have been the same point. Nodes further apart laterally are left
alone rather than joined by a long rigid link, which would stiffen the
junction in a way the real masonry does not.

Constraint-handler requirement
------------------------------
``equalDOF`` is a multi-point constraint: the analysis MUST use
``constraints('Transformation')`` (or Penalty/Lagrange). The default
``Plain`` handler silently ignores MPCs, so the ties would appear to be
applied and change nothing.
"""

import numpy as np


def _pairwise_close(pts_a, pts_b, max_dist, chunk=256):
    """Index pairs (i, j) with |pts_a[i] - pts_b[j]| <= max_dist, and the
    distance, sorted nearest first."""
    out = []
    for start in range(0, len(pts_a), chunk):
        block = pts_a[start:start + chunk]
        d = np.sqrt(((block[:, None, :] - pts_b[None, :, :]) ** 2).sum(axis=2))
        ii, jj = np.where(d <= max_dist)
        for i, j in zip(ii, jj):
            out.append((float(d[i, j]), start + int(i), int(j)))
    out.sort()
    return out


def find_junction_ties(junctions, node_tags_by_volume, node_coords_by_tag,
                       excluded_nodes=frozenset(), max_tie_distance=0.05):
    """Build the node pairs to tie.

    junctions:           iterable of (volume_a, volume_b, gap) - the open
                         junctions to close
    node_tags_by_volume: {volume_tag: set of mesh node tags}
    node_coords_by_tag:  {node tag: (x, y, z)}
    excluded_nodes:      nodes that must not become slaves (the fixed base
                         nodes - a node cannot be both fixed and slaved
                         without the two constraints fighting)
    max_tie_distance:    only tie pairs at most this far apart (m)

    Returns (ties, per_junction_counts) where ties is a list of
    (master_tag, slave_tag, distance). Each node appears at most once
    across the whole list, whether as master or slave: OpenSees cannot
    resolve chained or duplicated constraints on the same DOF.
    """
    ties = []
    used = set(excluded_nodes)
    counts = {}

    for va, vb, gap in junctions:
        tags_a = sorted(node_tags_by_volume.get(va, ()))
        tags_b = sorted(node_tags_by_volume.get(vb, ()))
        if not tags_a or not tags_b:
            counts[(va, vb)] = 0
            continue

        pts_a_all = np.array([node_coords_by_tag[t] for t in tags_a])
        pts_b_all = np.array([node_coords_by_tag[t] for t in tags_b])

        # A tie only makes sense between points that should have been
        # coincident, so scale the search with the gap but keep an absolute
        # ceiling - a wide search would start pairing nodes that are simply
        # neighbours along the wall rather than across the junction.
        limit = min(max(2.0 * gap, 0.02), max_tie_distance)

        # Prune to the nodes that could possibly pair before the O(n*m)
        # scan: on a locally refined mesh each of these volumes can carry
        # tens of thousands of nodes, almost all of them far from the
        # junction, and the unpruned scan does not finish in any useful
        # time.
        lo_b, hi_b = pts_b_all.min(axis=0) - limit, pts_b_all.max(axis=0) + limit
        keep_a = np.all((pts_a_all >= lo_b) & (pts_a_all <= hi_b), axis=1)
        lo_a, hi_a = pts_a_all.min(axis=0) - limit, pts_a_all.max(axis=0) + limit
        keep_b = np.all((pts_b_all >= lo_a) & (pts_b_all <= hi_a), axis=1)
        idx_a = np.flatnonzero(keep_a)
        idx_b = np.flatnonzero(keep_b)
        if len(idx_a) == 0 or len(idx_b) == 0:
            counts[(va, vb)] = 0
            continue
        tags_a = [tags_a[i] for i in idx_a]
        tags_b = [tags_b[i] for i in idx_b]
        pts_a = pts_a_all[idx_a]
        pts_b = pts_b_all[idx_b]

        n = 0
        for dist, i, j in _pairwise_close(pts_a, pts_b, limit):
            ta, tb = tags_a[i], tags_b[j]
            if ta in used or tb in used:
                continue
            ties.append((ta, tb, dist))
            used.add(ta)
            used.add(tb)
            n += 1
        counts[(va, vb)] = n

    return ties, counts


def apply_ties(ties, ops, dofs=(1, 2, 3)):
    """Apply the ties as equalDOF constraints. `ops` is openseespy's
    opensees module (passed in so this module stays importable without it)."""
    for master, slave, _d in ties:
        ops.equalDOF(int(master), int(slave), *dofs)
    return len(ties)
