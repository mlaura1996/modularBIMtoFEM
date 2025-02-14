import openseespy.opensees as ops
import os
import gmsh
import numpy as np
from gmsh2opensees import * 
from .Visualisation import * 
from pathlib import Path
from tqdm import tqdm
from datetime import datetime

class utils:

    @staticmethod
    def basic_analysis_loop_displacement_control(filename, cpoint, ok, step, originalIntegrator):
        """
        A simplified loop for displacement control analysis, with adaptive integrator adjustments and algorithm changes
        to attempt convergence.

        Parameters:
        - filename (str): File path for logging.
        - ok (int): Initial convergence result from the analysis step (0 if successful, non-zero if failed).
        - step (int): Current step in the analysis.
        - originalIntegrator (float): Initial value for displacement control increment.
        """

        # If the analysis did not converge (ok != 0), adjust integrator and algorithm settings to try again
        if ok != 0:
            # Log and attempt smaller increment (10x smaller)
            with open(filename, 'a') as file:
                file.write(f"\nConvergence failed at step {step + 1}:")
                file.write("\nTrying 10x smaller displacement increment.")
            ops.integrator("DisplacementControl", cpoint, 2, originalIntegrator / 10)
            ok = ops.analyze(1)

        # If it converged, reset integrator
        if ok == 0:
            ops.integrator("DisplacementControl", cpoint, 2, originalIntegrator)

        elif ok != 0:
            # Log and attempt even smaller increment (100x smaller)
            with open(filename, 'a') as file:
                file.write(f"\nConvergence still failed at step {step + 1}:")
                file.write("\nTrying 100x smaller displacement increment.")
            ops.integrator("DisplacementControl", cpoint, 2, originalIntegrator / 100)
            ok = ops.analyze(1)

        # If it converged, reset integrator
        if ok == 0:
            ops.integrator("DisplacementControl", cpoint, 2, originalIntegrator)

        elif ok != 0:
            # Log and increase iterations to try achieving convergence
            with open(filename, 'a') as file:
                file.write(f"\nConvergence still failed at step {step + 1}:")
                file.write("\nIncreasing iterations to 200.")
            ops.test("NormDispIncr", 1e-11, 200)
            ok = ops.analyze(1)

        # If it converged, reset test conditions
        if ok == 0:
            ops.test("NormDispIncr", 1e-11, 50)

        elif ok != 0:
            # Final attempt: change algorithm to 'ModifiedNewton' if all else fails
            with open(filename, 'a') as file:
                file.write(f"\nConvergence failed after multiple attempts at step {step + 1}:")
                file.write("\nSwitching algorithm to 'ModifiedNewton'.")
            ops.algorithm("ModifiedNewton")
            ok = ops.analyze(1)

        return ok

    

    @staticmethod
    def basic_analysis_loop(filename, ok, step, originalIntegrator):
            
        
        with open(filename, 'a') as file:
            file.write(f"\nImpossible to reach convergency at step {step + 1}:")
            file.write(f"\nThe following change was done:")
            file.write(f"\nUsing 10 times smaller timestep at load factor {step + 1}:")
        ops.integrator("LoadControl", originalIntegrator/10)
        ops.analyze(1)

        if ok == 0:
            ops.integrator("LoadControl", originalIntegrator)            
        
        elif ok != 0:
            with open(filename, 'a') as file:
                file.write(f"\nImpossible to reach convergency at step {step + 1}:")
                file.write(f"\nThe following change was done:")
                file.write(f"\nUsing 100 times smaller timestep at load factor {step + 1}:")
            ops.integrator("LoadControl", originalIntegrator/100)
            ops.analyze(1)
        
        if ok == 0:
            ops.integrator("LoadControl", originalIntegrator) 
        
        elif ok != 0:
            with open(filename, 'a') as file:
                file.write(f"\nImpossible to reach convergency at step {step + 1}:")
                file.write(f"\nThe following change was done:")
                file.write(f"\nTrying 200 iterations at load factor {step + 1}:")
            ops.test("NormDispIncr", 1.*10**-11, 200)
            ops.analyze(1)
        
        if ok == 0:
            ops.test("NormDispIncr", 1.*10**-11, 50)
        
        elif ok != 0:
            with open(filename, 'a') as file:
                file.write(f"\nImpossible to reach convergency at step {step + 1}:")
                file.write(f"\nThe following change was done:")
                file.write(f"\nChanging algorithm to 'Modified Newton' at load factor {step + 1}:")
                ops.algorithm("ModifiedNewton")
                ok = ops.analyze(1)
            
        return ok
    

    @staticmethod
    def count_numbers_in_file(filename):
        count = 0
        with open(filename, "r") as file:
            for line in file:
                # Split line by whitespace and count the number of numeric entries
                numbers = line.strip().split()
                count += len(numbers)
        return count
    
    @staticmethod
    def getNodeWithHigherCoords(gmshmodel):
        node_tags, node_coords, _ = gmshmodel.mesh.getNodes()
        node_coords = np.array(node_coords).reshape(-1, 3)

        max_z_index = np.argmax(node_coords[:, 2])  # Index of the node with the highest Z value
        max_z_value = node_coords[max_z_index, 2]  # Highest Z value
        node_tag_with_max_z = node_tags[max_z_index]  # Node tag corresponding to this index

        ### lets try to open gmsh and enlight it

        return node_tag_with_max_z 
    
    @staticmethod
    def getBaseNode(gmshmodel):

        physical_groups = gmshmodel.getPhysicalGroups()
        for dim, tag in physical_groups:
            name = gmsh.model.getPhysicalName(dim, tag)
            if name == "Fix":
                group_dim = dim
                group_tag = tag
                break

        entities = gmshmodel.getEntitiesForPhysicalGroup(group_dim, group_tag)

        all_nodes = []
        
        # Loop through each entity and get the nodes
        for entity in entities:
            # Get node tags and coordinates for the entity
            node_tags = (gmshmodel.mesh.getNodes(group_dim, entity)[0])
            
            # Add the node tags to the set
            all_nodes.append(node_tags)
        
        return all_nodes
        


    @staticmethod
    def create_folder(folder_name):
        # Get the current date and time
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Append the date and time to the folder name
        base_folder_name = f"{folder_name}_{current_time}"
        count = 1

        # Create a Path object for the folder
        folder_path = Path(base_folder_name)

        # Check if the folder already exists
        while folder_path.exists():
            # Append a number to the folder name
            folder_path = Path(f"{base_folder_name}_{count}")
            count += 1

        # Create the new folder
        folder_path.mkdir()
        print(f"Folder '{folder_path}' created successfully.")
        return str(folder_path)


