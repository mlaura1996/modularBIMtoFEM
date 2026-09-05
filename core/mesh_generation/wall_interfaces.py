"""
Wall-to-wall contact interface detection, semi-automatic selection, and
ZeroLengthContactASDimplex generation (Chapter 7 - Task A, see
PROJECT_BRIEF.md section 5).

Pipeline:
    1. InterfaceDetection.find_touching_surface_pairs() - after
       gmsh.model.occ.fragment(), find every pair of solids that share a
       conformal boundary surface (candidate interfaces), with area,
       centroid and normal for each.
    2. InterfaceDetection.classify_orientation() - tag each candidate as a
       likely vertical wall-to-wall joint, a likely horizontal
       floor/slab-bearing contact (to exclude per the brief - floors are
       out of scope for interfaces), or oblique (needs manual judgement).
    3. InterfaceSelection.select_interactive_or_cached() - print a numbered
       table and let the user confirm which candidates become imperfect
       (contact) connections; persist the choice to JSON so re-runs are
       non-interactive.
    4. ContactInterfaceGenerator.tag_physical_groups() - tag the selected
       surfaces as physical groups (so they survive meshing), called before
       gmsh.model.mesh.generate().
    5. NodeSplitter.create_duplicate_nodes() - after meshing: create one
       duplicate OpenSees node per interface node, and return the
       {volume: {orig: dup}} substitution map for
       core.opensees_generation.model_builder.Element.add_elements_to_opensees
       to consume, so that volume's tetrahedra attach to the duplicate
       instead of the shared node.
    6. ContactInterfaceGenerator.generate() - after the volume elements
       exist: emit a zeroLengthContactASDimplex element per original/
       duplicate node pair, with Kn/Kt scaled by that node's tributary area.

Two things this module deliberately does NOT do, per PROJECT_BRIEF.md:
  - It does not filter by IFC entity type (wall vs slab vs stair). The STEP
    geometry for Castelnuovo was prepared outside this repository and its
    solids carry no IFC-derived labels (verified: generic OCC translator
    names, no material/type tag) - see the orientation classification for
    the geometric proxy used instead, and the CLI table for human review.
  - It does not pick a "minimum meaningful interface area" for the user.
    Only true numerical slivers are dropped automatically; area is a sort
    key in the review table so the engineer sets the real cutoff by eye.
"""

import gmsh
import numpy as np
import json
import os


class InterfaceDetection:

    @staticmethod
    def find_touching_surface_pairs(volume_tags=None, min_area=1e-4):
        """Find every boundary surface shared by exactly two solids.

        Must be called after gmsh.model.occ.fragment(volumes, []) +
        synchronize(): the STEP import alone does NOT share topology
        between touching solids (verified empirically on the Castelnuovo
        geometry - 0 shared faces before fragment, 1012 after), so without
        fragment this function finds nothing.

        min_area (m^2) drops only true degenerate/sliver faces coming from
        floating-point noise in the fragment operation, not a "meaningful
        interface" threshold - that judgement belongs to the reviewer.
        """
        gmsh.model.occ.synchronize()
        if volume_tags is None:
            volume_tags = [t for d, t in gmsh.model.getEntities(3)]

        surface_to_volumes = {}
        for vol in volume_tags:
            boundary = gmsh.model.getBoundary([(3, vol)], oriented=False, combined=False)
            for dim, tag in boundary:
                surface_to_volumes.setdefault(abs(tag), set()).add(vol)

        candidates = []
        for surf_tag, vols in surface_to_volumes.items():
            if len(vols) != 2:
                continue
            vol_a, vol_b = sorted(vols)
            area = gmsh.model.occ.getMass(2, surf_tag)
            if area < min_area:
                continue
            com = gmsh.model.occ.getCenterOfMass(2, surf_tag)
            normal = gmsh.model.getNormal(surf_tag, [0.5, 0.5])
            candidates.append({
                "volume_a": vol_a,
                "volume_b": vol_b,
                "surface": surf_tag,
                "area_m2": area,
                "centroid": list(com),
                "normal": list(normal),
            })
        candidates.sort(key=lambda c: -c["area_m2"])
        return candidates

    @staticmethod
    def classify_orientation(candidates, horizontal_normal_tol=0.3, vertical_normal_tol=0.9):
        """Tag each candidate by interface orientation, using the interface
        normal's Z-component as a proxy for wall-to-wall vs floor-bearing
        contact (walls are vertical -> their mutual joint is a vertical
        plane with a near-horizontal normal; floor/slab bearing on a wall
        is a horizontal plane with a near-vertical normal).

        This is a geometric heuristic, not a ground-truth IFC-type filter -
        see module docstring. Every candidate is still shown to the
        reviewer regardless of its class; the class is a sort/filter aid.
        """
        for c in candidates:
            nz = abs(c["normal"][2])
            if nz <= horizontal_normal_tol:
                c["orientation"] = "vertical_joint"       # likely wall-to-wall
            elif nz >= vertical_normal_tol:
                c["orientation"] = "horizontal_bearing"   # likely floor/slab-to-wall
            else:
                c["orientation"] = "oblique"               # needs manual judgement
        return candidates


