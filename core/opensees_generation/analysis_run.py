import openseespy.opensees as ops
from core.config import *
from external.gmsh2opensees import *
from models.masonry_law import *
from utils.gmsh_helpers import *
from utils.dict_helper import *
from .model_builder import ModelBuilder, Element, BoundaryConditions, Loads

def run_static_analysis(gmshmodel, materials_dict):
    # Step 1: Initialize the Model (3D Model with 3 DOF per node)
    model = ModelBuilder(ndm=3, ndf=3)
    model.initialize_model()

    # Step 3: Create and Assign Elements
    print("Creating elements in OpenSees...")
    element_tags = Element.add_elements_to_opensees(gmshmodel, materials_dict)

    # Step 2: Apply Boundary Conditions (Fix base nodes)
    print("Applying boundary conditions...")
    BoundaryConditions.fixNodes(gmshmodel)

    # Step 4: Define Loads (Self-weight applied to elements)
    print("Applying loads...")
    load_case = Loads(timeSeriesType="Linear", timeSeriesTag=1, patternType="Plain", patternTag=1)
    load_case.addSelfWeight(element_tags)

    # Step 5: Define Static Analysis Settings
    print("Defining static analysis parameters...")
    ops.constraints("Transformation")  # Handles interaction constraints
    ops.numberer("RCM")  # Renumber nodes for efficiency
    ops.system("SparseGeneral")  # Solver type
    ops.test("NormDispIncr", 1e-6, 10, 0)  # Convergence criteria
    ops.algorithm("Newton")  # Solution algorithm
    ops.integrator("LoadControl", 1.0)  # Load increment step (static)
    ops.analysis("Static")  # Define the analysis type
    
    # Step 6: Run the Analysis
    print("Running the static analysis...")
    ok = ops.analyze(10)  # Perform 10 load steps
    
    if ok == 0:
        print("✅ Static analysis completed successfully!")
    else:
        print("❌ Static analysis failed.")
    

    # Step 7: Visualize Results in Gmsh
    print("🔍 Generating visualization in Gmsh...")
    
    # Displacement visualization
    visualize_displacements_in_gmsh(gmshmodel, new_view_name="Displacements")
    
    # Stress visualization (first principal stress)
    visualize_eleResponse_in_gmsh(gmshmodel, element_tags, "stress", new_view_name="Stresses")

    # Strain visualization (first principal strain)
    visualize_eleResponse_in_gmsh(gmshmodel, element_tags, "strain", new_view_name="Strains")

    gmsh.fltk.run()
    

    return element_tags  # Return element tags for visualization/debugging


