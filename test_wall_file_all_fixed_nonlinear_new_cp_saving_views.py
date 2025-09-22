from openseespy.opensees import *
import os

from external.gmsh2opensees import *
from core.config import  EXPORT_DIR_PART_1, EXPORT_DIR_PART_2, EXPORT_DIR_PART_3, gmsh, math, OUTPUT_DIR, LOG_DIR, plt, csv, pd, np
import datetime

from core.mesh_generation.mesh import Mesh
from core.opensees_generation.model_builder import Element

#UTILS
from utils.dict_helper import load_material_objects
from utils.analysis_helper import check_sign_flips, PeakViews
from utils.plot_helper import LiveDVPlot
from utils.modelbuilder_helper import get_wall_cp

material_file_path = os.path.join(EXPORT_DIR_PART_1, "CT02_equ_sec_divided.json")
materials = load_material_objects(material_file_path)
for material in materials:
    print(material)



#Recorders
recorders_path = os.path.join(OUTPUT_DIR, "Opensees_recorders")
os.makedirs(recorders_path, exist_ok=True)
# Create a timestamped subfolder, e.g. "2025-07-22_15-30-05"
now = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
recorders_path = os.path.join(recorders_path, now)
os.makedirs(recorders_path, exist_ok=True)
strain_path = os.path.join(recorders_path, "Strains")
os.makedirs(strain_path, exist_ok=True)
stress_path = os.path.join(recorders_path, "Stresses")
os.makedirs(stress_path, exist_ok=True)
displacements_path = os.path.join(recorders_path, "Displacement")
os.makedirs(displacements_path, exist_ok=True)



### GET MESH FILE
file_name = "_entire_model_divided.msh"
full_path = os.path.join(EXPORT_DIR_PART_2, file_name)

# Check if it's a file (not a subdirectory)
if os.path.isfile(full_path):
    print(f"📂 Found file: {file_name}")

### INITIALISE GMSH
gmsh.initialize()

### OPEN GMSH FILE
gmsh.open(full_path)

gmsh.fltk.run()

### INITALISE OPENSEES MODEL
wipe()
loadConst('-time', 0.0)
model('basic', '-ndm', 3, '-ndf', 3)
element_tags = Element.add_elements_to_opensees(gmsh.model, materials)


# Control nodes upper load
element_tags_load, node_tags_load, elementName2, elementNnodes2 = get_elements_and_nodes_in_physical_group("Load", gmsh.model)
# Flattening and cleaning
flat_nodes = [node for tri in node_tags_load for node in tri]
unique_nodes = list(set(flat_nodes))  # rimuove duplicati

# Control nodes upper load
element_tags_steel, node_tags_steel, _, _ = get_elements_and_nodes_in_physical_group("Steel", gmsh.model)

cp = get_wall_cp(node_tags_steel, gmsh.model)
print("Control points:", cp)

coord, _, _, _ = gmsh.model.mesh.getNode(cp)

# Aggiungi un punto grafico in una nuova view
view = gmsh.view.add(f"SelectedNode_{cp}")
gmsh.view.addListData(view, "SP", 1, [coord[0], coord[1], coord[2], 1.0])  # "SP" = Scalar Point

# gmsh.fltk.run()

#Fixing bottom nodes
element_tags_fix, node_tags_fix, elementName2, elementNnodes2 = get_elements_and_nodes_in_physical_group("Fix", gmsh.model)
flat_nodes_fix = [node for tri in node_tags_fix for node in tri]
unique_nodes_fix = list(set(flat_nodes_fix))  # rimuove duplicati
fix_nodes(node_tags_fix, "XYZ")

#self weight recorder
node_order = sorted(int(n) for n in unique_nodes_fix)
reaction_file_name = 'SW_react.out'
reaction_file = os.path.join(displacements_path, reaction_file_name)
displacament_file_name = 'SW_disp.out'
displacement_file = os.path.join(displacements_path, displacament_file_name)
h_reaction_file_name = 'SW_h_react.out'
h_reaction_file = os.path.join(displacements_path, h_reaction_file_name)
recorder('Node', '-file', displacement_file, '-time', '-node', cp, '-dof', 3, 'disp')
recorder("Node", "-file", reaction_file, "-time", "-node", *node_order, "-dof", 3,  "reaction")

print("analisi iniziata")

timeSeries('Linear', 1)
pattern('Plain', 1, 1)

eleLoad("-ele", *element_tags, "-type", "-selfWeight", 0, 0, 1)

# --- analysis ---
system('Umfpack')
constraints('Transformation')
numberer('RCM')
test('NormDispIncr', 1e-5, 100)
algorithm('Linear')

integrator('LoadControl', 1)  # ogni passo aggiunge 1/Ngrav del carico
analysis('Static')

# # Path completo del CSV
csv_rec_file = os.path.join(recorders_path, "results_SW.csv")

