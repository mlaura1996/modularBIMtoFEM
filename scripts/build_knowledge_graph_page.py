"""Builds the browsable page of the Castelnuovo knowledge graph.

    python scripts/build_knowledge_graph_page.py [--photos <survey photo folder>]

Reads output/castelnuovo/knowledge_graph.ttl (written by
docker/opensees/castelnuovo_knowledge_graph.py) and the three ontologies in
resources/ontologies/ for labels, and writes a self-contained page to
docs/source/_extra/knowledge-graph/index.html, together with a copy of the
graph to download. Sphinx copies docs/source/_extra/ to the root of the
documentation site, so the page is published with it.

The page has an interactive view of the graph and tables of the same
content (facades, masonry types, documents, people and activities). Both
are generated from the graph itself, not from the input records, so what
the page shows is what the graph says. Rerun after regenerating the graph.

Photographs. With --photos pointing at the folder the survey photographs
were extracted to (the one their dcterms:identifier paths are relative to,
A-417/417_a/... and so on), every photograph of the graph is written as a
small thumbnail and a larger view to docs/source/_extra/knowledge-graph/
photos/, resized and saved without metadata. Without --photos, the images
already there are reused; photographs without an image are listed by name.

Needs rdflib, and Pillow for --photos.
"""
import json
import os
import shutil
import sys
from collections import defaultdict

import rdflib
from rdflib import RDF, RDFS, OWL, Literal, URIRef

KG = "output/castelnuovo/knowledge_graph.ttl"
ONTOLOGIES = ["resources/ontologies/hsv.ttl", "resources/ontologies/hsto.ttl",
              "resources/ontologies/hmo.ttl"]
OUT_DIR = "docs/source/_extra/knowledge-graph"
THUMB_PX, LARGE_PX = 320, 1000

NS = {
    "": "https://example.org/castelnuovo#",
    "hsv": "https://w3id.org/hsv#",
    "hsto": "https://w3id.org/hsto#",
    "hmo": "https://w3id.org/hmo#",
    "saref": "https://saref.etsi.org/core/",
    "prov": "http://www.w3.org/ns/prov#",
    "dcterms": "http://purl.org/dc/terms/",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "rdfs": str(RDFS),
    "owl": str(OWL),
}
C = rdflib.Namespace(NS[""])
HSV, HSTO, HMO = (rdflib.Namespace(NS[p]) for p in ("hsv", "hsto", "hmo"))
SAREF, PROV, DCT = (rdflib.Namespace(NS[p]) for p in ("saref", "prov", "dcterms"))
FOAF, SKOS = rdflib.Namespace(NS["foaf"]), rdflib.Namespace(NS["skos"])

# node groups, in legend order: (key, label, shown by default)
GROUPS = [
    ("context", "Built context (HSV)", True),
    ("facade", "Façades (HSV, HSTO)", True),
    ("structure", "Floors and openings (HSTO)", True),
    ("wall", "Masonry walls (HMO)", True),
    ("type", "Masonry types", True),
    ("document", "Documents (HSV)", True),
    ("activity", "Activities", True),
    ("agent", "People and organisations", True),
    ("photo", "Photographs (HSV)", False),
    ("bim", "BIM elements (IFC)", False),
    ("hmo", "Quality index and properties (HMO)", False),
    ("constant", "Pattern entities (HMO)", False),
]
PROPERTY_CLASSES = {"CompressiveStrength": ("f_c", "MPa"), "YoungModulus": ("E", "MPa"),
                    "ShearModulus": ("G", "MPa"), "ShearStrengthTC": ("τ₀", "MPa"),
                    "MassDensity": ("ρ", "kg/m³")}


def curie(term):
    s = str(term)
    best = None
    for p, ns in NS.items():
        if s.startswith(ns) and (best is None or len(ns) > len(NS[best])):
            best = p
    return f"{best}:{s[len(NS[best]):]}" if best is not None else s


