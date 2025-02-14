import os
import ifcopenshell
from core.config import GEOMETRY_SETTINGS, STEP_WRITER, EXPORT_DIR  # Load global settings
from core.ifc_processing.geometry_extractor import GeometryProcessor, StepExporter
from core.ifc_processing.data_extractor import Material
from core.mesh_generation.mesh import GmshModel

# ✅ Define file paths
IFC_FILE_PATH = "resources/ifc_examples/SimpleModel_V1.ifc"
STEP_FILE_NAME = "SimpleModel_V1"

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
    print(gmsh_labels)
    GmshModel.createGmshModel("export/SimpleModel_V1.step", gmsh_labels, use_adaptive_mesh=True)

if __name__ == "__main__":
    main()
