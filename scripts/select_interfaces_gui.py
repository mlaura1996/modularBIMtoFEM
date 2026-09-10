"""
Mini GUI for Task A candidate wall-to-wall interface selection: the same
gmsh-rendered, numbered building screenshot as
scripts/plot_candidate_interfaces.py, shown at full resolution
(scrollable + zoomable), next to a scrollable checklist - one YES/NO
checkbox per numbered candidate - so picking which faces become contact
elements is a few clicks against the picture, instead of typing index
ranges blind (scripts/inspect_interfaces.py's terminal prompt) or
re-opening gmsh's own GUI.

Pure stdlib (tkinter) + Pillow (already installed here as a matplotlib
dependency) - no PySide/pyvista/Qt. See docs/source/user_guide/
installation.md for the (considerable) trouble those caused on this
machine - deliberately not repeated here.

Run OUTSIDE Docker, on the local castelnuovo_viewer conda environment:

    conda activate castelnuovo_viewer
    python scripts/select_interfaces_gui.py

What it does:
1. Same candidate detection as plot_candidate_interfaces.py /
   inspect_interfaces.py - full unfiltered volume set, same detection
   order, same MIN_VOLUME_M3 door/window-frame filter - so the numbers
   shown here are identical to both other tools.
2. Renders a gmsh screenshot per state (wireframe walls, red highlighted
   candidates, numbered text labels + leader arrows, 2400x1800) - three
   nearby camera angles are available (VIEWS), switched on demand, so a
   candidate that's foreshortened or buried in a dense corner cluster in
   one view is usually still readable in another. Only the default view is
   rendered up front; the other two render on first switch (see "Speed").
   Non-wall volumes (door/window frames etc., under MIN_VOLUME_M3) are
   hidden outright rather than just left uncolored, for a visibly lighter
   scene - neither side of any candidate is ever one of them, so nothing
   relevant disappears. Keeps gmsh's model open for the whole app run
   instead of reloading it per action - see "Speed" below.
3. Opens a tkinter window: picture on the left (buttons to switch between
   the three views, mouse-wheel to pan, ctrl+wheel or +/- to zoom), a
   scrollable checklist on the right - one
   row per numbered candidate (IF_### area=... vol A-B), all pre-checked
   to match inspect_interfaces.py's default (vertical_joint, both volumes
   >= MIN_VOLUME_M3 - i.e. exactly what's drawn). Untick what you don't
   want.
4. "Save && preview selection" writes resources/survey_data/castelnuovo/
   interface_selection.json in the exact format InterfaceSelection.save()
   / .load_selected() expect (so the Docker-based analysis scripts pick it
   up unchanged via InterfaceSelection.select_interactive_or_cached()),
   THEN re-renders the same building showing ONLY the selected interfaces
   and opens it in a second window to confirm before you close the app.

Speed (user feedback: "un po lento", then "é super lento"): timed each
phase in isolation - load_step ~5s, fragment ~9s, gmsh.fltk.initialize()
(headless render setup, independent of scene complexity) ~11s, a single
gmsh.write() screenshot ~0.5-1s. Follows from that:
  - fragment() is cached to disk after the first run (see
    load_or_build_geometry() below) - a .brep re-import of already-
    fragmented geometry took 0.3s in testing vs. 14s for STEP-load +
    fragment, and produces the identical shared-boundary topology
    InterfaceDetection needs (verified: same 279 volumes / 885 candidates
    from the cache as from a fresh fragment). Invalidated automatically if
    the source STEP file changes.
  - gmsh is initialized ONCE per app run and kept alive for the whole
    tkinter session (one long `with apeGmsh(...)` wrapping the mainloop,
    not one per render).
  - Views render LAZILY, one at a time, cached per (selection, view) -
    ImageViewer.reset()'s loader callback (see BuildingRenderer.render_view)
    - opening the app or clicking "Save && preview" used to render all
      three views immediately; now it renders only the one being shown,
      and the other two only if you actually switch to them.
  - Non-wall volumes are hidden (not just left uncolored) - see point 2 -
    less geometry for gmsh to draw on every screenshot.
"""
import math
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tkinter as tk
from tkinter import ttk, messagebox

