import os
import ifcopenshell
import gmsh
from core.config import GEOMETRY_SETTINGS, STEP_WRITER, EXPORT_DIR, ops, pd  # Load global settings
from core.ifc_processing.geometry_extractor import GeometryProcessor, StepExporter
from core.ifc_processing.data_extractor import Material
from core.mesh_generation.mesh import GmshModel
from core.opensees_generation.analysis_run import adaptive_analysis_step, force_displacement_recorder
from core.opensees_generation.model_builder import ModelBuilder, Element, BoundaryConditions, Loads
from external.gmsh2opensees import *
from utils.analysis_helper import visualize_timeseries, plot_reaction_vs_displacement, create_csv_file_for_force_displacement_recorder
import opsvis
import vfo.vfo as vfo





# ✅ Define file paths
IFC_FILE_PATH = "resources/ifc_examples/CT02.ifc"
STEP_FILE_NAME = "CT02"

os.makedirs(EXPORT_DIR, exist_ok=True)  # Ensure export folder exists

def main():
    print("🚀 Starting IFC to STEP Conversion Pipeline...\n")
    # Clear previous OpenSees model
    ops.wipe()

    # ✅ Load IFC File
    print(f"📂 Loading IFC file: {IFC_FILE_PATH}")
    ifc_model = ifcopenshell.open(IFC_FILE_PATH)

    material_db = Material.create_material_database(ifc_model)
    print(material_db)
    
    # ✅ Initialize Geometry Processor
    geometry_processor = GeometryProcessor(GEOMETRY_SETTINGS)

    # ✅ Extract IFC Elements (Walls, Slabs, etc.)
    elements = [element for element in ifc_model.by_type("IfcBuildingElement")
     if not element.is_a("IfcBuildingElementProxy")]
    print(f"🔍 Found {len(elements)} building elements in the IFC model.\n")
    elements_dictionary = Material.assign_material_tags(elements, material_db)

    # ✅ Generate STEP File
    step_exporter = StepExporter(STEP_WRITER)
    step_path, labels = step_exporter.generate_step_file(elements, elements_dictionary, os.path.join(EXPORT_DIR, STEP_FILE_NAME))

    # ✅ Print Results
    print(f"\n✅ STEP file successfully created at: {step_path}")
    print("📝 Exported Elements:")
    for label in labels:
        print(f"   - {label}")

    print("\n🎉 IFC to STEP conversion completed successfully!")

    print(STEP_FILE_NAME)
    # # ✅ GmshModel
    gmsh_labels = list(material_db.keys())
    # print(gmsh_labels)
    gmshmodel = GmshModel.createGmshModel("export/CT02.step", gmsh_labels, run_gmsh = False, use_adaptive_mesh=False)

    # Initialize the OpenSees Model
    model = ModelBuilder(ndm=3, ndf=3)
    model.initialize_model()
    nodesTags, coord = get_all_nodes(gmshmodel)
    add_nodes_to_ops(nodesTags, gmshmodel)

    element_tags = Element.add_elements_to_opensees(gmshmodel, material_db)

    # Apply boundary conditions
    BoundaryConditions.fixNodes(gmshmodel)
    
    fixed_nodes, _, _, _ = get_elements_and_nodes_in_physical_group("Fix", gmshmodel)
    # Define Force-Controlled Loading (Cycle 1F) with Newtons
    F_max_N = 20000  # 20 kN = 20000 N
    F_1F_N = F_max_N / 4  # 1/4 of Fmax = 5000 N

    # Get all nodes in the Gmsh physical group 'loads'
    loads_nodes, _, _, _ = get_elements_and_nodes_in_physical_group("Load", gmshmodel)
    # print(f"🔍 Debug: Loaded Nodes = {loads_nodes}")
    # print(f"🔍 Debug: Fixed Nodes = {fixed_nodes}")

    # Define Recorders Before Running Any Analysis
    force_displacement_recorder("output", "self_weight", loads_nodes, fixed_nodes, 3)

    # ops.system("UmfPack")
    # ops.numberer("Plain")
    # ops.constraints('Plain')
    # # ops.integrator("LoadControl", 1/Nsteps)
    # ops.integrator("Newmark", 0.5, 0.25)
    # ops.algorithm("Linear")

    # # ops.analysis("Static")
    # ops.analysis("Transient")

    # Nmodes = 10
    # Λ = ops.eigen(Nmodes)

    # # print(f"{Λ=}")

    # from numpy import sqrt, pi
    # for i, λ in enumerate(Λ):
    #     mode = i + 1
    #     ω = sqrt(λ)
    #     f = ω / (2*pi)
    #     T = 1 / f
    #     print(f"{mode=} {ω=} (rad/s) {f=} (Hz) {T=} (s)")


    # mode = 1
    # visualize_eigenmode_in_gmsh(gmsh.model, 
    #     mode=mode, 
    #     f=sqrt(Λ[mode-1])/(2*pi), 
    #     animate=True)

    # mode = 2
    # visualize_eigenmode_in_gmsh(gmsh.model, 
    #     mode=mode, 
    #     f=sqrt(Λ[mode-1])/(2*pi), 
    #     animate=True)

    # mode = 3
    # visualize_eigenmode_in_gmsh(gmsh.model, 
    #     mode=mode, 
    #     f=sqrt(Λ[mode-1])/(2*pi), 
    #     animate=True)
    
    ##Selft weight 
    

    linear_ts_tag = 1
    ops.timeSeries('Linear', linear_ts_tag)

    patternTag = 1
    ops.pattern('Plain', patternTag, linear_ts_tag)
    ops.eleLoad("-ele", *element_tags, "-type", "-selfWeight", 0, 0, 1)
    Nsteps = 100
    ops.system("UmfPack")
    ops.numberer("Plain")


    # ops.constraints('Penalty', alphaS, alphaM)
    ops.constraints('Plain')
    ops.integrator("LoadControl", 1.0/Nsteps)
    ops.algorithm("Newton")
    ops.test('NormDispIncr',1e-8, 10, 1)

    ops.analysis("Static")

    ops.analyze(Nsteps)

    visualize_displacements_in_gmsh(gmshmodel)

    create_csv_file_for_force_displacement_recorder("output/self_weight_reactions.out", "output/self_weight_displacement.out", "output/self_weight.csv")
    
    #gmsh.fltk.run()
    ops.wipeAnalysis()
    ops.remove("loadPattern", 1)
    force_displacement_recorder("output", "cyclic_analysis_Y", loads_nodes, fixed_nodes, 2)
    force_displacement_recorder("output", "cyclic_analysis_X", loads_nodes, fixed_nodes, 1)

    num_top_nodes = len(loads_nodes)
    if num_top_nodes > 0:
        F_per_node_N = F_1F_N / num_top_nodes  # Distribute force among nodes
        ops.timeSeries("Linear", 2)
        ops.pattern("Plain", 2, 2)

        for node in loads_nodes:
            ops.load(node, F_per_node_N, 0, 0)  # Apply force in X-direction
        ops.printModel('-JSON', '-file', 'model.json')
        # opsvis.plot_model()
        # vfo.plot_model() 
        print(f"✅ Applied {F_1F_N} N total force across {num_top_nodes} nodes.")
         # Run Force-Controlled Analysis
        # Analysis definitions:
        # Create the constraint handler, a Plain handler is used as homo constraints:
        #ops.printModel()
        ops.constraints('Transformation')
        # Create the DOF numberer, the plain algorithm is used:
        ops.numberer('Plain')
        # Create the system of equation, a SPD using a band storage scheme:
        ops.system('BandSPD')
        # Create the solution algorithm, a Linear algorithm is created:
        ops.algorithm('Linear')
        # Create the integration scheme, the LoadControl scheme using steps of 1.0:
        ops.integrator('LoadControl', 0.1)
        # create the analysis object:
        ops.analysis('Static')
        # Perform the analysis (1 step):
        ops.analyze(10)
        print("✅ Force-Controlled Analysis (1F) Completed.")
        
        # Visualize Displacements in Gmsh (1F)
        visualize_displacements_in_gmsh(gmshmodel, loads_nodes, step=0, time=0.0, new_view_name="Displacement Visualization 1F")
        
        create_csv_file_for_force_displacement_recorder("output/cyclic_analysis_Y_reactions.out", "output/cyclic_analysis_Y_displacement.out", "output/cyclic_analysis_Y.csv")
        create_csv_file_for_force_displacement_recorder("output/cyclic_analysis_X_reactions.out", "output/cyclic_analysis_X_displacement.out", "output/cyclic_analysis_X.csv")

        plot_reaction_vs_displacement("output/self_weight.csv")
        plot_reaction_vs_displacement("output/cyclic_analysis_Y.csv")
        plot_reaction_vs_displacement("output/cyclic_analysis_X.csv")


        # Remove force loads for next phase
        ops.remove("loadPattern", 1)
        

    else:
        print("❌ No nodes found in 'loads' physical group! Check Gmsh model.")
    
        
    
    # # Apply Displacement-Controlled Loading (Cycles 1S to 10S)
    # drift_values = [0.050, 0.075, 0.100, 0.150, 0.200, 0.250, 0.300, 0.400, 0.500, 0.600]  # Drift percentages
    # H_wall = 2500  # Wall height in mm
    # displacement_values = [(drift / 100) * H_wall for drift in drift_values]
    # time_values = [0, 200, 400, 600, 840, 1090, 1340, 1590, 1840, 2090, 2340]

    # ops.timeSeries("Path", 2, "-time", time_values, "-values", displacement_values)
    # ops.pattern("Plain", 2, 2)
    # for node in loads_nodes:
    #     ops.sp(node, 1, displacement_values[0])

    # # Run Adaptive Displacement-Controlled Analysis
    # adaptive_analysis_step(total_duration=max(time_values), initial_num_incr=100)

    # for i in range(len(displacement_values)):
    #     disp = ops.nodeDisp(loads_nodes[0], 1)
    #     print(f"✅ Step {i}: Applied Drift {drift_values[i]}%, Disp = {disp:.5f} mm")
        
    #     # Visualize Displacements in Gmsh (1S - 10S)
    #     visualize_displacements_in_gmsh(gmshmodel, loads_nodes, step=i+1, time=time_values[i], new_view_name="Displacement Visualization 1S-10S")

    # # Save Gmsh views to .pos file
    # gmsh.view.write("displacement_results.pos")
    # gmsh.view.write("stress_results.pos")

    # # Run Gmsh GUI for visualization
    gmsh.fltk.run()



if __name__ == "__main__":
    main()
