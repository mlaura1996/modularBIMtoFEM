"""Command line: build a case study, convert it, write the empty workbook.

    python -m core.knowledge_graph build <case> --out <dir> [--bim <bim_elements.json>]
                                         [--site <page dir>] [--photos <photo folder>]
    python -m core.knowledge_graph convert <case> <case.json | case.xlsx>
    python -m core.knowledge_graph template <path.xlsx>
    python -m core.knowledge_graph schema <schema.json>

<case> is a workbook (.xlsx), a case.json, or an IFC file the case-study
editor has written the case study into. build reads it, checks its
cross-references, builds the graph,
runs Pellet (Java and owlready2 0.48 needed), writes knowledge_graph.ttl
and material_database.json to --out, and with --site writes the browsable
page there (with --photos, also the photograph thumbnails). --bim is the
element list written by scripts/export_bim_for_web.py, which links the BIM
model to the masonry types; its glTF model is expected in <site>/bim/.
schema writes the description of the sheets the editor is generated from.
"""
import argparse
import json
import sys

from core.knowledge_graph.workbook import (case_document, editor_schema, read_case, tables_from_records,
                                          validate, write_workbook)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m core.knowledge_graph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template", help="write the empty workbook")
    t.add_argument("path")
    s = sub.add_parser("schema", help="write the sheet description the editor is generated from")
    s.add_argument("path")
    c = sub.add_parser("convert", help="convert a case study between .xlsx, .json (and from .ifc)")
    c.add_argument("source")
    c.add_argument("target")
    b = sub.add_parser("build", help="build the graph of a case study")
    b.add_argument("case", help="workbook (.xlsx), case.json, or IFC file written by the editor")
    b.add_argument("--out", required=True)
    b.add_argument("--bim")
    b.add_argument("--site")
    b.add_argument("--photos")
    a = ap.parse_args(argv)

    if a.cmd == "template":
        write_workbook(a.path)
        print(f"wrote the empty workbook {a.path}")
        return
    if a.cmd == "schema":
        json.dump(editor_schema(), open(a.path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"wrote {a.path}")
        return
    case, classification = read_case(a.source if a.cmd == "convert" else a.case)
    problems = validate(case, classification)
    if problems:
        sys.exit("the case study has references that do not resolve:\n  " + "\n  ".join(problems))
    if a.cmd == "convert":
        if a.target.lower().endswith(".xlsx"):
            write_workbook(a.target, case, classification)
        else:
            json.dump(case_document(tables_from_records(case, classification)),
                      open(a.target, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"wrote {a.target}")
        return
    bim = json.load(open(a.bim, encoding="utf-8"))["elements"] if a.bim else []
    from core.knowledge_graph.builder import run
    run(case, classification, a.out, bim)
    if a.site:
        from core.knowledge_graph.page import build_page
        build_page(f"{a.out}/knowledge_graph.ttl", a.site, photos_dir=a.photos)


if __name__ == "__main__":
    main()
