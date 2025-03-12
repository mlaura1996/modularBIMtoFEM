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

import openseespy.opensees as ops

def adaptive_analysis_step(total_duration, initial_num_incr, max_iter=20, desired_iter=10,
                           max_factor=1.0, min_factor=1e-6, max_factor_increment=1.5,
                           min_factor_increment=1e-6, filename="analysis_log.txt"):
    # Initial setup
    factor = 1.0
    old_factor = factor
    current_time = 0.0
    initial_time_increment = total_duration / initial_num_incr
    time_tolerance = abs(initial_time_increment) * 1.0e-8
    increment = 1

    # Open log file
    with open(filename, 'w') as file:
        file.write("Starting adaptive analysis loop\n")
    
    # Main adaptive time-stepping loop
    while current_time < total_duration:
        
        # Compute adaptive time increment
        time_increment = initial_time_increment * factor
        if abs(current_time + time_increment) > abs(total_duration) - time_tolerance:
            time_increment = total_duration - current_time
        
        # Update the integrator with the adaptive time increment
        ops.integrator("LoadControl", time_increment)
        
        # Perform the analysis step
        ok = ops.analyze(1)
        
        if ok == 0:
            # Step succeeded - retrieve norms to analyze convergence quality
            norms = ops.testNorms()
            final_norm = norms[-1] if norms else 0.0  # Final norm indicates convergence quality
            num_iter = len(norms)

            # Log success and convergence information
            with open(filename, 'a') as file:
                file.write(f"Increment: {increment:6d} | Iterations: {num_iter:4d} | "
                           f"Norm: {final_norm:8.3e} | Progress: {(current_time / total_duration) * 100.0:7.3f} %\n")

            # Adjust `factor` based on convergence quality
            factor_increment = min(max_factor_increment, desired_iter / max(num_iter, 1))
            factor *= factor_increment
            factor = min(factor, max_factor)
            
            if factor > old_factor:
                with open(filename, 'a') as file:
                    file.write(f"Increasing increment factor to {factor} due to faster convergence.\n")
            
            old_factor = factor
            current_time += time_increment
            increment += 1

        else:
            # Step failed - reduce factor significantly for better convergence
            factor *= min_factor_increment
            if factor < min_factor:
                with open(filename, 'a') as file:
                    file.write("ERROR: Factor fell below min_factor. Analysis terminated.\n")
                raise RuntimeError("ERROR: the analysis did not converge")

    with open(filename, 'a') as file:
        file.write("Analysis successfully completed.\n")
    
    print("Adaptive analysis loop completed.")
   

@staticmethod
def force_displacement_recorder(folder_name:str, analysis_name:str, control_point, reaction_points, dof):
    """
    Sets up recorders for capturing the displacement and reaction forces at specific nodes during the analysis.

    This function configures two types of OpenSees recorders:
    1. Displacement Recorder: Records the displacement at a control node across a specified degree of freedom (dof).
    2. Reaction Force Recorder: Records the reaction forces at multiple nodes across the specified degree of freedom.

    The recorded data is saved in files within the provided folder, with filenames generated using the given analysis name.

    Parameters:
    - folder_name (str): The path to the folder where the output files will be saved.
    - analysis_name (str): The base name used for the output files.
    - control_point: The node ID at which displacement is recorded.
    - reaction_points: A list of node IDs at which reaction forces are recorded.
    - dof: The degree of freedom (e.g., 1 for x-axis, 2 for y-axis, etc.) to be monitored.
    """
    
    ops.recorder("Node", "-file", folder_name + "/" + analysis_name + "_displacement.out", "-time", "-node", control_point, "-dof", dof, "disp")
    
    ops.recorder("Node", "-file", folder_name + "/" + analysis_name + "_reactions.out", "-time", "-node", reaction_points, "-dof", dof,  "reaction")



