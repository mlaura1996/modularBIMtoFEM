import matplotlib.pyplot as plt
import numpy as np
import openseespy.opensees as ops
import gmsh
import csv
import pandas as pd 


class preProcessing:

    @staticmethod
    def highlight_control_point(gmshmodel, point_tag):
        """
        Highlights a specific control point in the Gmsh model by setting its visibility and color,
        while hiding all other points. Adjusts mesh and geometry display options for better visibility.

        :param gmshmodel: The Gmsh model object containing the geometry and mesh entities
        :param point_tag: The tag identifier of the control point to be highlighted
        """

        pointDimTag = (0, point_tag)

        gmsh.option.set_number("Mesh.SurfaceEdges", 0)
        gmsh.option.set_number("Mesh.VolumeFaces", 1)
        gmsh.option.set_number("Mesh.ColorCarousel", 0)
        gmsh.option.setColor("Mesh.Color.Tetrahedra", 128, 128, 128)
        gmsh.option.setColor("Geometry.Color.Curves", 0, 0, 0)

        point_tags = ((gmshmodel.getEntities(dim = 0)))
        for dim, tag in point_tags:
            gmsh.model.setVisibility([(dim, tag)], 0)

        gmsh.model.setVisibility([pointDimTag], 1)

        gmsh.option.setColor("Geometry.Color.Points", 255, 0, 0)
        gmsh.option.set_number("Geometry.PointType", 1)

        gmsh.fltk.run()
    
    @staticmethod
    def highlight_reactions_points(gmshmodel, point_tags):
        """
        Highlights a list of reactio points in the Gmsh model by setting their visibility and color,
        while hiding all other points. Adjusts mesh and geometry display options for better visibility.

        :param gmshmodel: The Gmsh model object containing the geometry and mesh entities
        :param point_tags: List of tag identifiers for the control points to be highlighted
        """

        # Ensure the input is a list of point tags
        if not isinstance(point_tags, list):
            raise ValueError("point_tags must be a list of point tag identifiers")

        # Set up the visualization options
        gmsh.option.set_number("Mesh.SurfaceEdges", 0)
        gmsh.option.set_number("Mesh.VolumeFaces", 1)
        gmsh.option.set_number("Mesh.ColorCarousel", 0)
        gmsh.option.setColor("Mesh.Color.Tetrahedra", 128, 128, 128)
        gmsh.option.setColor("Geometry.Color.Curves", 0, 0, 0)

        # Retrieve all point entities (dimension 0 corresponds to points)
        #all_point_tags = gmshmodel.getEntities(dim=0)
        all_point_tags = gmsh.model.mesh.get_elements(0)
        array = (all_point_tags[1])
        ints = array[0]

        print(ints)

        # # Hide all points initially
        # for tag in ints:
        #     dimtg = (0, tag)
        #     gmsh.model.mesh.setVisibility([dimtg], 0)

        # # Highlight only the specified control points
        # for point_tag in point_tags:
        #     pointDimTag = (0, point_tag)
        #     gmsh.model.mesh.setVisibility([pointDimTag], 1)

        # # Set the color and point type for the highlighted points
        # gmsh.option.setColor("Mesh.Color.Nodes", 255, 0, 0)
        # gmsh.option.set_number("Geometry.PointType", 1)

        # # Run the Gmsh graphical interface
        gmsh.fltk.run()

class recorder:

    @staticmethod
    def force_displacement_recorder(folder_name:str, analysis_name:str, control_point, dof):
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
        
        ops.recorder("Node", "-file", folder_name + "/" + analysis_name + "_reactions.out", "-time", "-node", "-dof", dof,  "reaction")


class postProcessing:

    @staticmethod
    def create_csv_file_for_force_displacement_recorder(reaction_file, displacement_file, output_csv_file):
        """
        Processes reaction and displacement data files and writes the combined results to a CSV file.
        
        :param reaction_file: Path to the file containing reaction data
        :param displacement_file: Path to the file containing displacement data
        :param output_csv_file: Path to the output CSV file
        """
        # Lists to store processed data
        reaction_sums = []
        displacements = []

        # Process the reaction file to sum the values (ignoring the first column)
        with open(reaction_file, 'r') as file:
            for line in file:
                # Split the line into columns
                columns = line.strip().split()
                
                # Ignore the first column and keep the rest
                data_without_first_column = columns[1:]
                
                # Convert the remaining data to float and sum them
                row_sum = sum(float(value) for value in data_without_first_column)
                
                # Store the sum for later use
                reaction_sums.append(row_sum)

        # Process the displacement file and store processed data
        with open(displacement_file, 'r') as file:
            for line in file:
                # Split the line into columns
                columns = line.strip().split()
                
                # Ignore the first column and keep the rest
                if len(columns) > 1:  # Ensure there are more columns to process
                    displacement_value = float(columns[1])
                    
                    # Store the displacement for later use
                    displacements.append(displacement_value)

        # Ensure both lists have the same length (just in case there's a mismatch)
        min_length = min(len(reaction_sums), len(displacements))
        reaction_sums = reaction_sums[:min_length]
        displacements = displacements[:min_length]

        # Add (0, 0) as the first row
        reaction_sums.insert(0, 0)
        displacements.insert(0, 0)

        # Write to CSV file
        with open(output_csv_file, 'w', newline='') as csvfile:
            csv_writer = csv.writer(csvfile)
            
            # Write header
            csv_writer.writerow(['TotalReaction', 'Displacement'])
            
            # Write data rows
            for reaction, displacement in zip(reaction_sums, displacements):
                csv_writer.writerow([reaction, displacement])

    @staticmethod

    def plot_reaction_vs_displacement(file_path):
        """
        Reads a CSV file and plots Displacement (X-axis) vs Reaction Sum (Y-axis)
        
        :param file_path: Path to the CSV file containing the data
        """
        data = pd.read_csv(file_path)

        # Extract the columns, assuming they are named 'Reaction Sum' and 'Displacement'
        reaction_sums = data['TotalReaction']
        displacements = data['Displacement']
        plt.figure(figsize=(8, 6))
        plt.plot(displacements, reaction_sums, linestyle='-', color = 'k')
        plt.xlabel("Displacement (mm)")
        plt.ylabel("Reactions (N)")
        plt.title("Reactions vs Displacement")
        plt.grid(True)
        plt.show()





                