import gmsh
from apeGmsh import apeGmsh
from PIL import Image, ImageTk

from core.mesh_generation.wall_interfaces import InterfaceDetection, InterfaceSelection

STEP_PATH = "resources/ifc_examples/castelnuovo/example_clean_PRONTO.stp"
OUT_DIR = "output/castelnuovo/plots"
CACHE_DIR = "output/castelnuovo/cache"
CACHE_BREP = os.path.join(CACHE_DIR, "castelnuovo_fragmented.brep")
SELECTION_PATH = "resources/survey_data/castelnuovo/interface_selection.json"
PLOT_ORIENTATIONS = ("vertical_joint",)
MIN_VOLUME_M3 = 0.3  # matches plot_candidate_interfaces.py / inspect_interfaces.py
FONT_SIZE = 20
# Camera angles (degrees) rendered for every picture - user feedback:
# rather than pick one, show all three side by side (a switch button per
# view) so a candidate hidden/foreshortened in one angle is still visible
# in another. First one (VIEW_1) is the default shown on open.
VIEWS = [
    ("Vista 1", -35, 0, -35),   # original angle
    ("Vista 2", -25, 0, -35),   # less steep tilt
    ("Vista 3", -25, 0, -25),   # more frontal - most legible of the three so far
]
VIEW_ANGLES = {name: (rx, ry, rz) for name, rx, ry, rz in VIEWS}
VIEW_NAMES = [name for name, *_ in VIEWS]
DEFAULT_VIEW = "Vista 3"
LEADER_ARROW_SIZE = 36  # pixels - tuned against a 2400x1800 render; too small got lost in clutter
GOLDEN_ANGLE = 2.399963229728653  # radians - spreads a spiral evenly, no two steps overlap


