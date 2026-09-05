"""
Hand-written, partition-aware OpenSeesMP TCL exporter (Task B,
PROJECT_BRIEF.md section 6).

apeGmsh's own g.opensees.export.tcl() was evaluated (see chat log) and
found unsuitable for this project's parallel route: its element registry
(apeGmsh.solvers._element_specs._ELEM_REGISTRY) has no
zeroLengthContactASDimplex entry and no escape hatch for custom element
types, and its Tcl emitter (_opensees_export.py) has zero partition
awareness - no getPID/getNP, no if-guards - it only ever writes a
monolithic, single-domain model regardless of whether
g.mesh.partitioning.partition() was called first.

What apeGmsh IS used for here, because it does this well: g.model.io +
g.mesh.* for CAD import/cleanup/meshing, g.mesh.partitioning.partition(n)
for METIS domain decomposition, and the FEMData broker
(g.mesh.queries.get_fem_data), which carries per-node/per-element
partition assignment (fem.nodes.get(partition=N), fem.elements.get(pg=...,
partition=N)) - exactly the raw data a partition-aware TCL writer needs.
This module is that writer.

Partitioning convention (standard OpenSeesMP idiom, matches Ch.6/7's
reference setup - ParallelRCM numberer, Mumps solver): every rank defines
every node (cheap; DOF numbering needs global consistency across ranks);
each rank only creates the elements belonging to its own partition,
wrapped in `if {$pid == N} { ... }`. OpenSees's parallel domain resolves
shared boundary nodes automatically from which elements reference them on
which rank - nothing needs to be done explicitly for that.
"""


class TclWriter:

    def __init__(self, ndm=3, ndf=3):
        self.ndm = ndm
        self.ndf = ndf
        self._lines = []

    def raw(self, line):
        self._lines.append(line)
        return self

    def header(self):
        self._lines.append(f"model basic -ndm {self.ndm} -ndf {self.ndf}")
        self._lines.append("set pid [getPID]")
        self._lines.append("set np [getNP]")
        return self

    def nodes(self, fem):
        """Every node in the FEMData snapshot, unconditionally (no pid
        guard) - every rank needs the full node set for consistent DOF
        numbering even though it only builds its own partition's elements.
        """
        ids = fem.nodes.ids
        coords = fem.nodes.coords
        for nid, xyz in zip(ids, coords):
            self._lines.append(f"node {int(nid)} {xyz[0]:.6f} {xyz[1]:.6f} {xyz[2]:.6f}")
        return self

    def material_linear_elastic(self, tag, E, nu, rho):
        self._lines.append(f"nDMaterial ElasticIsotropic {tag} {E:.6g} {nu:.6g} {rho:.6g}")
        return self

    def material_asdconcrete3d(self, tag, E, nu, Te, Ts, Td, Ce, Cs, Cd, lch, implex=True):
        """ASDConcrete3D (brief 4.1): exponential tension softening,
        Bezier compression, crack-band auto-regularization. Te/Ts/Td and
        Ce/Cs/Cd come from models.damage_law.ConstitutiveLaws (already
        framework-agnostic pure math, reused as-is - only the TCL text
        rendering is new here).
        """
        def flat(name, vals):
            return f"-{name} " + " ".join(f"{v:.8g}" for v in vals)

        implex_kw = "implex" if implex else ""
        self._lines.append(
            f"nDMaterial ASDConcrete3D {tag} {E:.6g} {nu:.6g} "
            f"{flat('Te', Te)} {flat('Ts', Ts)} {flat('Td', Td)} "
            f"{flat('Ce', Ce)} {flat('Cs', Cs)} {flat('Cd', Cd)} "
            f"{implex_kw} autoRegularization {lch:.6g}".replace("  ", " ")
        )
        return self

    def solid_elements(self, fem, pg_name, material_tag, rank,
                        ele_type="FourNodeTetrahedron", body_force=(0.0, 0.0, 0.0)):
        """Tets in physical group pg_name AND MPI rank `rank`, wrapped in
        an `if {$pid == rank}` guard - the actual domain-decomposition
        step. Silently emits nothing if this (pg, rank) combination is
        empty (normal - most partitions don't touch every material group).

        rank is 0-based (OpenSeesMP's getPID() convention: ranks 0..NP-1).
        apeGmsh's own partition IDs are 1-based (Gmsh's native convention -
        confirmed empirically: g.mesh.partitioning.partition(n_parts=2)
        produces fem.elements.partitions == [1, 2], not [0, 1] - querying
        fem.elements.get(partition=0) raises KeyError). This method does
        the +1 translation so callers can think in OpenSeesMP rank terms
        throughout.
        """
        result = fem.elements.get(pg=pg_name, partition=rank + 1)
        if result.n_elements == 0:
            return self
        self._lines.append(f"if {{$pid == {rank}}} {{")
        for group in result:
            for eid, conn in group:
                nodes_str = " ".join(str(int(n)) for n in conn)
                self._lines.append(
                    f"    element {ele_type} {int(eid)} {nodes_str} {material_tag} "
                    f"{body_force[0]:.6g} {body_force[1]:.6g} {body_force[2]:.6g}"
                )
        self._lines.append("}")
        return self

    def fix(self, fem, pg_name, dofs):
        """Homogeneous SP constraints on every node in pg_name. Unlike
        elements, fix commands are emitted on every rank (matches nodes()
        - cheap, and every rank has this node defined).
        """
        ids = fem.nodes.get(pg=pg_name).ids
        dof_str = " ".join(str(d) for d in dofs)
        for nid in ids:
            self._lines.append(f"fix {int(nid)} {dof_str}")
        return self

    def analysis_static_gravity(self, n_steps=10, tol=1e-8, max_iter=20):
        """Single self-weight ramp (brief 4.4 stage 1), Ch.6/7's solver
        stack: ParallelRCM numberer + Mumps parallel direct solver.
        """
        self._lines.extend([
            "constraints Plain",
            "numberer ParallelRCM",
            "system Mumps",
            f"test NormDispIncr {tol:.3g} {max_iter} 1",
            "algorithm Newton",
            f"integrator LoadControl {1.0 / n_steps:.6g}",
            "analysis Static",
            f"analyze {n_steps}",
        ])
        return self

    def write(self, path):
        with open(path, "w") as f:
            f.write("\n".join(self._lines) + "\n")
        return self
