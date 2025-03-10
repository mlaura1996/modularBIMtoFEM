import os
import ifcopenshell
import gmsh
from core.config import GEOMETRY_SETTINGS, STEP_WRITER, EXPORT_DIR, ops, pd  # Load global settings
from core.ifc_processing.geometry_extractor import GeometryProcessor, StepExporter
from core.ifc_processing.data_extractor import Material
from core.mesh_generation.mesh import GmshModel
from core.opensees_generation.analysis_run import run_static_analysis
from core.opensees_generation.model_builder import ModelBuilder, Element, BoundaryConditions, Loads
from external.gmsh2opensees import *

# ✅ Define file paths
IFC_FILE_PATH = "resources/ifc_examples/CT02.ifc"
STEP_FILE_NAME = "CT02"

os.makedirs(EXPORT_DIR, exist_ok=True)  # Ensure export folder exists

def main():
    print("🚀 Starting IFC to STEP Conversion Pipeline...\n")

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
    gmshmodel = GmshModel.createGmshModel("export/CT02.step", gmsh_labels, run_gmsh = True, use_adaptive_mesh=True)
    
    # run_static_analysis(gmshmodel, material_db)
    # Load estimated time series with displacement data
    file_path = "resources/experimental_results/CT02_estimated_time_series.csv"  # Ensure this file is available
    df = pd.read_csv(file_path)

    # Extract time and displacement values
    time_values = df['Estimated Time (s)'].values  # Time steps
    displacement_values = df['Ux_top [mm]'].values  # Displacement history at top of the wall

    # Initialize the OpenSees Model
    model = ModelBuilder(ndm=3, ndf=3)
    model.initialize_model()

    element_tags = Element.add_elements_to_opensees(gmshmodel, material_db)

    # Apply boundary conditions
    fixed_nodes = BoundaryConditions.fixNodes(gmshmodel)

    # Get all nodes in the Gmsh physical group 'loads'
    loads_nodes, _, _, _ = get_elements_and_nodes_in_physical_group("Load", gmshmodel)

    # Apply Time Series for Cyclic Loading
    ops.timeSeries("Path", 2, "-dt", time_values[1] - time_values[0], "-values", *displacement_values)

    # Define Load Pattern
    ops.pattern("Plain", 2, 2)

    # Apply distributed cyclic load across all nodes in 'loads'
    load_factor = 1.0 / len(loads_nodes)  # Distribute load equally
    for node in loads_nodes:
        ops.load(node, load_factor, 0, 0)  # Load in X-direction

    # Define Displacement Control
    ops.integrator("DisplacementControl", loads_nodes[0], 1, 0.5)  # Control first node in 'loads'

    # Run Analysis
    ops.system("BandGeneral")
    ops.numberer("RCM")
    ops.constraints("Transformation")
    ops.test("NormDispIncr", 1e-8, 10, 0)
    ops.algorithm("Newton")
    ops.analysis("Static")

    # Define Recorders
    ops.recorder("Node", "-file", "displacement_record.csv", "-time", "-node", *loads_nodes, "-dof", 1, "disp")
    ops.recorder("Node", "-file", "reaction_forces.csv", "-time", "-node", *fixed_nodes, "-dof", 1, "reaction")
    ops.recorder("Element", "-file", "stress_strain.csv", "-time", "-ele", *element_tags, "material", 1, "stressStrain")

    for i in range(len(time_values)):
        ops.analyze(1)
        disp = ops.nodeDisp(loads_nodes[0], 1)
        print(f"Step {i}: Time = {time_values[i]:.2f} s, Disp = {disp:.5f} mm")
            # Visualize Displacements in Gmsh
        disp_view = visualize_displacements_in_gmsh(gmshmodel, loads_nodes, step=i, time=time_values[i], new_view_name="Displacement Visualization")
        
        # Visualize Element Stress Response in Gmsh
        stress_view = visualize_eleResponse_in_gmsh(gmshmodel, element_tags, "stress", step=i, time=time_values[i], new_view_name="Stress Visualization")

    # Save Gmsh views to .pos file
    gmsh.view.write("displacement_results.pos", disp_view)
    gmsh.view.write("stress_results.pos", stress_view)

    # Run Gmsh GUI for visualization
    gmsh.fltk.run()


if __name__ == "__main__":
    main()
