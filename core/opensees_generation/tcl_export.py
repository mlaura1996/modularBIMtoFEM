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
                        ele_type="FourNodeTetrahedron", body_force=(0.0, 0.0, 0.0),
                        node_substitution=None, split_element_ids=None):
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

        node_substitution (optional): {volume_tag: {orig_node_tag: dup_node_tag}}
        from core.mesh_generation.wall_interfaces.NodeSplitter.compute_node_map,
        for Task A/B reconciliation - a confirmed interface's "split side"
        volume gets its connectivity reassigned to duplicate node tags
        exactly as core.opensees_generation.model_builder.Element does for
        the direct-openseespy path (which scopes correctly - see below).
        split_element_ids (required together with node_substitution): the
        set of element ids belonging to any of node_substitution's split
        volumes - MUST be computed by the caller BEFORE
        g.mesh.partitioning.partition() (see below for why), e.g.:

            split_element_ids = set()
            for vol in substitution:
                _t, etags, _n = gmsh.model.mesh.getElements(dim=3, tag=vol)
                for tags in etags:
                    split_element_ids.update(int(t) for t in tags)

        TWO real bugs, found and fixed here, both on the Castelnuovo full-
        aggregate + 11-interface run ("Matrix is Singular Numerically" at
        the very first load step):
        1. An earlier version flattened every volume's {orig: dup} into
           one global dict and applied it to every element in pg_name
           regardless of which volume that element actually belongs to -
           the orig node is on the shared boundary, so it also belongs to
           volume_a's (the NON-split side's) own tets, and those got
           silently rewritten to the duplicate too. Both sides ending up
           on the duplicate orphans the real mesh node entirely - zero
           solid-element stiffness, connected to the rest of the model
           only through its own contact spring (confirmed: the orig node
           of a selected interface was referenced by 0 tet elements
           afterward, all of them had moved to the duplicate).
        2. Fixing (1) by querying `gmshmodel.mesh.getElements(dim=3,
           tag=vol)` from INSIDE this method (called after partitioning)
           silently returns EMPTY for every volume - partitioning mutates
           gmsh's element/entity bookkeeping the same way it breaks
           InterfaceDetection.find_touching_surface_pairs() after
           partition() (see that function's callers' comments) - so the
           "fix" from (1) ended up substituting nothing at all (confirmed:
           split_element_ids came back with 0 elements although the exact
           same query, run BEFORE partition(), found the expected ones).
           Hence the caller-computed `split_element_ids` parameter instead
           of a `gmshmodel` one - it has to be computed at the right time,
           which only the caller (which also calls
           NodeSplitter.compute_node_map before partition()) is in a
           position to guarantee.
        """
        result = fem.elements.get(pg=pg_name, partition=rank + 1)
        if result.n_elements == 0:
            return self

        if node_substitution and split_element_ids is None:
            raise ValueError(
                "solid_elements(): node_substitution was given but "
                "split_element_ids wasn't - cannot scope the substitution to "
                "its own split_volume without it (applying it unscoped "
                "orphans the non-split side's node - see this method's "
                "docstring)."
            )

        sub = {}
        for vol_map in (node_substitution or {}).values():
            sub.update(vol_map)
        self._lines.append(f"if {{$pid == {rank}}} {{")
        for group in result:
            for eid, conn in group:
                if sub and int(eid) in split_element_ids:
                    nodes = [sub.get(int(n), int(n)) for n in conn]
                else:
                    nodes = [int(n) for n in conn]
                nodes_str = " ".join(str(n) for n in nodes)
                self._lines.append(
                    f"    element {ele_type} {int(eid)} {nodes_str} {material_tag} "
                    f"{body_force[0]:.6g} {body_force[1]:.6g} {body_force[2]:.6g}"
                )
        self._lines.append("}")
        return self

    def duplicate_nodes(self, gmshmodel, selected):
        """Emit `node <dup_tag> x y z` for every interface's duplicate
        nodes (core.mesh_generation.wall_interfaces.NodeSplitter.compute_node_map
        must have already populated c['node_map'] on each candidate).
        Unconditional, like nodes() - every rank needs every node defined,
        including the synthetic duplicates, since FEMData/gmsh have no
        knowledge of them (they don't exist in the mesh, only in the
        OpenSees domain) and solid_elements()'s node_substitution will
        reference them from whichever rank owns the split volume's
        elements.

        Deduplicates across interfaces: a node sitting where three or more
        walls meet can be an "interface node" for more than one selected
        interface at once (e.g. two different wall-to-wall joints
        converging on the same corner). Its dup_tag (orig_tag +
        NodeSplitter.TAG_OFFSET) is a pure function of orig_tag, so every
        interface that includes it computes the identical duplicate - found
        the hard way at cluster scale (18 volumes, multiple interfaces):
        emitting `node <tag>` twice for the same tag makes OpenSees reject
        the second one ("node already exists"), aborting the whole run.
        One `node` line per unique dup_tag is correct - it's still the same
        physical duplicate serving every interface that touches it.
        """
        seen = set()
        for c in selected:
            for orig_tag, dup_tag in c["node_map"].items():
                if dup_tag in seen:
                    continue
                seen.add(dup_tag)
                coord, _, _, _ = gmshmodel.mesh.get_node(orig_tag)
                self._lines.append(f"node {int(dup_tag)} {coord[0]:.6f} {coord[1]:.6f} {coord[2]:.6f}")
        return self

    @staticmethod
    def _node_partition_map(fem):
        """{node_id: 0-based rank} for every node FEMData knows about
        (real mesh nodes only - duplicates are synthetic, see
        duplicate_nodes). A node exactly on a partition boundary can
        legitimately appear in more than one partition's node set; this
        keeps whichever assignment is seen last, which is an arbitrary
        but consistent tie-break - correctness (the element ends up on
        exactly one valid rank) doesn't depend on which one.
        """
        mapping = {}
        for p in fem.nodes.partitions:
            for nid in fem.nodes.get(partition=p).ids:
                mapping[int(nid)] = p - 1  # apeGmsh 1-based -> OpenSeesMP 0-based
        return mapping

    def contact_elements(self, fem, selected, Kn_nominal, Kt_nominal, mu=0.6, int_type=1):
        """zeroLengthContactASDimplex elements for confirmed interfaces
        (NodeSplitter.compute_node_map must have already run). Each
        element is guarded onto the rank that owns its ORIGINAL node
        (queried from FEMData's partition assignment - the duplicate has
        no partition of its own, being synthetic) - a functional choice
        (every element lands on exactly one valid rank, node exists there
        because nodes()/duplicate_nodes() are unconditional) rather than a
        load-balance-optimal one.

        KNOWN GAP (brief section 6, explicitly flagged there as needing
        verification): does METIS ever cut a contact pair's two GMSH-mesh
        neighbourhoods (the elements around the original vs. around what
        will become the duplicate) across different ranks in a way that
        matters for solver correctness? Not investigated in this pass -
        OpenSeesMP is designed for elements referencing nodes owned by
        other ranks (that's how any shared boundary works at all), so this
        is very likely fine, but it has not been stress-tested here beyond
        the 2-volume/2-rank case in test_apegmsh_tcl.py.

        Deduplicates across interfaces, same reasoning and same bug as
        duplicate_nodes(): a node shared by two selected interfaces (e.g.
        a corner where three walls meet) produces the identical
        (orig_tag, dup_tag) pair - hence the identical element tag
        (orig_tag + dup_tag) - in both interfaces' node_map. Emitting it
        twice would either duplicate-tag-collide or, if the two
        interfaces' normals differ, silently pick whichever orientation
        happens to be written second. First occurrence wins; which
        interface "claims" a shared corner node is as arbitrary as
        NodeSplitter's own volume-pair tie-break, not a modelling choice
        this method should be making silently for you if it starts to
        matter - flagged, not solved, same as the METIS gap above.
        """
        node_rank = self._node_partition_map(fem)
        lines_by_rank = {}
        seen_pairs = set()
        for c in selected:
            nx, ny, nz = c["normal"]
            for orig_tag, dup_tag in c["node_map"].items():
                if (orig_tag, dup_tag) in seen_pairs:
                    continue
                seen_pairs.add((orig_tag, dup_tag))
                area = c["tributary"][orig_tag]
                Kn = Kn_nominal * area
                Kt = Kt_nominal * area
                rank = node_rank.get(orig_tag)
                if rank is None:
                    raise ValueError(
                        f"Original node {orig_tag} not found in FEMData's partition "
                        f"assignment - was get_fem_data() called after partition()?"
                    )
                lines_by_rank.setdefault(rank, []).append(
                    f"element zeroLengthContactASDimplex "
                    f"{orig_tag + dup_tag} {orig_tag} {dup_tag} "
                    f"{Kn:.6g} {Kt:.6g} {mu:.6g} -orient {nx:.6g} {ny:.6g} {nz:.6g} "
                    f"-intType {int_type}"
                )
        for rank, lines in lines_by_rank.items():
            self._lines.append(f"if {{$pid == {rank}}} {{")
            self._lines.extend(f"    {ln}" for ln in lines)
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
