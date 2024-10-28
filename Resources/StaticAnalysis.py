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
    def LcBasicAnalysisLoop(filename, ok, nn, step, cNode, originalIntegrator, originalAlgorithm, originalTest):

        with open(filename, 'a') as file:
            file.write(f"\nThe following changes were done to accomplish convergency at step {step}:")

        """Create an analysis loop to improve convergency"""
        if ok !=0:
            print("Trying 10 times smaller timestep at load factor", nn)
            ops.integrator("LoadControl", .1)
            ok = ops.analyze(step)    
            with open(filename, 'a') as file:
                file.write(f"Trying 10 times smaller timestep at load factor {nn}.")    
            
            if ok ==0:
                originalIntegrator

        if ok !=0:
            print("Trying 100 times smaller timestep at load factor", nn) #100 smaller is already ok
            ops.integrator("LoadControl", .01)
            ok = ops.analyze(step)   
            with open(filename, 'a') as file:
                file.write(f"\nTrying 100 times smaller timestep at load factor {nn}.")   
            
            if ok ==0:
                originalIntegrator
                 
        
        if ok !=0:
            print("Trying 200 iterations at load factor", nn)
            ops.integrator("LoadControl", .01)
            ops.test("NormDispIncr", 1.*10**-11, 200)
            ok = ops.analyze(step)
            with open(filename, 'a') as file:
                file.write(f"\nTrying 200 iterations at load factor {nn}.")
            if ok ==0:
                originalTest
       
        if ok !=0:
            print("Trying Modified Newton algorithm at load factor", nn)
            ops.algorithm("ModifiedNewton")
            ok = ops.analyze(step)
            with open(filename, 'a') as file:
                file.write(f"\nTrying Modified Newton algorithm at load factor {nn}.")
            if ok ==0:
                originalAlgorithm

        if ok !=0: 
            print("Pass to displacement control", nn)
            ops.integrator("DisplacementControl", cNode, 2, .001)
            ok = ops.analyze(step)
            with open(filename, 'a') as file:
                file.write(f"\nPass to displacement at load factor {nn}.")
            if ok ==0:
                originalIntegrator = ops.integrator("DisplacementControl", cNode, 2, .001)
        
        return ok
    

    @staticmethod
    def basic_analysis_loop(filename, ok, step, originalIntegrator):
            
        if ok != 0:
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
    def GravityLoads(nSteps, cPoint, element_tags, gmshmodel):
        
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

    def basic_pushover_settings(analysisName, nSteps, cPoint, bPoints, element_tags, gmshmodel):

        folder = utils.create_folder(analysisName)

        ops.wipeAnalysis()
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        Integrator = ops.integrator("LoadControl", 1/nSteps) #the number is the load step
        Algorithm = ops.algorithm("Newton")
        ops.analysis("Static")
        Test = ops.test("NormDispIncr", 1.*10**-11, 50)

        # Define Recorders
        ops.recorder("Node", "-file", folder + "/Push_node_disp.out", "-time", "-node", cPoint, "-dof", 2, "disp")
        ops.recorder("Node", "-file", folder + "/Push_base_reactions.out", "-time", "-node", *bPoints, "-dof", 2,  "reaction")
        


    def PushOverLC(analysisName, nSteps, cPoint, bPoints, element_tags, gmshmodel):

        folder = utils.create_folder(analysisName)
        ops.wipeAnalysis()
        ops.system("BandGeneral")
        ops.numberer("Plain")
        ops.constraints("Transformation")
        Integrator = ops.integrator("LoadControl", 1/nSteps) #the number is the load step
        Algorithm = ops.algorithm("Newton")
        ops.analysis("Static")

        #Create test
        """The displacement test allows us to understand how much is the displacement changing from step to step.
        If its not changing a lot, we are reaching the convergency. - the model has converged"""
        Test = ops.test("NormDispIncr", 1.*10**-11, 50) #the first thing is the tolerance and the second thing is the number of iteration - 50 is a good amount of iterations


        # Define Recorders
        ops.recorder("Node", "-file", folder + "/Push_node_disp.out", "-time", "-node", cPoint, "-dof", 2, "disp")
        ops.recorder("Node", "-file", folder + "/Push_base_reactions.out", "-time", "-node", *bPoints, "-dof", 2,  "reaction")
        


        if isinstance(cPoint, int):
            print(f"{cPoint} is a valid single node ID.")
        else:
            print(f"Control Point {cPoint} is not a valid node ID.")

        if isinstance(bPoints, list) and all(isinstance(i, int) for i in bPoints):
            print("Base Points are valid node IDs.")
        else:
            print("Base Points are not valid node IDs.")
        index = 0
        for step in range(nSteps):
            index += (1/nSteps)
            analysis = ops.analyze(step)

            filename = folder + "/" + analysisName + "_PushOverInfo.txt"
            with open(filename, 'w') as file:
                file.write(f"Using the following analysis settings: ops.integrator(LoadControl, 1/{nSteps}); ops.algorithm(Newton); ops.test(NormDispIncr, 1.*10**-11, 50)")

            with open(filename, 'a') as file:
                file.write("Using IMPLEX")
            utils.LcBasicAnalysisLoop(filename, analysis, index, step, cPoint, Integrator, Algorithm, Test)
        
        
            viewnum = visualize_displacements_in_gmsh(gmshmodel, step = step)
                      
            gmsh.view.write(viewnum, folder + "/" + analysisName + "_displacements_" + str(step)+ ".pos") 

            try:
                viewnum1 = visualize_eleResponse_in_gmsh(gmshmodel, element_tags, args="strains", step = step)
                gmsh.view.write(viewnum1, folder + "/" + analysisName + "_strain_" + str(step)+ ".pos") 

            except Exception as e:
                print(f"An error occurred: {e}")
        


    
    