state = analyze(1)
if state == 0:  
    reactions()
    disp = nodeDisp(cp, 3) 
    sumRz = sum(nodeReaction(n,3) for n in unique_nodes_fix)
    sumRz = sumRz*0.001
    with open(csv_rec_file, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([disp, sumRz])

report = check_sign_flips(reaction_file, node_order, tol=1e-6)

visualize_displacements_in_gmsh(
    gmshmodel=gmsh.model, nodeTags=getNodeTags(),
    new_view_name="Displacement View"# ✅ Save to file
)

displacement_pos_file = os.path.join(displacements_path, "SW_disp.pos")
gmsh.write(displacement_pos_file)

#gmsh.fltk.run()
print("analisi SW finita")

loadConst('-time', 0.0)
remove("loadPattern", 1)

# ##### precom
master_node_top = cp

# Usa un set per evitare duplicati
slave_nodes = set([n for tri in node_tags_steel for n in tri])

element_tags_steel_bottom, node_tags_steel_bottom, _, _ = get_elements_and_nodes_in_physical_group("LowSection", gmsh.model)

slave_nodes.update([n for tri in node_tags_steel_bottom for n in tri])  # aggiunge senza duplicati

# Se ti serve come lista
slave_nodes = list(slave_nodes)




timeSeries('Linear', 2)
pattern('Plain', 2, 2)

for n in unique_nodes:
    #load(n, 0.0, 0.0, -400000/len(unique_nodes))
    load(n, 0.0, 0.0, -160000/len(unique_nodes))
    #load(n, 0.0, 0.0, -80000/len(unique_nodes))


system('UmfPack')
constraints('Transformation')
numberer('RCM')
test('NormDispIncr', 1.0e-2, 20)
#algorithm('Newton')
algorithm('Linear')
integrator('LoadControl', 1)
analysis('Static')

# Path completo del CSV
csv_rec_file = os.path.join(recorders_path, "results_PreCompr.csv")

state = analyze(1)
if state == 0:  
    reactions()
    disp = nodeDisp(master_node_top, 3) 
    sumRz = sum(nodeReaction(n,3) for n in unique_nodes_fix)
    sumRz = sumRz*0.001
    with open(csv_rec_file, 'a', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([disp, sumRz])

report = check_sign_flips(reaction_file, node_order, tol=1e-6)

visualize_displacements_in_gmsh(
    gmshmodel=gmsh.model, nodeTags=getNodeTags(),
    new_view_name="Displacement View"# ✅ Save to file
)

displacement_pos_file = os.path.join(displacements_path, "PreCompr_disp.pos")
gmsh.write(displacement_pos_file)


print("analisi PreCompr finita")

### Linear lateral
for slave_node in slave_nodes:
    equalDOF(master_node_top, slave_node, 2, 3)

loadConst('-time', 0.0)
remove("loadPattern", 1)
remove("loadPattern", 2)

timeSeries('Linear', 3)
pattern('Plain', 3, 3)


### Loading 
#defining pushover parameters
dof_control_node = 1
dU = 0.05

load(master_node_top, 100000.0, 0.0, 0.0)  # Apply a lateral load in the X direction

system('BandGeneral')
constraints('Transformation')
numberer('RCM')
test('NormDispIncr', 1.0e-2, 50)
algorithm('NewtonLineSearch')
#algorithm('Linear')
#algorithm('Newton')
integrator('DisplacementControl', master_node_top, dof_control_node, dU)
analysis('Static')

max_displ = 5  # target (stima)
D, V = [], []
D.append(0.0); V.append(0.0)

# riferimento spostamento iniziale
D0 = nodeDisp(master_node_top, 1)

# === CSV pushover: apri UNA volta, header, flush a ogni step ===
csv_push_file = os.path.join(recorders_path, "pushover_curve.csv")
push_fh = open(csv_push_file, 'w', newline='')
push_writer = csv.writer(push_fh)
push_writer.writerow(['step', 'time', 'disp_X', 'baseShear_X'])

def try_step(dU_step, step_idx):
    """Prova un passo e, se riesce, registra subito su CSV e flush."""
    integrator('DisplacementControl', master_node_top, dof_control_node, dU_step)
    ok = analyze(1)
    if ok == 0:
        reactions()  # aggiorna reazioni nodali
        disp = nodeDisp(master_node_top, 1) - D0
        base_shear_x = sum(nodeReaction(n, 1) for n in unique_nodes_fix)  # somma reazioni alla base in X
        base_shear_x = -base_shear_x/1000
        t = getTime()

        # aggiorna liste (se ti servono anche in memoria)
        D.append(disp); V.append(base_shear_x)


        # scrivi SUBITO su CSV e flush
        push_writer.writerow([step_idx, t, disp, base_shear_x])
        push_fh.flush()
    return ok

# loop principale con fallback di passo
n_steps = int(max_displ / dU) if dU != 0 else 0
for i in range(n_steps):
    for factor in [1.0, 0.5, 0.1, 0.05, 0.01]:
        ok = try_step(dU * factor, i)
        if ok == 0:
            compute_and_visualize_principal_strains(
            element_tags=getEleTags(),
            save_dir=os.path.join(recorders_path, f"strains_{i}"),
            max_view_name=f"Principal_strains_max_{i}",
            min_view_name=f"Principal_strains_min_{i}",
            remove_intermediate=True)

            compute_and_visualize_principal_stresses(
                        element_tags=getEleTags(),
                        save_dir=os.path.join(recorders_path, f"stress_{i}"),
                        max_view_name=f"Principal_stress_max_{i}",
                        min_view_name=f"Principal_stress_min_{i}",
                        remove_intermediate=True
                    )
            visualize_displacements_in_gmsh(
            gmshmodel=gmsh.model, nodeTags=getNodeTags(),
            new_view_name="Displacement View",
            save_path=os.path.join(recorders_path, f"displacement_{i}.pos"))
            break
        else:
            print(f"  step {i}, factor {factor} failed, trying smaller step")
    else:
        print(f"step {i} permanently failed, aborting")
        break

# chiudi il file CSV in modo esplicito
push_fh.close()

displacement_pos_file = os.path.join(displacements_path, "lateral_linear.pos")
gmsh.write(displacement_pos_file)
#gmsh.fltk.run()




