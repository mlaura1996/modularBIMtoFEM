import os
import ifcopenshell
import gmsh
import openseespy.opensees as ops
from core.config import GEOMETRY_SETTINGS, STEP_WRITER, EXPORT_DIR  # Load global settings
from core.ifc_processing.geometry_extractor import GeometryProcessor, StepExporter
from core.ifc_processing.data_extractor import Material
from core.mesh_generation.mesh import GmshModel
from core.opensees_generation.model_builder import ModelBuilder, Element, BoundaryConditions
from external.gmsh2opensees import *


# ✅ Define file paths
IFC_FILE_PATH = "resources/ifc_examples/modelloProvaV1.ifc"
STEP_FILE_NAME = "modelloProva"

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
    print("\n🎉 IFC to STEP conversion completed successfully!")

    print(STEP_FILE_NAME)
    # # ✅ GmshModel
    gmsh_labels = list(material_db.keys())
    gmshmodel = GmshModel.createGmshModel("export/modelloProva.step", gmsh_labels, run_gmsh = False, use_adaptive_mesh=False)
    gmsh.fltk.run()
  
    # Initialize the OpenSees Model
    model = ModelBuilder(ndm=3, ndf=3)
    model.initialize_model()
    nodesTags, coord = get_all_nodes(gmshmodel)
    add_nodes_to_ops(nodesTags, gmshmodel)

    element_tags = Element.add_elements_to_opensees(gmshmodel, material_db)

    # Apply boundary conditions
    BoundaryConditions.fix_nodes(gmshmodel)
    
    linear_ts_tag = 1
    ops.timeSeries('Linear', linear_ts_tag)

    patternTag = 1
    ops.pattern('Plain', patternTag, linear_ts_tag)
    ops.eleLoad("-ele", *element_tags, "-type", "-selfWeight", 0, 0, 1)
    Nsteps = 10
    ops.system("UmfPack")
    ops.numberer("Plain")
    ops.constraints('Plain')
    ops.integrator("LoadControl", 1.0/Nsteps)
    ops.algorithm("Newton")
    ops.test('NormDispIncr',1e-8, 10, 1)

    ops.analysis("Static")

    ops.analyze(Nsteps)

    visualize_displacements_in_gmsh(gmshmodel)
    gmsh.fltk.run()
    

if __name__ == "__main__":
    main()
