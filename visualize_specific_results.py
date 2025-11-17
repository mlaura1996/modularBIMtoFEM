import gmsh, os, glob
from core.config import EXPORT_DIR_PART_2
gmsh.initialize()

# Aprire un .geo che è in un'altra cartella
#COARSE
### GET MESH FILE
file_name = "in_plane.msh"
full_path = os.path.join(EXPORT_DIR_PART_2, file_name)
gmsh.open(full_path)

folders = [
    fr"C:/Users/mlaur/Documents/clean_code/output/Opensees_recorders/2025-11-13_13-54-50/strains_{i}"
    for i in range(18, 25)
]
for folder in folders:
    # se vuoi includere eventuali sottocartelle, usa "**/*.pos" e recursive=True
    pattern = os.path.join(folder, "*.pos")
    for pos_file in sorted(glob.glob(pattern)):
        try:
            print(f"Merge: {pos_file}")
            gmsh.merge(pos_file)  # aggiunge il view senza rimpiazzare il modello
        except Exception as e:
            print(f"Errore nel caricamento di {pos_file}: {e}")

# 1) Tetraedri rossi (colore di rendering degli elementi 3D)
gmsh.option.setColor("Mesh.Color.Hexahedra", 255, 0, 0)

# 1) Tetraedri rossi (per "by type" userà questo colore)
gmsh.option.setColor("Mesh.Color.Tetrahedra", 255, 0, 0)

# 2) Sfondo completamente bianco (niente gradiente)
gmsh.option.setNumber("General.BackgroundGradient", 0)
gmsh.option.setColor("General.Background", 255, 255, 255)

# 3) Colora gli elementi "by type" (0 = by element type)
gmsh.option.setNumber("Mesh.ColorCarousel", 0)


# --- (1) Imposta la colormap di default per TUTTE le viste che caricherai/creerai da ora in poi
gmsh.option.setNumber("View.ColormapNumber", 9)   # colormap #9
gmsh.option.setNumber("View.ColormapSwap", 1)     # inverti l'orientamento (min/max) dei colori
# Se per "colori invertiti" intendi il complemento (x -> 255-x), usa invece:
# gmsh.option.setNumber("View.ColormapInvert", 1)


# --- (2) Applica/forza le stesse opzioni su OGNI vista già esistente
for v in gmsh.view.getTags():
    # forza comunque la mappa 9
    gmsh.view.option.setNumber(v, "ColormapNumber", 9)

    # leggi il nome della vista e controlla 'min' (case-insensitive)
    name = gmsh.view.option.getString(v, "Name")
    if "max" in name.lower():
        gmsh.view.option.setNumber(v, "ColormapSwap", 1)  # inverti min↔max
    else:
        gmsh.view.option.setNumber(v, "ColormapSwap", 0)  # lascia standard

#6) Orientazione camera: usa Euler angles (Trackball off) e imposta X=300, Y=0
gmsh.option.setNumber("General.Trackball", 0)
gmsh.option.setNumber("General.RotationX", 300)
gmsh.option.setNumber("General.RotationY", 0)
# opzionale: azzera anche Z se vuoi una base pulita
gmsh.option.setNumber("General.RotationZ", -200)
gmsh.fltk.run()
gmsh.finalize()


