import openseespy.opensees as ops
from .gmsh2opensees import * 
from .Materials import *



class generalTools:

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
    def get_solid_physical_groups(gmsh_model):
        """
        Retrieves all physical group names associated with solid (3D) entities in a Gmsh model.

        Parameters:
            gmsh_model (gmsh.model): The Gmsh model containing physical groups.

        Returns:
            List[str]: A list of names of all solid (3D) physical groups.
        """
        solid_physical_groups = [
            gmsh_model.getPhysicalName(dim, tag)
            for dim, tag in gmsh_model.getPhysicalGroups()
            if dim == 3  # Only include solids (3D physical groups)
        ]
        return solid_physical_groups

    @staticmethod
    def filter_materials_by_name(materials_dict, selected_names):
        """
        Filters a materials dictionary to include only the materials whose names are in the selected_names list.

        Parameters:
            materials_dict (dict): A dictionary of Material objects (keys are material names).
            selected_names (list): A list of material names to keep.

        Returns:
            dict: A filtered dictionary containing only the selected materials.
        """
        return {name: material for name, material in materials_dict.items() if name in selected_names}


class ModelBuilder:

    def __init__(self, ndm: int, ndf: int):
        """Initialize instance variables to store model configuration."""
        self.ndm = ndm  # Number of dimensions
        self.ndf = ndf  # Number of degrees of freedom
        
        # Initialize the model in OpenSees using instance variables
        ops.model("basicBuilder", "-ndm", self.ndm, "-ndf", self.ndf)

    def initialize_model(self):
        # Access the instance variables with self
        print(f"Building a solid model with {self.ndm} dimensions and {self.ndf} degrees of freedom")

class Nodes:

    @staticmethod
    def add_nodes(gmshmodel):
        nodeTags, coords, parametricCoord = gmshmodel.mesh.getNodes(-1, -1)

        # Add nodes to OpenSees
        add_nodes_to_ops(nodeTags, gmshmodel, remove_duplicates=True)