class nonLinearAnalysis:

    @staticmethod
    def run_gravity_analysis():
        return "Running gravity analysis..."
    
    @staticmethod
    def run_pushover_analysis_in_X_direction_positive():
        return "Running pushover analysis in X direction, positive..."
    
    @staticmethod
    def run_pushover_analysis_in_X_direction_negative():
        return "Running pushover analysis in X direction, negative..."
    
    @staticmethod
    def run_pushover_analysis_in_Y_direction_positive():
        return "Running pushover analysis in Y direction, positive..."
    
    @staticmethod
    def run_pushover_analysis_in_Y_direction_negative():
        return "Running pushover analysis in Y direction, negative..."


    # Create a dictionary that maps strings to functions
    analysis_methods = {
        "gravity": run_gravity_analysis(),
        "pushoverX_+": run_pushover_analysis_in_X_direction_positive(),
        "pushoverX_-": run_pushover_analysis_in_X_direction_negative(),
        "pushoverY_+": run_pushover_analysis_in_Y_direction_positive(),
        "pushoverY_-": run_pushover_analysis_in_Y_direction_negative(),
    }


class monotonicPushoverAnalysis:
    def gravity_analysis(nSteps, cPoint, element_tags, gmshmodel):
        
        folder = utils.create_folder("GravityLoads")

        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        Integrator = 1/nSteps
        ops.integrator("LoadControl", 1/nSteps) #the number is the load step
        ops.algorithm("ModifiedNewton")
        ops.analysis("Static")

        ops.test("NormDispIncr", 1.*10**-11, 50) #the first thing is the tolerance and the second thing is the number of iteration - 50 is a good amount of iterations

        recorder.force_displacement_recorder(folder, "gravity", cPoint, 3)

        filename = folder + "/Gravity_analysis_info.txt"

        with open(filename, 'a') as file:
            file.write(f"Using the following analysis settings: \nops.integrator(LoadControl, 1/{nSteps}); \nops.algorithm(Newton); \nops.test(NormDispIncr, 1.*10**-11, 50)")
            file.write("\n ")
            file.write("\nUsing IMPLEX")

        for step in tqdm(range(nSteps)):
            with open(filename, 'a') as file:
                file.write("\n ")
                file.write(f"\nStarting step {step+1}.")
            analysis = ops.analyze(1)

            analysis = utils.basic_analysis_loop(filename, analysis, step, Integrator)

            if analysis !=0:
                
                with open(filename, 'a') as file:
                    file.write("\nImpossible to reach convergency. Analysis failed.")
                break

            with open(filename, 'a') as file:
                file.write("\nConverged")

        viewnum = visualize_displacements_in_gmsh(gmshmodel)   
        gmsh.view.write(viewnum, folder + "/SW_Displacement.pos") 

        viewnum2 = visualize_reactions_in_gmsh(gmshmodel)
        gmsh.view.write(viewnum2, folder + "/SW_Reactions.pos") 

        try:
            visualize_eleResponse_in_gmsh(gmshmodel, element_tags, args="strains")
        except Exception as e:
            print(f"An error occurred: {e}")

    def horizontal_analysis(nSteps, cPoint, element_tags, gmshmodel):
        
        folder = utils.create_folder("HLoads")

        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        Integrator = 1/nSteps
        ops.integrator("LoadControl", 1/nSteps) #the number is the load step
        ops.algorithm("ModifiedNewton")
        ops.analysis("Static")

        ops.test("NormDispIncr", 1.*10**-11, 50) #the first thing is the tolerance and the second thing is the number of iteration - 50 is a good amount of iterations

        recorder.force_displacement_recorder(folder, "Horizonal", cPoint, 2)

        filename = folder + "/Horizonal_analysis_info.txt"

        with open(filename, 'a') as file:
            file.write(f"Using the following analysis settings: \nops.integrator(LoadControl, 1/{nSteps}); \nops.algorithm(Newton); \nops.test(NormDispIncr, 1.*10**-11, 50)")
            file.write("\n ")
            file.write("\nUsing IMPLEX")

        for step in tqdm(range(nSteps)):
            with open(filename, 'a') as file:
                file.write("\n ")
                file.write(f"\nStarting step {step+1}.")
            analysis = ops.analyze(1)

            if analysis != 0:

                analysis = utils.basic_analysis_loop(filename, analysis, step, Integrator)

            if analysis !=0:
                
                with open(filename, 'a') as file:
                    file.write("\nImpossible to reach convergency. Analysis failed.")
                break

            with open(filename, 'a') as file:
                file.write("\nConverged")

        viewnum = visualize_displacements_in_gmsh(gmshmodel)   
        gmsh.view.write(viewnum, folder + "/Horizonal_Displacement.pos") 

        viewnum2 = visualize_reactions_in_gmsh(gmshmodel)
        gmsh.view.write(viewnum2, folder + "/Horizonal_Reactions.pos") 

        try:
            visualize_eleResponse_in_gmsh(gmshmodel, element_tags, args="strains")
        except Exception as e:
            print(f"An error occurred: {e}")
    
    def basic_displacement_control_pushover(nSteps, cPoint, element_tags, gmshmodel, max_attempts=5, tolerance=1e-11, min_step_size=1e-4):
        """
        Perform a displacement-controlled pushover analysis in OpenSees with adaptive convergence control,
        and generate Gmsh visualizations for displacements, reactions, and strains at the end.

        Parameters:
        - nSteps (int): Number of steps for the pushover analysis.
        - cPoint (int): Node tag for the control point.
        - element_tags (list of int): List of element tags to visualize responses.
        - gmshmodel (Gmsh model object): The Gmsh model for visualizing results.
        - max_attempts (int): Maximum number of attempts for each step to achieve convergence.
        - tolerance (float): Initial convergence tolerance.
        - min_step_size (float): Minimum allowable displacement increment (load step).
        """

        # Set up folder for results and analysis configurations
        folder = utils.create_folder("Pushover")
        filename = f"{folder}/Pushover_analysis_info.txt"

        # Configure OpenSees analysis
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        integrator_value = 1 / nSteps
        ops.integrator("DisplacementControl", cPoint, 2, 0.01)  # Control in Y-axis by default
        ops.algorithm("ModifiedNewton")
        ops.analysis("Static")
        ops.test("NormDispIncr", tolerance, 50)  # Initial tolerance setting

        # Record analysis settings
        recorder.force_displacement_recorder(folder, "pushover", cPoint, 2)

        with open(filename, 'a') as file:
            file.write(f"Analysis settings:\nIntegrator: DisplacementControl (1/{nSteps})\nAlgorithm: ModifiedNewton\nTolerance: {tolerance}, Iterations: 50\n")

        # Run the pushover analysis with adaptive loop
        for step in tqdm(range(nSteps), desc="Running pushover analysis"):

            with open(filename, 'a') as file:
                file.write("\n ")
                file.write(f"\nStarting step {step+1}.")
            analysis = ops.analyze(1)

            analysis = utils.basic_analysis_loop_displacement_control(filename, cPoint, analysis, step, integrator_value)

            if analysis !=0:
                
                with open(filename, 'a') as file:
                    file.write("\nImpossible to reach convergency. Analysis failed.")
                break
            with open(filename, 'a') as file:
                file.write("\nConverged")

        # Visualization steps
        try:
            viewnum_disp = visualize_displacements_in_gmsh(gmshmodel)
            gmsh.view.write(viewnum_disp, f"{folder}/Displacements.pos")

            viewnum_react = visualize_reactions_in_gmsh(gmshmodel)
            gmsh.view.write(viewnum_react, f"{folder}/Reactions.pos")

            viewnum_strain = visualize_eleResponse_in_gmsh(gmshmodel, element_tags, args="strains")
            gmsh.view.write(viewnum_strain, f"{folder}/Strains.pos")

        except Exception as e:
            print(f"An error occurred during visualization: {e}")

        print("Pushover analysis and visualization complete.")



        



        


    
    