def local(term):
    return curie(term).split(":", 1)[1]


def photo_images(kg, src_dir):
    """{photo curie: (thumbnail, large view)} relative to OUT_DIR, writing them from src_dir if given."""
    out = os.path.join(OUT_DIR, "photos")
    images = {}
    photos = sorted(kg.subjects(RDF.type, HSV.Photo), key=str)
    if src_dir:
        from PIL import Image, ImageOps
        os.makedirs(out, exist_ok=True)
    for ph in photos:
        name = local(ph)
        thumb, large = f"photos/{name}.jpg", f"photos/{name}_large.jpg"
        if src_dir:
            src = os.path.join(src_dir, str(kg.value(ph, DCT.identifier)))
            if not os.path.exists(src):
                raise SystemExit(f"photograph not found: {src}")
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            for px, rel, q in ((THUMB_PX, thumb, 70), (LARGE_PX, large, 72)):
                copy = im.copy()
                copy.thumbnail((px, px))
                copy.save(os.path.join(OUT_DIR, rel), "JPEG", quality=q, optimize=True)  # no metadata
        if os.path.exists(os.path.join(OUT_DIR, thumb)):
            images[curie(ph)] = (thumb, large)
    return images


def main():
    src_dir = sys.argv[sys.argv.index("--photos") + 1] if "--photos" in sys.argv else None
    kg = rdflib.Graph().parse(KG, format="turtle")
    onto = rdflib.Graph()
    for path in ONTOLOGIES:
        onto.parse(path, format="turtle")
    both = kg + onto

    def label(term):
        for g in (kg, onto):
            for lab in g.objects(term, RDFS.label):
                if not isinstance(lab, Literal) or lab.language in (None, "en"):
                    return str(lab)
        name = kg.value(term, FOAF.name)
        return str(name) if name else local(term)

    def types(term):
        return sorted({t for t in kg.objects(term, RDF.type) if t != OWL.NamedIndividual}, key=str)

    def group(term):
        ts = set(types(term))
        if term in ts or str(term) == str(C.KnowledgeGraph):
            return None
        if ts & {PROV.Association, PROV.Role}:
            return None     # shown as roles of the people, not as nodes
        if (term, DCT.isPartOf, C.BIMModel) in kg:
            return "bim"
        if HSV.Photo in ts:
            return "photo"
        if ts & {HSV.Facade, HSTO.Facade}:
            return "facade"
        if ts & {HSV.HistoricCentre, HSV.Aggregate, HSV.StructuralUnit, HSV.TraditionalConstructionTechnique}:
            return "context"
        if ts & {HSTO.TimberFloor, HSTO.HistoricOpening}:
            return "structure"
        if HMO.MasonryWall in ts:
            return "wall"
        if SKOS.Concept in ts:
            return "type"
        if ts & {FOAF.Person, FOAF.Organization}:
            return "agent"
        if PROV.Activity in ts:
            return "activity"
        if any(str(t).startswith(NS["hsv"]) for t in ts):
            return "document"
        if any(str(t).startswith(NS["hmo"]) for t in ts):
            return "hmo"
        if str(term).startswith(NS["hmo"]):
            return "constant"
        return None

    images = photo_images(kg, src_dir)

    # --- graph view ------------------------------------------------------------
    nodes, edges = {}, []

    def add_node(term):
        key = curie(term)
        if key in nodes:
            return key
        g = group(term)
        if g is None:
            return None
        literals = defaultdict(list)
        for p, o in kg.predicate_objects(term):
            if isinstance(o, Literal) and p != RDFS.label:
                literals[curie(p)].append(str(o))
        nodes[key] = {"id": key, "label": label(term), "group": g,
                      "types": [curie(t) for t in types(term)] or
                               (["IFC element of the BIM model"] if g == "bim" else ["hmo constant"]),
                      "literals": dict(literals)}
        if key in images:
            nodes[key]["img"], nodes[key]["large"] = images[key]
        return key

    for s, p, o in kg:
        if p == RDF.type or not isinstance(o, URIRef) or p == OWL.imports:
            continue
        a, b = add_node(s), add_node(o)
        if a and b:
            edges.append({"from": a, "to": b, "label": curie(p)})
    for s in set(kg.subjects(RDF.type, OWL.NamedIndividual)):
        add_node(s)

    # --- tables ------------------------------------------------------------------
    def wall_values(wall):
        out = {}
        mqi = kg.value(wall, HMO.hasMasonryQualityIndex)
        for direction, prop in (("MQI vertical", "MQITotalVertical"),
                                ("MQI out of plane", "MQITotalOutOfPlane"),
                                ("MQI in plane", "MQITotalInPlane")):
            v = kg.value(mqi, HMO[prop])
            out[direction] = float(v) if v is not None else None
        rve = kg.value(wall, HMO.hasRepresentativeVolumeElement)
        found = {}
        for prop in kg.objects(rve, HMO.hasHomogenisedMechanicalProperty):
            for t in kg.objects(prop, RDF.type):
                if local(t) in PROPERTY_CLASSES:
                    v = kg.value(prop, SAREF.hasValue)
                    found[local(t)] = float(v) if v is not None else None
        for cls, (sym, unit) in PROPERTY_CLASSES.items():   # fixed column order
            out[f"{sym} ({unit})"] = found.get(cls)
        return out

    facades = []
    for f in sorted(kg.subjects(RDF.type, HSTO.Facade), key=str):
        wall = kg.value(f, HSTO.isMadeOf)
        unit = next(kg.subjects(DCT.hasPart, f), None)
        photos = sorted(kg.objects(f, HSV.hasDocument), key=str)
        row = {"Façade": label(f).replace("Facade", "Façade"), "_id": curie(f),
               "Unit": local(unit).replace("Unit_", "") if unit else "",
               "Masonry type": label(kg.value(wall, DCT.type)), "_wall": curie(wall),
               "Photographs": len(photos)}
        row.update(wall_values(wall))
        row["_photos"] = [{"file": str(kg.value(ph, DCT.identifier)),
                           "taken": str(kg.value(ph, DCT.created) or ""),
                           "img": images.get(curie(ph), (None, None))[0],
                           "large": images.get(curie(ph), (None, None))[1]} for ph in photos]
        facades.append(row)

    mtypes = []
    for t in sorted(kg.subjects(RDF.type, SKOS.Concept), key=str):
        walls = sorted((w for w in kg.subjects(DCT.type, t) if (w, RDF.type, HMO.MasonryWall) in kg), key=str)
        bim_elements = [e for e in kg.subjects(DCT.type, t) if (e, DCT.isPartOf, C.BIMModel) in kg]
        fac = [label(f) for w in walls for f in kg.subjects(HSTO.isMadeOf, w)]
        entities = []
        if walls:
            rve = kg.value(walls[0], HMO.hasRepresentativeVolumeElement)
            pat = kg.value(rve, HMO.hasPattern)
            for p, kind in ((HMO.hasDominantPatternEntities, "dominant"),
                            (HMO.hasSparsePatternEntities, "sparse")):
                for e in kg.objects(pat, p):
                    if str(e).startswith(NS["hmo"]):
                        entities.append(f"{local(e)} ({kind})")
                    else:
                        lo = kg.value(e, HMO.unitsLengthHasMinimumValue)
                        hi = kg.value(e, HMO.unitsLengthMaximumValue)
                        entities.append(f"unit length {float(lo):g}–{float(hi):g} cm")
        mtypes.append({"Type": label(t), "_id": curie(t),
                       "Description": str(kg.value(t, SKOS.definition) or ""),
                       "Façades": ", ".join(fac), "BIM elements": len(bim_elements),
                       "Pattern entities": sorted(entities),
                       "Flags": [str(c) for c in kg.objects(t, RDFS.comment)]})

    roles = {HSV.acquiredBy: "acquired by", HSV.postProcessedBy: "processed by", HSV.hasAuthor: "author"}
    documents = []
    for d in sorted({s for s, _, o in kg.triples((None, RDF.type, None))
                     if group(s) == "document"}, key=str):
        people = [f"{label(p)} ({r})" for prop, r in roles.items() for p in kg.objects(d, prop)]
        documents.append({
            "Document": label(d), "_id": curie(d),
            "Kind": ", ".join(local(t) for t in types(d)),
            "Date": str(kg.value(d, DCT.created) or ""),
            "Derived from": ", ".join(label(x) for x in kg.objects(d, PROV.wasDerivedFrom)),
            "Produced in": ", ".join(label(x) for x in kg.objects(d, PROV.wasGeneratedBy)),
            "Used in": ", ".join(label(a) for a in kg.subjects(PROV.used, d)),
            "People": people})

    activities = []
    for a in sorted(kg.subjects(RDF.type, PROV.Activity), key=str):
        start, end = kg.value(a, PROV.startedAtTime), kg.value(a, PROV.endedAtTime)
        when = str(kg.value(a, DCT.date) or "")
        if start and end:
            when = f"{when} ({str(start)[11:16]}–{str(end)[11:16]} UTC)"
        activities.append({"Activity": label(a), "_id": curie(a), "Date": when,
                           "People": [label(p) for p in kg.objects(a, PROV.wasAssociatedWith)],
                           "Notes": "; ".join(str(c) for c in kg.objects(a, RDFS.comment))})

    people = []
    for p in sorted(kg.subjects(RDF.type, FOAF.Person), key=lambda x: label(x)):
        org = next(kg.subjects(FOAF.member, p), None)
        roles = [f"{local(t)} (HSV)" for t in sorted(types(p), key=str) if str(t).startswith(NS["hsv"])]
        for assoc in kg.subjects(PROV.agent, p):
            activity = next(kg.subjects(PROV.qualifiedAssociation, assoc), None)
            for role in kg.objects(assoc, PROV.hadRole):
                roles.append(f"{label(role)} ({label(activity)})" if activity else label(role))
        people.append({"Person": label(p), "_id": curie(p),
                       "Organisation": str(kg.value(org, FOAF.name)) if org else "",
                       "Roles": roles,
                       "Activities": [label(a) for a in kg.subjects(PROV.wasAssociatedWith, p)]})

    data = {
        "groups": [{"key": k, "label": l, "visible": v} for k, l, v in GROUPS],
        "nodes": list(nodes.values()), "edges": edges,
        "facades": facades, "types": mtypes, "documents": documents,
        "activities": activities, "people": people,
        "bim": {"glb": "bim/model.glb" if os.path.exists(os.path.join(OUT_DIR, "bim", "model.glb")) else None,
                "types": {label(t): curie(t) for t in kg.subjects(RDF.type, SKOS.Concept)},
                "elements": {str(kg.value(e, DCT.identifier)): curie(e)
                             for e in kg.subjects(DCT.isPartOf, C.BIMModel)}},
        "stats": {"triples": len(kg), "nodes": len(nodes), "edges": len(edges)},
        "note": str(kg.value(C.KnowledgeGraph, RDFS.comment) or ""),
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    template = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "knowledge_graph_page_template.html"), encoding="utf-8").read()
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8", newline="\n") as f:
        f.write(template.replace("/*__DATA__*/null", payload))
    shutil.copyfile(KG, os.path.join(OUT_DIR, "knowledge_graph.ttl"))
    print(f"wrote {OUT_DIR}/index.html: {len(nodes)} nodes, {len(edges)} edges, "
          f"{len(facades)} facades, {len(documents)} documents, {len(images)} photographs with images")


if __name__ == "__main__":
    main()