class Element:

    def __init__(self):
        self.node_tags = []
        self.element_tag = 0
        self.element_name = ""
        self.side_lenght = 0
    
    def get_element_side_lenght(element_tag: int):
        """This method returns the side lenght of a gmsh element given the element tag."""
        
        volume = gmsh.model.mesh.getElementQualities(element_tag, "volume") 
        side_length = (6 * math.sqrt(2) * volume) ** (1/3)
        
        return(side_length)
        
    @staticmethod
    def create_linear_elastic_element(gmshmodel, material, solid_material_tag) -> int:

        PaE = material.young_modulus #MPa - N/mm2
        E = (float(PaE))*1e6 #Pa - N/m2
        rho = material.density # kg / m³
        nu = material.poisson_ratio #--
        #add nD material to opensees
        ops.nDMaterial('ElasticIsotropic', solid_material_tag, E, nu, rho)

        print('Elastic material created with tag: ', solid_material_tag)
        #assign material to element
        physical_group = material.name

        element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)


        #Add node tags to Opensees
        for node_tag in node_tags:
            add_nodes_to_ops(node_tag, gmshmodel, True)

        #Add elements to opensees
        for ele_tag, ele_nodes in zip(element_tags, node_tags):
            ops.element('FourNodeTetrahedron', ele_tag, *ele_nodes, solid_material_tag, 0, 0, rho*g)
        
        return solid_material_tag
    
    @staticmethod 
    def create_plastic_damage_elements(gmshmodel, material, solid_material_tag) -> int:
        MPaE = material.young_modulus #MPa - N/mm2
        E = (float(MPaE))*1e6 #MPa - N/m2
        rho = material.density # kg / m³
        #rho = float(mrho*1e-9) # kg / mm³
        nu = material.poisson_ratio #--
        MPaFc = material.compressive_strength #MPa - N/mm2
        fc = float(MPaFc)*1e6 #Pa - N/m2
        MPaFt = material.tensile_strength #MPa - N/mm2
        ft = float(MPaFt)*1e6 #Pa - N/mm2
        if material.compression_fracture_energy != 0:
            Gc = float(material.compression_fracture_energy)
            Gc = float(Gc*1e6)
        else: 
            Gc = 15 + (0.43*fc) - 0.0036*(fc**2)
        
        if material.tensile_fracture_energy != 0:
            Gt = float(material.tensile_fracture_energy)
            Gt = float(Gt*1e6)
        else: 
            Gt = 0.025*(fc/10)**(0.7)
        
        if material.compressive_elastic_behaviour != 0:
            f0 = float(material.compressive_elastic_behaviour)
            f0 = float(f0*1e6)
        else:
            f0 = fc/3

        #Creating the geometry
        physical_group = material.name
        
        #Getting the gmsh model
        element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)

        #Add node tags to Opensees
        for node_tag in node_tags:
            add_nodes_to_ops(node_tag, gmshmodel, True)
        
        for element_tag, node_tag in zip(element_tags, node_tags):

            solid_material_tag = solid_material_tag + 1
            side_length = Element.get_element_side_lenght([element_tag])
            side_length = side_length[0]
            print(side_length)

            #Traction
            Te, Ts, Td = Masonry.ExponentialSoftening_Tension.tension(E, ft, Gt, side_length)

            #Compression
            Ce, Cs, Cd = Masonry.BezierCurve_Compression.Compression(E, f0, fc, Gc, side_length)

            #Definition of the OpenSees material
            
            ops.nDMaterial('ASDConcrete3D', solid_material_tag,
            E, nu, # elasticity
            '-Te', *Te, '-Ts', *Ts, '-Td', *Td, # tensile law
            '-Ce', *Ce, '-Cs', *Cs, '-Cd', *Cd, # compressive law
            )

            print('Plastic material created with tag: ', solid_material_tag)

            #Add the tetrahedron

            ops.element('FourNodeTetrahedron', element_tag, *node_tag, solid_material_tag, 0, 0, rho*g)
            print('Nonlinear element added!')
    
        return (solid_material_tag)

    @staticmethod        
    def add_elements_to_opensees(gmshmodel, materials_dict):
        """This method create the opensees elements to add to the model."""  
        names = generalTools.get_solid_physical_groups(gmshmodel)
        materials_dict = generalTools.filter_materials_by_name(materials_dict, names)
        tags = []
        for matname, material in materials_dict.items():

            #Get all the tags that will be in OpenSees - needed to show the results in Gmsh
            physical_group = matname

            element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)
            element_tags.append(element_tags)
            
            #Create the material
            solid_material_tag = addUniqueSolidMaterialTags(tags)

            #Define Material Type
            if material.material_model_type == 'LinearElastic':
                tag = Element.create_linear_elastic_element(gmshmodel, material, solid_material_tag)                      
            if material.material_model_type == 'PlasticDamage':
                tag = Element.create_plastic_damage_elements(gmshmodel, material, solid_material_tag)  
            tags.append(tag)         

        return element_tags

class BoundaryConditions:

    @staticmethod
    def fixNodes(gmshmodel):
        #Create boundary conditions
        elementTags2, nodeTags2, elementName2, elementNnodes2 = get_elements_and_nodes_in_physical_group("Fix", gmshmodel)
        fix_nodes(nodeTags2, 'XYZ')

class Loads:
    def __init__(self, timeSeriesType: str, timeSeriesTag: int, patternType: str, patternTag: int):
        self.timeSeriesType = timeSeriesType
        self.timeSeriesTag = timeSeriesTag
        self.patternType = patternType
        self.patternTag = patternTag

        ops.timeSeries(timeSeriesType, timeSeriesTag)
        ops.pattern(patternType, patternTag, timeSeriesTag)


    def addSelfWeight(elementTags):
        ops.eleLoad("-ele", *elementTags, "-type", "-selfWeight", 0, 0, -1)
    
    def addMassPushover_X_pos(elementTags):
        ops.eleLoad("-ele", *elementTags, "-type", "-selfWeight", 1, 0, 0)
    
    def addMassPushover_X_neg(elementTags):
        ops.eleLoad("-ele", *elementTags, "-type", "-selfWeight", -1, 0, 0)
    
    
    

    def addLiveLoads(gmshmodel):
        elementTags3, nodeTags3, elementName3, elementNnodes3 = get_elements_and_nodes_in_physical_group("Loaded", gmshmodel)

        #here I need to add more stuff


