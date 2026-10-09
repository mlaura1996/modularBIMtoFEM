"""One-off: writes the Castelnuovo records as a case-study workbook.

    python scripts/migrate_castelnuovo_to_workbook.py

Reads the records the Castelnuovo graph was first built from
(survey_record.json and masonry_classification.json) and writes
resources/survey_data/castelnuovo/case.xlsx in the format of
core/knowledge_graph/workbook.py, keeping every identifier, so that the
graph built from the workbook has the same IRIs. Kept as the record of how
the workbook was obtained; from now on the workbook is the source.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.knowledge_graph.workbook import write_workbook, read_workbook, validate

SRC = "resources/survey_data/castelnuovo"
OUT = os.path.join(SRC, "case.xlsx")


def main():
    r = json.load(open(os.path.join(SRC, "survey_record.json"), encoding="utf-8"))
    cls = json.load(open(os.path.join(SRC, "masonry_classification.json"), encoding="utf-8"))
    case = {
        "project": {
            "id": "castelnuovo",
            "title": "Castelnuovo di Porto knowledge graph",
            "description": "The masonry aggregate of Castelnuovo di Porto described with the Historic Survey (HSV), "
                           "Historic Structure (HSTO) and Historic Masonry (HMO) ontologies: the survey and its "
                           "documents, the façades and their walls, and the mechanical properties of the masonry "
                           "derived by a reasoner from the observed construction features.",
            "namespace": "https://example.org/castelnuovo#",
            "centre_id": "CastelnuovoDiPorto", "centre_label": "Historic centre of Castelnuovo di Porto",
            "aggregate_id": "Aggregate", "aggregate_label": "Aggregate between Piazza Garibaldi and Via Umberto I",
            "technique_id": "MuraturaATufelli", "technique_label": "Muratura a tufelli",
            "bim_document": "BIMModel", "software_doi": "10.5281/zenodo.23260962"},
        "organisations": r["organisations"],
        "people": r["people"],
        "activities": {}, "documents": {}, "units": {}, "facades": {}, "photos": {},
        "connections": {}, "openings": {}, "measured": []}
    for aid, a in r["activities"].items():
        x = {k: a[k] for k in ("label", "people", "date", "start", "end", "roles") if k in a}
        if "instrument" in a:
            x["notes"] = f"Instrument: {a['instrument']}"
        case["activities"][aid] = x
    rename = {"created": "date", "used_by": "used_in", "post_processed_by": "processed_by"}
    for did, d in r["documents"].items():
        case["documents"][did] = {rename.get(k, k): v for k, v in d.items()}
    for u in sorted({f["unit"] for f in r["facades"].values()}):
        case["units"][f"Unit_{u}"] = {
            "label": f"Structural unit {u} (cadastral identifier)",
            "floor": {"kind": "TimberFloor", "label": f"Timber floors of unit {u}", "accessible": False,
                      "note": "Generic: timber floors alla romana documented for the aggregate as a whole; "
                              "the interiors of the case-study units could not be inspected."}}
    for fid, f in r["facades"].items():
        k = fid.replace("Facade_", "")
        case["facades"][fid] = {"unit": f"Unit_{f['unit']}", "label": f"Facade {k} of unit {f['unit']}",
                                "masonry_type": f["masonry_type"]}
        for i, ph in enumerate(f["photos"], 1):
            case["photos"][f"Photo_{k}_{i:02d}"] = {"facade": fid, "file": ph["file"], "taken": ph["taken"] or "",
                                                    "activity": "PhotographicCampaign", "acquired_by": []}
    case["openings"]["Opening_419"] = {"facade": "Facade_419",
                                       "label": "Doorway with an arch of dressed tuff voussoirs, facade 419"}
    write_workbook(OUT, case, cls)
    back, back_cls = read_workbook(OUT)
    problems = validate(back, back_cls)
    print(f"wrote {OUT}: {len(back['facades'])} facades, {len(back['photos'])} photos, "
          f"{len(back_cls['types'])} masonry types; problems: {problems or 'none'}")


if __name__ == "__main__":
    main()