def load_or_build_geometry(g):
    """g: the live apeGmsh instance. Loads from cache if valid, otherwise
    loads the STEP file + fragments through apeGmsh and writes the cache
    for next time. Returns the list of (dim, tag) volume entities.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    use_cache = (os.path.isfile(CACHE_BREP)
                 and os.path.getmtime(CACHE_BREP) > os.path.getmtime(STEP_PATH))
    t0 = time.perf_counter()
    if use_cache:
        print(f"Loading cached fragmented geometry ({CACHE_BREP}) ...", flush=True)
        gmsh.model.occ.importShapes(CACHE_BREP)
        gmsh.model.occ.synchronize()
    else:
        print("No (valid) geometry cache - loading STEP and fragmenting "
              "(one-time cost, ~15-25s; cached afterwards for next run) ...", flush=True)
        g.model.io.load_step(STEP_PATH)
        gmsh.model.occ.fragment(gmsh.model.occ.getEntities(3), [])
        gmsh.model.occ.synchronize()
        gmsh.write(CACHE_BREP)
    print(f"Geometry ready in {time.perf_counter() - t0:.1f}s.", flush=True)
    return gmsh.model.getEntities(3)


def declutter_positions(numbered, cluster_radius=0.6, base_offset=0.45, growth=0.45):
    """Nudges label ANCHOR points apart (never the highlighted surfaces
    themselves) when several candidates' true 3D centroids fall within
    `cluster_radius` of one another - e.g. multiple small patches from an
    L-shaped wall junction (see InterfaceSelection.key_for's docstring: 144
    of Castelnuovo's candidates are volume pairs that touch at more than
    one separate spot) - so their number labels don't render exactly on
    top of each other (user feedback: "alcuni numeri sono uno sopra
    l'altro"). Each label after the first in a cluster is pushed out along
    a widening golden-angle spiral around its own true centroid.

    Not a true screen-space anti-collision pass (that would need
    replicating gmsh's camera projection) - a 3D-domain approximation:
    good enough to separate near-coincident centroids in most views
    without risking a much larger, camera-matching rewrite this close to
    the deadline.

    Returns {candidate_number: (x, y, z)} label anchors.
    """
    placed = []  # true centroids already processed, for the proximity count
    positions = {}
    for i, c in numbered:
        cx, cy, cz = c["centroid"]
        k = sum(1 for (px, py, pz) in placed
                if math.dist((px, py, pz), (cx, cy, cz)) < cluster_radius)
        if k == 0:
            positions[i] = (cx, cy, cz)
        else:
            angle = k * GOLDEN_ANGLE
            r = base_offset + growth * k  # grows with cluster size, not just a fixed nudge -
            # dense corner clusters (10+ candidates within ~1m, common at an L-shaped wall
            # junction) need real separation, not a small constant offset, to read at all at
            # whole-building scale; still labeled/keyed by area+volume pair in the checklist,
            # so a label drifting a bit from its exact surface doesn't create ambiguity.
            positions[i] = (cx + r * math.cos(angle), cy + r * math.sin(angle), cz + 0.25 * k)
        placed.append((cx, cy, cz))
    return positions


class BuildingRenderer:
    """Wraps the already-loaded, already-fragmented gmsh model kept alive
    for the whole app run (see module docstring's "Speed" section) and
    re-renders it on demand - recoloring + relabeling only whichever
    candidates are passed in.

    Two speed/weight choices made directly from user feedback ("super
    lento" + "geometria meno pesante"):
      - Small, non-wall volumes (door/window frames, anything under
        MIN_VOLUME_M3 - never a candidate's own volume, both sides of
        every candidate are already restricted to the big ones) are hidden
        outright, not just left uncolored - fewer edges for gmsh to draw,
        less visual clutter, and it's geometry that was never relevant to
        a contact interface anyway.
      - render_view() renders ONE view at a time instead of all of VIEWS
        at once, and ensure_state() only re-applies coloring/labels when
        the requested candidate set actually changed - see ImageViewer's
        lazy per-view loading: switching views or opening the app now
        costs one gmsh.write() (~0.5-1s), not three.

    First render_view() call still pays gmsh.fltk.initialize()'s ~11s
    (paid once, in __init__); every render_view() call after that costs
    well under a second.
    """

    def __init__(self, all_vols, big_vol_tags):
        self.all_vols = all_vols
        self.big_vol_tags = big_vol_tags
        self.label_view_tag = None
        self.leader_view_tag = None
        self._state_key = None
        gmsh.option.setNumber("Print.Width", 2400)
        gmsh.option.setNumber("Print.Height", 1800)
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("Geometry.Surfaces", 1)
        gmsh.option.setNumber("Geometry.SurfaceType", 0)  # wireframe - see plot_candidate_interfaces.py
        gmsh.option.setNumber("Geometry.LineWidth", 2)
        gmsh.option.setNumber("General.Trackball", 0)
        for _d, t in all_vols:
            gmsh.model.setVisibility([(3, t)], 1 if t in big_vol_tags else 0, recursive=True)
        # gmsh.fltk.initialize() needs a real native window to create its
        # OpenGL context - this build has no true windowless/offscreen mode
        # (gmsh.write() then just captures that window's content, it
        # doesn't render without one). User feedback: "si apre sempre
        # gmsh" - since we never call gmsh.fltk.run(), that window is never
        # interactive/blocking, but it WAS still visibly popping up and
        # staying open the whole session (kept alive for speed - see the
        # "Speed" section above). Moving it off-screen and shrinking it
        # before creation is the standard trick for this: it still exists
        # as a real OS window, but nowhere you'd ever see it.
        gmsh.option.setNumber("General.GraphicsPositionX", -32000)
        gmsh.option.setNumber("General.GraphicsPositionY", -32000)
        gmsh.option.setNumber("General.GraphicsWidth", 50)
        gmsh.option.setNumber("General.GraphicsHeight", 50)
        gmsh.fltk.initialize()

    def _apply_state(self, numbered):
        """Recolors + rebuilds the number labels and their leader arrows for
        `numbered` - everything here is independent of camera angle, so
        it's only redone when the candidate set actually changes (see
        ensure_state), not once per view.
        """
        for _d, t in self.all_vols:
            gmsh.model.setColor([(3, t)], 200, 200, 210, 255, recursive=True)
        for _i, c in numbered:
            gmsh.model.setColor([(2, c["surface"])], 255, 0, 0, 255, recursive=True)

        if self.label_view_tag is not None:
            gmsh.view.remove(self.label_view_tag)
        if self.leader_view_tag is not None:
            gmsh.view.remove(self.leader_view_tag)
            self.leader_view_tag = None

        label_view = gmsh.view.add("candidate_numbers")
        self.label_view_tag = label_view
        positions = declutter_positions(numbered)
        leader_data = []
        for i, c in numbered:
            gmsh.view.addListDataString(label_view, list(positions[i]), [str(i)],
                                         ["Font", "Helvetica-Bold", "FontSize", str(FONT_SIZE),
                                          "Align", "Center"])
            lx, ly, lz = positions[i]
            cx, cy, cz = c["centroid"]
            if (lx, ly, lz) != (cx, cy, cz):
                # Leader arrow FROM the (offset) label back TO the true
                # surface - user feedback: "rifare i label ... tipo con
                # una freccia". Only for labels declutter_positions()
                # actually moved - a label still sitting on its true
                # centroid doesn't need one.
                leader_data.extend([lx, ly, lz, cx - lx, cy - ly, cz - lz])
        view_idx = gmsh.view.getIndex(label_view)
        gmsh.option.setNumber(f"View[{view_idx}].Visible", 1)
        gmsh.option.setNumber(f"View[{view_idx}].ShowScale", 0)

        if leader_data:
            leader_view = gmsh.view.add("candidate_leaders")
            self.leader_view_tag = leader_view
            gmsh.view.addListData(leader_view, "VP", len(leader_data) // 6, leader_data)
            l_idx = gmsh.view.getIndex(leader_view)
            gmsh.option.setNumber(f"View[{l_idx}].Visible", 1)
            gmsh.option.setNumber(f"View[{l_idx}].ShowScale", 0)
            gmsh.option.setNumber(f"View[{l_idx}].ArrowSizeMax", LEADER_ARROW_SIZE)
            gmsh.option.setNumber(f"View[{l_idx}].LineWidth", 3)

    def ensure_state(self, numbered):
        """Applies `numbered`'s coloring/labels only if it differs from
        whatever is currently applied - candidate numbers are a stable,
        unique key for a given detection run, so comparing them is enough.
        """
        key = tuple(i for i, _c in numbered)
        if key != self._state_key:
            self._apply_state(numbered)
            self._state_key = key

    def render_view(self, numbered, view_name, base_path):
        """Renders exactly one camera angle (view_name, from VIEWS) of
        `numbered`'s current state to base_path + "_<view_name>.png" and
        returns that path. Safe to call for any (numbered, view_name)
        combination at any time - ensure_state() re-applies coloring only
        when actually needed, so interleaving calls for two different
        selections (e.g. the main picker and a "confirm selection" popup
        sharing this one live gmsh session) always renders the right one.

        Real gmsh quirk, found by testing (reproduced with NO Tkinter
        involved at all, and present even in plot_candidate_interfaces.py's
        old two-write loop - it just went unnoticed since 1924x1061 still
        looked fine): only the FIRST gmsh.write() after gmsh.fltk.
        initialize() honors Print.Width/Height; every later write() in the
        same session silently drops to some other (screen-derived) size,
        no matter how many times Print.Width/Height are re-set in between.
        The fix that actually worked in testing: a genuine
        finalize()+initialize() cycle before every write - confirmed
        4/4 renders at the correct 2400x1800 across repeated calls, at
        ~0.7-1s each here (window is tiny/off-screen - see __init__ - so
        this isn't the ~11s a full first-ever initialize() costs).
        """
        gmsh.fltk.finalize()
        gmsh.fltk.initialize()
        self.ensure_state(numbered)
        gmsh.option.setNumber("Print.Width", 2400)
        gmsh.option.setNumber("Print.Height", 1800)
        rx, ry, rz = VIEW_ANGLES[view_name]
        gmsh.option.setNumber("General.RotationX", rx)
        gmsh.option.setNumber("General.RotationY", ry)
        gmsh.option.setNumber("General.RotationZ", rz)
        path = f"{base_path}_{view_name.replace(' ', '_')}.png"
        gmsh.write(path)
        return path


class ImageViewer(ttk.Frame):
    """Scrollable, zoomable image display - the picture pane, factored out
    so the main window and the post-save "confirm your selection" popup
    can both use it. Shows one of several named views (VIEWS - different
    camera angles of the same render) with a row of switch buttons, so a
    candidate that's foreshortened or buried in a cluster in one angle can
    still be checked against another without re-running anything."""

    def __init__(self, parent, view_names, loader, caption="", start_zoom=0.6, default_view=None):
        super().__init__(parent)
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.caption = caption
        self.zoom = start_zoom

        self.canvas = tk.Canvas(self, bg="#dddddd")
        hbar = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Control-MouseWheel>",
                          lambda e: self._zoom(1.1 if e.delta > 0 else 1 / 1.1))
        self.canvas.bind("<Button-4>", lambda e: self._zoom(1.1))
        self.canvas.bind("<Button-5>", lambda e: self._zoom(1 / 1.1))

        self.view_bar = ttk.Frame(self)
        self.view_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.view_label = ttk.Label(self.view_bar, text="")
        self.view_label.pack(side="left", padx=6)
        ttk.Button(self.view_bar, text="-", width=3, command=lambda: self._zoom(1 / 1.25)).pack(side="right")
        ttk.Button(self.view_bar, text="+", width=3, command=lambda: self._zoom(1.25)).pack(side="right")
        self.view_buttons_frame = ttk.Frame(self.view_bar)
        self.view_buttons_frame.pack(side="left", padx=6)

        self.reset(view_names, loader, default_view)

    def reset(self, view_names, loader, default_view=None):
        """view_names: the switchable views, in order. loader(view_name) ->
        image path, called (and its result cached) only the first time a
        given view is actually shown - user feedback: "super lento" -
        rendering all views up front was real, avoidable work when most of
        the time only one or two get looked at. Call this (instead of
        building a new ImageViewer) whenever the underlying render STATE
        changes, e.g. after "Save && preview" - a fresh loader means a
        fresh cache, so switching views re-renders under the new state
        instead of showing a stale image from before. Plain view-switching
        (same state, different camera angle) should use _switch_view
        instead - it keeps the cache, so flipping back to an
        already-rendered view is instant rather than re-rendering it.
        """
        self.view_names = list(view_names)
        self.loader = loader
        self._cache = {}  # view_name -> already-rendered path, this state only
        keep = default_view or getattr(self, "current_view", None)
        self.current_view = keep if keep in self.view_names else self.view_names[0]
        self._rebuild_view_buttons()
        self._load_current()

    def _switch_view(self, name):
        """Change which already-configured view is shown, keeping the
        render cache - switching back to a view seen earlier in this same
        selection state doesn't re-render it."""
        self.current_view = name
        self._rebuild_view_buttons()
        self._load_current()

    def _rebuild_view_buttons(self):
        for w in self.view_buttons_frame.winfo_children():
            w.destroy()
        if len(self.view_names) > 1:
            ttk.Label(self.view_buttons_frame, text="Vista:").pack(side="left")
            for name in self.view_names:
                text = f"[{name}]" if name == self.current_view else name
                b = ttk.Button(self.view_buttons_frame, text=text,
                                command=lambda n=name: self._switch_view(n))
                b.pack(side="left", padx=2)

    def _load_current(self):
        name = self.current_view
        if name not in self._cache:
            self.view_label.configure(text=f"Rendering '{name}' ...")
            self.update_idletasks()  # show that message before the (blocking) render below
            self._cache[name] = self.loader(name)
        path = self._cache[name]
        img = Image.open(path)
        if img.mode == "RGBA":
            # gmsh writes these with a fully transparent background
            # (alpha=0), not opaque white - flatten it onto white so the
            # canvas (and any tool that saves/re-displays this image)
            # shows the same thing regardless of transparency handling.
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.split()[3])
            img = flat
        self.pil_image = img
        text = f"{name}  -  {os.path.basename(path)}   (wheel = pan, ctrl+wheel or +/- = zoom)"
        if self.caption:
            text = f"{self.caption}   |   {text}"
        self.view_label.configure(text=text)
        self._render()

    def _render(self):
        w, h = self.pil_image.size
        disp = self.pil_image.resize((max(1, int(w * self.zoom)), max(1, int(h * self.zoom))),
                                      Image.Resampling.LANCZOS)
        self.tk_image = ImageTk.PhotoImage(disp)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.tk_image)
        self.canvas.configure(scrollregion=(0, 0, disp.width, disp.height))

    def _zoom(self, factor):
        self.zoom = max(0.1, min(3.0, self.zoom * factor))
        self._render()

    def _on_wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


class InterfacePickerApp:
    def __init__(self, root, renderer, candidates, numbered, out_dir):
        self.root = root
        self.renderer = renderer
        self.candidates = candidates
        self.numbered = numbered  # list of (index, candidate)
        self.out_dir = out_dir
        self.vars = {i: tk.BooleanVar(value=True) for i, _c in numbered}
        self.preview_window = None  # one reusable popup, not one per click - see _save_and_preview
        self.preview_viewer = None

        root.title(f"Task A - select wall-to-wall contact interfaces "
                   f"({len(numbered)} candidates)")
        root.geometry("1400x900")

        main = ttk.Frame(root)
        main.pack(fill="both", expand=True)

        main_base = os.path.join(out_dir, "candidate_interfaces_gui")
        self.image_viewer = ImageViewer(
            main, VIEW_NAMES,
            loader=lambda name: self.renderer.render_view(self.numbered, name, main_base),
            default_view=DEFAULT_VIEW)
        self.image_viewer.pack(side="left", fill="both", expand=True)

        side = ttk.Frame(main, width=380)
        side.pack(side="right", fill="y")
        side.pack_propagate(False)

        ttk.Label(side, text="Candidate interfaces (numbers match the picture) - "
                              "tick = export as contact interface",
                  wraplength=360, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=8, pady=(8, 4))

        btn_row = ttk.Frame(side)
        btn_row.pack(fill="x", padx=8, pady=(0, 4))
        ttk.Button(btn_row, text="Select all", command=self._select_all).pack(side="left")
        ttk.Button(btn_row, text="Deselect all", command=self._deselect_all).pack(side="left", padx=6)

        list_container = ttk.Frame(side)
        list_container.pack(fill="both", expand=True, padx=8)
        list_canvas = tk.Canvas(list_container, highlightthickness=0)
        list_scroll = ttk.Scrollbar(list_container, orient="vertical", command=list_canvas.yview)
        list_canvas.configure(yscrollcommand=list_scroll.set)
        list_canvas.pack(side="left", fill="both", expand=True)
        list_scroll.pack(side="right", fill="y")

        checklist = ttk.Frame(list_canvas)
        list_canvas.create_window((0, 0), window=checklist, anchor="nw")
        checklist.bind("<Configure>",
                        lambda e: list_canvas.configure(scrollregion=list_canvas.bbox("all")))
        list_canvas.bind("<MouseWheel>",
                          lambda e: list_canvas.yview_scroll(int(-e.delta / 120), "units"))

        for i, c in numbered:
            label = f"IF_{i:03d}   area={c['area_m2']:.2f} m2   vol {c['volume_a']}-{c['volume_b']}"
            ttk.Checkbutton(checklist, text=label, variable=self.vars[i]).pack(anchor="w", pady=1)

        ttk.Separator(side, orient="horizontal").pack(fill="x", padx=8, pady=8)
        self.status = ttk.Label(side, text="", wraplength=360)
        self.status.pack(anchor="w", padx=8)
        ttk.Button(side, text="Save && preview selection", command=self._save_and_preview).pack(
            fill="x", padx=8, pady=8)

    def _select_all(self):
        for v in self.vars.values():
            v.set(True)

    def _deselect_all(self):
        for v in self.vars.values():
            v.set(False)

    def _save_and_preview(self):
        selected_pairs = [(i, c) for i, c in self.numbered if self.vars[i].get()]
        selected = [c for _i, c in selected_pairs]

        # Anything past this point (re-rendering through gmsh, triggered
        # lazily inside the ImageViewer below) is where a real error could
        # happen - caught here instead of crashing the whole app silently,
        # so you can go back to the checklist and keep working, and so the
        # actual traceback ends up somewhere you can copy from (the
        # terminal you launched the script from) instead of just the
        # window disappearing.
        try:
            InterfaceSelection.save(self.candidates, selected, SELECTION_PATH)
            msg = f"Saved {len(selected)}/{len(self.numbered)} selected interface(s) to {SELECTION_PATH}."
            self.status.configure(text=msg)

            if not selected_pairs:
                self.status.configure(text=msg + " (0 selected - nothing to preview.)")
                return

            confirm_base = os.path.join(self.out_dir, "candidate_interfaces_selected_confirm")
            loader = lambda name, sp=selected_pairs: self.renderer.render_view(sp, name, confirm_base)

            # Reuse the SAME popup across multiple "Save && preview" clicks
            # instead of stacking a new window every time - both to keep
            # the workflow ("adjust checklist -> preview again") from
            # cluttering the screen, and because it's the natural "go
            # back" path: this popup is never modal, the main checklist
            # window stays fully usable behind/underneath it the whole
            # time. reset() (not a new ImageViewer) also clears its
            # per-view render cache, so switching views re-renders under
            # THIS selection instead of showing a stale one from before.
            if self.preview_window is None or not self.preview_window.winfo_exists():
                self.preview_window = tk.Toplevel(self.root)
                self.preview_window.geometry("1100x800")
                self.preview_viewer = ImageViewer(
                    self.preview_window, VIEW_NAMES, loader, default_view=DEFAULT_VIEW,
                    caption=f"{len(selected_pairs)} selected interface(s), same numbering")
                self.preview_viewer.pack(fill="both", expand=True)
                ttk.Button(self.preview_window, text="Chiudi anteprima e torna alla selezione",
                           command=self.preview_window.destroy).pack(pady=6)
            else:
                self.preview_viewer.reset(VIEW_NAMES, loader, default_view=DEFAULT_VIEW)
                self.preview_window.lift()
            self.preview_window.title(f"Confirm selection - {len(selected_pairs)} interface(s)")
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror(
                "Errore durante il salvataggio/anteprima",
                f"{exc}\n\nLa selezione nella finestra principale non e' stata persa - "
                "puoi correggerla e riprovare. Il traceback completo e' stampato nel "
                "terminale da cui hai lanciato lo script.",
            )


if __name__ == "__main__":
    print("Starting - loading geometry (cached after the first run) and detecting "
          "candidates...", flush=True)
    with apeGmsh(model_name="select_interfaces_gui") as g:
        all_vols = load_or_build_geometry(g)

        big_vol_tags = {t for _d, t in all_vols if gmsh.model.occ.getMass(3, t) >= MIN_VOLUME_M3}
        candidates = InterfaceDetection.find_touching_surface_pairs()
        InterfaceDetection.classify_orientation(candidates)
        numbered = [(i, c) for i, c in enumerate(candidates, start=1)
                    if c["orientation"] in PLOT_ORIENTATIONS
                    and c["volume_a"] in big_vol_tags and c["volume_b"] in big_vol_tags]
        print(f"{len(candidates)} candidates total, {len(numbered)} shown/selectable "
              f"(orientation in {PLOT_ORIENTATIONS}, both volumes >= {MIN_VOLUME_M3} m^3).",
              flush=True)

        os.makedirs(OUT_DIR, exist_ok=True)
        renderer = BuildingRenderer(all_vols, big_vol_tags)
        print(f"{len(big_vol_tags)}/{len(all_vols)} volumes kept visible (>= {MIN_VOLUME_M3} m^3 - "
              "everything smaller, e.g. door/window frames, is hidden to keep the render light).",
              flush=True)
        print(f"Opening the picker window (renders '{DEFAULT_VIEW}' now; the other views render "
              "on first switch, not up front).", flush=True)

        root = tk.Tk()
        app = InterfacePickerApp(root, renderer, candidates, numbered, OUT_DIR)
        root.mainloop()