class InterfaceSelection:

    @staticmethod
    def key_for(candidate):
        """Stable identity for a candidate interface.

        volume_a-volume_b alone is NOT sufficient: 144 of the 1010
        Castelnuovo candidates are volume pairs that touch at more than one
        separate patch (e.g. an L-shaped wall meeting another at two
        distinct locations), so the pair collides for those and silently
        drops one interface (found by round-tripping save/load in testing).
        The centroid, rounded to mm, disambiguates same-pair patches and is
        a geometric invariant that reproduces across a fresh detection run
        on the same input geometry, unlike gmsh's internal surface tags.
        """
        cx, cy, cz = candidate["centroid"]
        return f"{candidate['volume_a']}-{candidate['volume_b']}@{cx:.3f},{cy:.3f},{cz:.3f}"

    @staticmethod
    def present_cli(candidates, default_include=("vertical_joint", "oblique")):
        """Print a numbered table of candidates and collect the user's
        selection from the terminal (brief section 5, option (b)).

        Selection syntax: comma-separated indices and/or ranges
        (e.g. "1,3,5-9"), "all", "none", or a class filter such as
        "vertical" / "oblique" / "horizontal" to pre-select a whole class,
        which can then be refined by index.
        """
        print(f"\n{'#':>4}  {'vol_A':>6} {'vol_B':>6}  {'area_m2':>9}  "
              f"{'centroid (x,y,z)':>28}  {'normal (x,y,z)':>22}  orientation")
        print("-" * 110)
        for i, c in enumerate(candidates, start=1):
            cx, cy, cz = c["centroid"]
            nx, ny, nz = c["normal"]
            print(f"{i:>4}  {c['volume_a']:>6} {c['volume_b']:>6}  {c['area_m2']:>9.4f}  "
                  f"({cx:7.3f},{cy:7.3f},{cz:7.3f})  ({nx:5.2f},{ny:5.2f},{nz:5.2f})  {c['orientation']}")

        default_idx = {i for i, c in enumerate(candidates, start=1) if c["orientation"] in default_include}
        print(f"\n{len(default_idx)} candidates pre-selected by default "
              f"(orientation in {default_include}); {len(candidates) - len(default_idx)} excluded "
              f"(likely floor/slab bearing contacts).")
        raw = input(
            "Confirm wall-to-wall interfaces to generate as contact elements.\n"
            "Enter indices/ranges (e.g. 1,3,5-9), 'all', 'none', or press Enter to accept the default: "
        ).strip()

        if raw == "":
            selected_idx = default_idx
        elif raw.lower() == "all":
            selected_idx = set(range(1, len(candidates) + 1))
        elif raw.lower() == "none":
            selected_idx = set()
        else:
            selected_idx = set()
            for part in raw.split(","):
                part = part.strip()
                if "-" in part:
                    lo, hi = part.split("-")
                    selected_idx.update(range(int(lo), int(hi) + 1))
                elif part:
                    selected_idx.add(int(part))

        selected = [c for i, c in enumerate(candidates, start=1) if i in selected_idx]
        print(f"\n{len(selected)} interface(s) confirmed:")
        for c in selected:
            print(f"  vol {c['volume_a']}-{c['volume_b']}  area={c['area_m2']:.4f} m2")
        return selected

    @staticmethod
    def save(candidates, selected, path):
        payload = {
            "all_candidates": candidates,
            "selected_keys": [InterfaceSelection.key_for(c) for c in selected],
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    @staticmethod
    def load_selected(path, candidates):
        """Re-apply a saved selection to a freshly detected candidate list
        (matched by the volume_a-volume_b key, so re-running detection on
        the same geometry reproduces the same selection non-interactively).
        """
        with open(path) as f:
            payload = json.load(f)
        selected_keys = set(payload["selected_keys"])
        by_key = {InterfaceSelection.key_for(c): c for c in candidates}
        missing = selected_keys - set(by_key.keys())
        if missing:
            raise ValueError(
                f"Saved selection references interfaces not found in the current candidate "
                f"list: {missing}. The geometry may have changed since the selection was made - "
                f"re-run interactively instead of trusting a stale selection file."
            )
        return [by_key[k] for k in selected_keys]

    @staticmethod
    def select_interactive_or_cached(candidates, path):
        """Non-interactive if `path` already exists (brief requirement:
        re-running the pipeline must not require re-selecting), otherwise
        prompts via present_cli() and persists the result.
        """
        if os.path.isfile(path):
            print(f"Loading existing interface selection from {path} (non-interactive).")
            return InterfaceSelection.load_selected(path, candidates)

        selected = InterfaceSelection.present_cli(candidates)
        InterfaceSelection.save(candidates, selected, path)
        print(f"Selection saved to {path}.")
        return selected


class ContactInterfaceGenerator:
    """Generates ZeroLengthContactASDimplex elements at confirmed
    interfaces (brief section 4.2 / 5.4). Must run after meshing: the
    interface surfaces are tagged as physical groups before meshing so
    their FE nodes can be recovered afterwards.
    """

    PHYSICAL_GROUP_PREFIX = "ContactInterface"

    @staticmethod
    def tag_physical_groups(selected):
        """Create one 2D physical group per selected interface surface.
        Call before gmsh.model.mesh.generate(3).
        """
        gmsh.model.occ.synchronize()
        for c in selected:
            name = f"{ContactInterfaceGenerator.PHYSICAL_GROUP_PREFIX}_{InterfaceSelection.key_for(c)}"
            tag = gmsh.model.addPhysicalGroup(2, [c["surface"]], tag=-1, name=name)
            c["physical_group_tag"] = tag
            c["physical_group_name"] = name
        return selected

    @staticmethod
    def get_nodal_tributary_areas(surface_tag):
        """Lumped tributary area per corner node on a meshed 2D surface:
        for every face element on the surface, area/3 is added to each of
        its 3 corner nodes (first 3 nodes of the element regardless of
        element order - gmsh lists corner nodes first). Returns
        {node_tag: area_m2}.
        """
        elem_types, elem_tags, elem_node_tags = gmsh.model.mesh.getElements(dim=2, tag=surface_tag)
        tributary = {}
        for etype, tags, node_tags in zip(elem_types, elem_tags, elem_node_tags):
            props = gmsh.model.mesh.getElementProperties(etype)
            name, dim, order, num_nodes, local_coords, num_primary_nodes = props
            if num_primary_nodes < 3:
                continue  # not a triangle-family face element
            nodes_per_elem = num_nodes
            n_elems = len(tags)
            node_tags = np.array(node_tags).reshape(n_elems, nodes_per_elem)
            for elem_nodes in node_tags:
                corner_nodes = elem_nodes[:3]
                coords = []
                for n in corner_nodes:
                    xyz, _, _, _ = gmsh.model.mesh.getNode(int(n))
                    coords.append(xyz)
                p0, p1, p2 = [np.array(p) for p in coords]
                area = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0))
                for n in corner_nodes:
                    tributary[int(n)] = tributary.get(int(n), 0.0) + area / 3.0
        return tributary

    @staticmethod
    def generate(selected, Kn_nominal, Kt_nominal, mu=0.6, int_type=1, get_new_ops_element_tag=None):
        """Create one zeroLengthContactASDimplex element per original/
        duplicate node pair, Kn/Kt scaled by that node's tributary area.

        Requires NodeSplitter.create_duplicate_nodes(selected, ...) to have
        already run: this function only reads c['node_map'] and
        c['tributary'] (original_tag -> duplicate_tag / area), it does not
        create nodes itself - node creation and the corresponding volume-
        element node substitution have to happen together, in
        model_builder.py, before the contact elements are wired in here.

        Kn_nominal, Kt_nominal are per unit area (brief: Kn=69000, Kt=0.001
        in the N-mm-t unit system used in Ch.6/7 - pass values already
        converted to whatever unit system this model uses).
        """
        import openseespy.opensees as ops
        from utils.tag_manager import Opensees as OpenseesTags

        get_new_ops_element_tag = get_new_ops_element_tag or OpenseesTags.get_next_available_element_tag

        results = []
        for c in selected:
            if "node_map" not in c:
                raise ValueError(
                    f"Interface {InterfaceSelection.key_for(c)} has no node_map - call "
                    f"NodeSplitter.create_duplicate_nodes() first."
                )
            nx, ny, nz = c["normal"]
            created_elements = []

            for orig_tag, dup_tag in c["node_map"].items():
                area = c["tributary"][orig_tag]
                Kn = Kn_nominal * area
                Kt = Kt_nominal * area

                ele_tag = get_new_ops_element_tag()
                ops.element('zeroLengthContactASDimplex', ele_tag, orig_tag, dup_tag,
                            Kn, Kt, mu, '-orient', nx, ny, nz, '-intType', int_type)
                created_elements.append(ele_tag)

            results.append({
                "interface_key": InterfaceSelection.key_for(c),
                "surface": c["surface"],
                "node_map": c["node_map"],
                "elements": created_elements,
            })
        return results


