import openseespy.opensees as ops
from gmsh2opensees import * 
from .StaticAnalysis import *
from .Visualisation import *
import math
import matplotlib.pyplot as plt
import numpy as np 
from  .ConstitutiveLaws import ConstitutiveLaws as Masonry

g = 9810
class GeneralTools:

    @staticmethod
    def add_incremental_number(existing_list: list) -> int:
        """This method returns an incremental number that is not in the provided list."""
        
        excluded_set = set(existing_list)  # Convert list to set for O(1) lookups
        max_excluded = max(excluded_set) if excluded_set else -1  # Find the maximum value in the excluded list
        current_num = max_excluded + 1

        while current_num in excluded_set:
            current_num = current_num + 1

        return current_num
    
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
    def get_element_side_lenght(element_tag):
        """This method returns the side lenght of a gmsh element given the element tag."""
        
        volume = gmsh.model.mesh.getElementQualities(element_tag, "volume") 
        side_length = (6 * math.sqrt(2) * volume) ** (1/3)
        
        return(side_length)
    
    
class Geometry:
    @staticmethod
    def addUniqueSolidMaterialTags(excluded_list):

        #This function returns an incremental number that is not in the excluded_list - needed for the tags of the materials

        excluded_set = set(excluded_list)  # Convert list to set for O(1) lookups
        max_excluded = max(excluded_set) if excluded_set else -1  # Find the maximum value in the excluded list
        current_num = max_excluded + 1

        while current_num in excluded_set:
            current_num = current_num +1

        return current_num

    @staticmethod
    def create_linear_elastic_element (gmshmodel, material_dictionary, solid_material_tag):

        E = material_dictionary['YoungModulus'] #MPa - N/mm2
        mrho = material_dictionary['MassDensity'] # kg / m³
        rho = float(mrho*1e-12) # Ton / mm³
        nu = material_dictionary['PoissonRatio'] #--

        ops.nDMaterial('ElasticIsotropic', solid_material_tag, E, nu, rho)

        print('Elastic material created with tag: ', solid_material_tag)
        #assign material to element
        physical_group = material_dictionary['MaterialName']

        element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)

        #Add node tags to Opensees
        for node_tag in node_tags:
            add_nodes_to_ops(node_tag, gmshmodel, True)

        #Add elements to opensees
        for ele_tag, ele_nodes in zip(element_tags, node_tags):
            ops.element('FourNodeTetrahedron', ele_tag, *ele_nodes, solid_material_tag, 0, 0, -rho*g)
            print(f'Linear elastic fourNodeTetrahedron element with tag {ele_tag} added.')
        
        return solid_material_tag
    
    @staticmethod
    def create_plastic_damage_elements(gmshmodel, material_dictionary, solid_material_tag):

        E = material_dictionary['YoungModulus'] #MPa - N/mm2
        mrho = material_dictionary['MassDensity'] # kg / m³
        rho = float(mrho*1e-12) # Ton / mm³
        nu = material_dictionary['PoissonRatio'] #--
        fc = material_dictionary['CompressiveStrength'] #MPa - N/mm2
        ft = material_dictionary['TensileStrength'] #MPa - N/mm2

        if 'CompressionFractureEnergy' in material_dictionary:
            Gc = float(material_dictionary['CompressionFractureEnergy'])
        else: 
            Gc = 15 + (0.43*fc) - 0.0036*(fc**2)
        
        if 'TensionFractureEnergy' in material_dictionary:
            Gt = float(material_dictionary['TensionFractureEnergy'])
        else: 
            Gt = 0.025*(fc/10)**(0.7)
        
        if 'CompressiveStressElasticBehaviour' in material_dictionary:
            f0 = float(material_dictionary['CompressiveStressElasticBehaviour'])
        else:
            f0 = fc/3

        #Creating the geometry
        physical_group = material_dictionary['MaterialName']
        
        #Getting the gmsh model
        element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)

        #Add node tags to Opensees
        for node_tag in node_tags:
            add_nodes_to_ops(node_tag, gmshmodel, True)
        
        for element_tag, node_tag in zip(element_tags, node_tags):

            solid_material_tag = solid_material_tag + 1
            side_length = GeneralTools.get_element_side_lenght([element_tag])
            side_length = side_length[0]
            print(side_length)

            #Tensile behaviour
            Te, Ts, Td = Masonry.ExponentialSoftening_Tension.tension(E, ft, Gt, side_length)

            #Compression behaviour 
            Ce, Cs, Cd = Masonry.BezierCurve_Compression.Compression(E, f0, fc, Gc, side_length)

            #Definition of the OpenSees material
            
            ops.nDMaterial('ASDConcrete3D', solid_material_tag,
            E, nu, # elasticity
            '-Te', *Te, '-Ts', *Ts, '-Td', *Td, # tensile law
            '-Ce', *Ce, '-Cs', *Cs, '-Cd', *Cd, # compressive law
            )

            print('Plastic material created with tag: ', solid_material_tag)

            #Add the tetrahedron

            ops.element('FourNodeTetrahedron', element_tag, *node_tag, solid_material_tag, 0, 0, -rho*g)
            print('Nonlinear element added!')
    
        return solid_material_tag
    
    @staticmethod
    def add_elements_to_opensees(gmshmodel, material_data):
        """This method create the opensees elements to add to the model."""  

        tags = []
        for material_dictionary in material_data:

            #Get all the tags that will be in OpenSees - needed to show the results in Gmsh
            physical_group = material_dictionary['MaterialName']

            element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)
            element_tags.append(element_tags)
            
            #Create the material
            solid_material_tag = Geometry.addUniqueSolidMaterialTags(tags)

            #Define Material Type
            if material_dictionary['MaterialModelType'] == 'LinearElastic':
                tag = Geometry.create_linear_elastic_element(gmshmodel, material_dictionary, solid_material_tag)                    
            if material_dictionary['MaterialModelType'] == 'PlasticDamage':
                tag = Geometry.create_plastic_damage_elements(gmshmodel, material_dictionary, solid_material_tag) 
            tags.append(tag)         

        return element_tags
    
