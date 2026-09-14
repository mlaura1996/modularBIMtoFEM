"""Which solid elements get strain/damage/stress recorders in a nonlinear
time-history.

Recording all ~120k elements every step would write hundreds of GB
(measured: 39 GB even sampled), so only a subset gets the expensive
per-material recorders: every `sample_stride`-th element of the whole
mesh, plus every element of every volume that carries a Task A contact
interface or an open-junction tie - the elements where damage is actually
expected.

Shared between docker/opensees/timehistory_castelnuovo.py (the live run,
which needs this list to build the recorders) and
docker/opensees/reconstruct_sampled_elements.py (recovering the same list
after the fact for a run that finished before this module existed - see
that script's docstring for why the list has to be reconstructed rather
than just re-read). ONE implementation, used by both, so a future change
here cannot silently make the live run and a later reconstruction disagree
about what "element index 7" in a results CSV actually is.
"""
import gmsh


def select_recorded_elements(element_tags, selected_interfaces, open_junctions,
                             sample_stride):
    """Returns (sampled, interesting_vols, focus_eles).

    element_tags:        every solid element tag in the model, in the order
                         Element.add_elements_to_opensees produced them
    selected_interfaces: the Task A interfaces in this model (each a dict
                         with 'volume_a'/'volume_b', as InterfaceSelection
                         returns them)
    open_junctions:      iterable of (volume_a, volume_b, gap) - the open
                         junctions the equalDOF ties close
    sample_stride:       1 element in this many, uniformly across the mesh

    Needs the CURRENT gmsh model to already hold the mesh element_tags was
    taken from - it queries gmsh.model.mesh.getElements(dim=3, ...) per
    volume, which only returns real data against a mesh that is actually
    loaded/generated in this gmsh session.

    sampled is SORTED ascending: this is what
    ops.recorder("Element", ..., "-ele", *sampled, ...) then uses as its
    element list, and OpenSees writes the recorder's columns in exactly
    that argument order, so this sort order IS the column order every
    results CSV is built against - changing it silently would misalign
    every "element index" already on record.
    """
    interesting_vols = (
        {c["volume_a"] for c in selected_interfaces} |
        {c["volume_b"] for c in selected_interfaces} |
        {v for a, b, _g in open_junctions for v in (a, b)}
    )
    focus_eles = set()
    for v in interesting_vols:
        _et, etg, _en = gmsh.model.mesh.getElements(dim=3, tag=v)
        for tags in etg:
            focus_eles.update(int(t) for t in tags)
    all_tags = set(int(e) for e in element_tags)
    sampled = (set(int(e) for e in element_tags[::sample_stride]) | focus_eles) & all_tags
    return sorted(sampled), interesting_vols, focus_eles