class NodeSplitter:
    """Bridges Task A's confirmed interfaces to element creation in
    core/opensees_generation/model_builder.py: decides which volume on each
    interface gets its nodes duplicated, creates the duplicates in
    OpenSees, and hands back a substitution map that
    Element.add_elements_to_opensees consumes to build that volume's
    tetrahedra against the duplicate instead of the shared node.

    Must run after ContactInterfaceGenerator.tag_physical_groups() +
    meshing (needs the meshed interface surface to know which nodes are
    actually on it), and before Element.add_elements_to_opensees().
    """

    @staticmethod
    def assign_split_side(selected):
        """volume_b (the larger tag of the pair - arbitrary but consistent,
        candidates are already built from sorted(vols)) is the side whose
        tetrahedra get reassigned to duplicate nodes; volume_a keeps the
        originals. Doesn't matter physically which side is which - the
        contact element is symmetric - only that every consumer agrees.
        """
        for c in selected:
            c["split_volume"] = c["volume_b"]
        return selected

    # Offset added to a node's own gmsh tag to get its duplicate's OpenSees
    # tag - NOT an incrementing "next free tag" counter. Found the hard way
    # (see chat log): NodeSplitter runs before Element.add_elements_to_opensees,
    # i.e. before any *real* gmsh mesh node has been added to OpenSees, so
    # querying ops.getNodeTags() for "the next free tag" at that point sees
    # an empty/near-empty model and hands out tags 1, 2, 3... which then
    # collide with the real gmsh node tags created moments later (gmsh's own
    # numbering also starts at 1). That collision doesn't error - add_nodes_to_ops
    # silently skips any tag already present - it just silently gives some
    # real mesh node the wrong (duplicate's) coordinates. 10,000,000 is safely
    # above any node count this pipeline will ever produce (Castelnuovo's
    # finest planned mesh is ~279k nodes) and keeps the mapping invertible
    # (dup_tag - OFFSET == orig_tag) for debugging.
    TAG_OFFSET = 10_000_000

    @staticmethod
    def compute_node_map(gmshmodel, selected):
        """For every selected interface: get its meshed nodes + tributary
        area, compute each node's duplicate tag (orig_tag +
        NodeSplitter.TAG_OFFSET), and store c['node_map'] / c['tributary']
        on each candidate. Pure computation - creates no nodes in any
        backend (openseespy or Tcl text). Split out from
        create_duplicate_nodes() so both backends (direct openseespy calls
        - see that method - and TclWriter.duplicate_nodes for the apeGmsh/
        Task B path) can share the same node-map logic instead of
        duplicating it; the two backends only differ in how they turn a
        (tag, coord) pair into an actual node.

        Returns {split_volume: {orig_node_tag: dup_node_tag}} for
        Element.add_elements_to_opensees's / TclWriter.solid_elements's
        node_substitution argument.

        KNOWN LIMITATION: if the same node is shared by two interfaces that
        both assign the same volume as split_volume (e.g. a node at a
        triple junction where two selected interfaces meet), the second
        interface's update() overwrites the first's duplicate for that
        node - it only gets split once, not twice. Rare at Castelnuovo's
        scale but not handled; would need per-(interface, node) duplicates
        instead of per-(volume, node) if it turns out to matter.
        """
        NodeSplitter.assign_split_side(selected)

        substitution = {}
        for c in selected:
            tributary = ContactInterfaceGenerator.get_nodal_tributary_areas(c["surface"])
            node_map = {}
            for orig_tag in tributary:
                dup_tag = orig_tag + NodeSplitter.TAG_OFFSET
                node_map[orig_tag] = dup_tag

            c["node_map"] = node_map
            c["tributary"] = tributary
            substitution.setdefault(c["split_volume"], {}).update(node_map)

        return substitution

    @staticmethod
    def create_duplicate_nodes(gmshmodel, selected):
        """openseespy backend: compute_node_map() plus an ops.node() call
        per duplicate. See compute_node_map for the shared logic and the
        known limitation; see TclWriter.duplicate_nodes for the Tcl-text
        equivalent used by the apeGmsh/Task B path.
        """
        import openseespy.opensees as ops

        NodeSplitter.assign_split_side(selected)

        substitution = {}
        for c in selected:
            tributary = ContactInterfaceGenerator.get_nodal_tributary_areas(c["surface"])
            node_map = {}
            for orig_tag in tributary:
                coord, _, _, _ = gmshmodel.mesh.get_node(orig_tag)
                dup_tag = orig_tag + NodeSplitter.TAG_OFFSET
                ops.node(int(dup_tag), *coord)
                node_map[orig_tag] = dup_tag

            c["node_map"] = node_map
            c["tributary"] = tributary
            substitution.setdefault(c["split_volume"], {}).update(node_map)

        return substitution