class BoundaryConditions:

    @staticmethod
    def fix_nodes(gmshmodel):
        #Create boundary conditions
        elementTags2, nodeTags2, elementName2, elementNnodes2 = get_elements_and_nodes_in_physical_group("Fix", gmshmodel)
        fix_nodes(nodeTags2, 'XYZ')
         

class Loads:

    @staticmethod
    def addTimeseriesAndPattern(timeSeriesType, timeSeriesTag, patternType, patternTag):
        ops.timeSeries(timeSeriesType, timeSeriesTag)
        ops.pattern(patternType, patternTag, timeSeriesTag)

    @staticmethod
    def addSelfWeight(elementTags):
        ops.eleLoad("-ele", *elementTags, "-type", "-selfWeight", 0, 0, 1)
    
    @staticmethod
    def addMassPushover_X_pos(elementTags):
        ops.eleLoad("-ele", *elementTags, "-type", "-selfWeight", 1, 0, 0)
    
    @staticmethod
    def addSW(gmshmodel, material_data):

        ops.timeSeries("Constant", 1)
        ops.pattern("Plain", 1, 1)

        for material_dictionary in material_data:
            name = material_dictionary['MaterialName']
            element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(name, gmshmodel)
            
            print("element tag")
            print(element_tags)
            mrho = material_dictionary['MassDensity'] # kg / m³
            rho = float(mrho*1e-12) # Ton / mm³

            print(mrho)

            for ele in element_tags:
                ops.eleLoad("-ele", ele, "-type", "-selfWeight", 0, 0, -9810*rho)
    
    
    @staticmethod
    def addMassPushover_Y_pos(gmshmodel, material_data):
        ops.timeSeries("Constant", 2)
        ops.pattern("Plain", 2, 2)

        for material_dictionary in material_data:
            name = material_dictionary['MaterialName']
            element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(name, gmshmodel)
            
            print("element tag")
            print(element_tags)
            mrho = material_dictionary['MassDensity'] # kg / m³
            rho = float(mrho*1e-12) # Ton / mm³

            print(mrho)

            for ele in element_tags:
                ops.eleLoad("-ele", ele, "-type", "-selfWeight", 0, 9810*rho, 0.)
    
    @staticmethod
    def apply_total_load_to_node(gmshmodel, material_data):

        ops.timeSeries("Linear", 2)
        ops.pattern("Plain", 2, 2)
        
        for material_dictionary in material_data:
            name = material_dictionary['MaterialName']
            mrho = material_dictionary['MassDensity'] # kg / m³
            rho = float(mrho*1e-12) # Ton / mm³
            element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(name, gmshmodel)
            number_of_elements = len(element_tags)

            for element_tag, node_tag in zip(element_tags, node_tags):
                volume = gmsh.model.mesh.getElementQualities([element_tag], "volume")
                volume = volume[0]
                volume = float(volume)
                load = volume*g*rho
                nodeLoad = (load/4)*0.3

                for node in node_tag:
                    ops.load(node, 0, nodeLoad, 0)

            # volumes = gmsh.model.mesh.getElementQualities(element_tags, "volume")
            # print(volumes)

            # totalVol = sum(volumes)
            
            # # totalVol = totalVol + volume
            # totalLoad = rho*g*totalVol
            # localLoad = totalVol/elementNnodes
            # for node in node_tags:
                        
            # # Apply lateral load in Y-direction (or X-direction if required)
            #     ops.load(node, 0, localLoad, 0)




    
class Model:

    def  create_solid_model(gmshmodel, material_data): #I need to add the load comb
        ops.model("basicBuilder", "-ndm", 3, "-ndf", 3)
        Geometry.add_elements_to_opensees(gmshmodel, material_data)
        element_tags = ops.getEleTags()

        BoundaryConditions.fix_nodes(gmshmodel)
  

        #ops.record()
        ops.printModel("-file", "filename", "Model.json", "Model.json")
        controlPoint = GeneralTools.getNodeWithHigherCoords(gmshmodel)
        controlPoint = int(controlPoint)
        print(controlPoint)

        #Loads.addSW(gmshmodel, material_data)
        ops.timeSeries("Linear", 1)
        ops.pattern("Plain", 1, 1)
        monotonicPushoverAnalysis.gravity_analysis(100, controlPoint, element_tags, gmshmodel)
        Loads.apply_total_load_to_node(gmshmodel, material_data)
   
        #Loads.addMassPushover_Y_pos(gmshmodel, material_data)
        
    
        ops.printModel("-file", "filename", "Model.json", "Model.json")


        monotonicPushoverAnalysis.horizontal_analysis(100, controlPoint, element_tags, gmshmodel)

 

        