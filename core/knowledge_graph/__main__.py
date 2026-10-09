"""Command line: write the empty workbook, or build a case study.

    python -m core.knowledge_graph template <path.xlsx>
    python -m core.knowledge_graph build <case.xlsx> --out <dir> [--bim <bim_elements.json>]
                                         [--site <page dir>] [--photos <photo folder>]

build reads the workbook, checks its cross-references, builds the graph,
runs Pellet (Java and owlready2 0.48 needed), writes knowledge_graph.ttl
and material_database.json to --out, and with --site writes the browsable
page there (with --photos, also the photograph thumbnails). --bim is the
element list written by scripts/export_bim_for_web.py, which links the BIM
model to the masonry types; its glTF model is expected in <site>/bim/.
"""
import argparse
import json
import sys

from core.knowledge_graph.workbook import read_workbook, validate, write_workbook


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m core.knowledge_graph")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("template", help="write the empty workbook")
    t.add_argument("path")
    b = sub.add_parser("build", help="build the graph of a case study")
    b.add_argument("workbook")
    b.add_argument("--out", required=True)
    b.add_argument("--bim")
    b.add_argument("--site")
    b.add_argument("--photos")
    a = ap.parse_args(argv)

    if a.cmd == "template":
        write_workbook(a.path)
        print(f"wrote the empty workbook {a.path}")
        return
    case, classification = read_workbook(a.workbook)
    problems = validate(case, classification)
    if problems:
        sys.exit("the workbook has references that do not resolve:\n  " + "\n  ".join(problems))
    bim = json.load(open(a.bim, encoding="utf-8"))["elements"] if a.bim else []
    from core.knowledge_graph.builder import run
    run(case, classification, a.out, bim)
    if a.site:
        from core.knowledge_graph.page import build_page
        build_page(f"{a.out}/knowledge_graph.ttl", a.site, photos_dir=a.photos)


if __name__ == "__main__":
    main()
