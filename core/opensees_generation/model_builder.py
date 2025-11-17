from core.config import G
from openseespy.opensees import *
from external.gmsh2opensees import *
from models.damage_law import *
from utils.gmsh_helpers import get_solid_physical_groups
from utils.dict_helper import filter_materials_by_name
from utils.tag_manager import add_unique_solid_material_tag
import gmsh
import math


class ModelBuilder:
    
    def __init__(self, ndm: int, ndf: int):
        """Initialize instance variables to store model configuration."""
        self.ndm = ndm  # Number of dimensions
        self.ndf = ndf  # Number of degrees of freedom
        
        # Initialize the model in OpenSees using instance variables
        model("basicBuilder", "-ndm", self.ndm, "-ndf", self.ndf)

    def initialize_model(self):
        # Access the instance variables with self
        print(f"Building a solid model with {self.ndm} dimensions and {self.ndf} degrees of freedom")


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
    def create_linear_elastic_element(gmshmodel, material, solid_material_tag, element_tags, node_tags) -> int:

        E = material.young_modulus #MPa - N/mm2
        #E = (float(PaE))*1e6 #Pa - N/m2
        rho = material.density # kg / m³
        rho = float(rho*1e-12) # Ton / mm³
        nu = material.poisson_ratio #--
        #add nD material to opensees
        nDMaterial('ElasticIsotropic', solid_material_tag, E, nu, rho)

        #print('Elastic material created with tag: ', solid_material_tag)
        #assign material to element
        physical_group = material.name
        for node_tag in node_tags:
            add_nodes_to_ops(node_tag, gmshmodel, True)    

        #Add elements to opensees
        for ele_tag, ele_nodes in zip(element_tags, node_tags):
            element('FourNodeTetrahedron', ele_tag, *ele_nodes, solid_material_tag, 0, 0, rho*G)
            
        return solid_material_tag
    
    @staticmethod 
    def create_plastic_damage_elements(gmshmodel, material, solid_material_tag, element_tags, node_tags) -> int:
        MPaE = material.young_modulus #MPa - N/mm2
        E = (float(MPaE)) #MPa - N/m2
        rho = material.density # kg / m³
        rho = float(rho*1e-12) # Ton / mm³
        nu = material.poisson_ratio #--
        fc = material.compressive_strength #MPa - N/mm2
        #fc = float(MPaFc)*1e6 #Pa - N/m2
        ft = material.tensile_strength #MPa - N/mm2
        #ft = float(MPaFt)*1e6 #Pa - N/mm2
        if material.compression_fracture_energy != 0:
            Gc = float(material.compression_fracture_energy)
            #Gc = float(Gc*1e6)
        else: 
            Gc = 15 + (0.43*fc) - 0.0036*(fc**2)
        
        if material.tensile_fracture_energy != 0:
            Gt = float(material.tensile_fracture_energy)
            #Gt = float(Gt*1e6)
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
        #element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)

        #Add node tags to Opensees
        
        add_nodes_to_ops(node_tags, gmshmodel, True)

        print(f"Gt = {Gt}")
        print(f"Gc = {Gc}")
        
        for element_tag, node_tag in zip(element_tags, node_tags):

            solid_material_tag = solid_material_tag + 1
            side_length = Element.get_element_side_lenght([element_tag])
            side_length = side_length[0]

            #print(f"side lenght = {side_length}")

            #Traction
            Te, Ts, Td = ConstitutiveLaws.ExponentialSoftening_Tension.tension(E, ft, Gt, side_length)

            #Compression
            Ce, Cs, Cd = ConstitutiveLaws.BezierCurve_Compression.compression(E, f0, fc, Gc, side_length)


            #Definition of the OpenSees material
            
            nDMaterial('ASDConcrete3D', solid_material_tag,
            E, nu, # elasticity
            '-Te', *Te, '-Ts', *Ts, '-Td', *Td, # tensile law
            '-Ce', *Ce, '-Cs', *Cs, '-Cd', *Cd, # compressive law
            'implex', 'autoRegularization', side_length
            )

            #print('Plastic material created with tag: ', solid_material_tag)

            #Add the tetrahedron

            element('FourNodeTetrahedron', element_tag, *node_tag, solid_material_tag, 0, 0, rho*G)
            #print('Nonlinear element added!')
    
        return (solid_material_tag)

    @staticmethod              
    def add_elements_to_opensees(gmshmodel, materials_dict):
        """This method create the opensees elements to add to the model."""          
        names = get_solid_physical_groups(gmshmodel)
        materials_dict = filter_materials_by_name(materials_dict, names)
        
        tags = []
        for matname, material in materials_dict.items():

            #Get all the tags that will be in OpenSees - needed to show the results in Gmsh
            physical_group = matname


            element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)
            element_tags.append(element_tags)
                        
            #Create the material
            solid_material_tag = add_unique_solid_material_tag(tags)

            #Define Material Type
            if material.material_model_type == 'LinearElastic':
                tag = Element.create_linear_elastic_element(gmshmodel, material, solid_material_tag, element_tags, node_tags)                      
            elif material.material_model_type == 'PlasticDamage':
                #tag = Element.create_linear_elastic_element(gmshmodel, material, solid_material_tag, element_tags, node_tags)
                tag = Element.create_plastic_damage_elements(gmshmodel, material, solid_material_tag, element_tags, node_tags)  
            tags.append(tag)         

        return element_tags
    
    #@staticmethod              
    # def add_filtered_elements_to_opensees(gmshmodel, materials_dict, allowed_tags=None, pid):
    #     """Create OpenSees elements for the model, optionally filtering by element tag."""
    #     names = get_solid_physical_groups(gmshmodel)
    #     materials_dict = filter_materials_by_name(materials_dict, names)
        
    #     all_tags = []
    #     for matname, material in materials_dict.items():
    #         print(matname)
    #         print(material)

    #         # Get element info
    #         physical_group = matname
    #         element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)

    #         # ✅ Apply filtering here if a list of allowed_tags is provided
    #         if allowed_tags is not None:
    #             filtered_elements = []
    #             filtered_nodes = []

    #             for i, tag in enumerate(element_tags):
    #                 if tag in allowed_tags:
    #                     filtered_elements.append(tag)
    #                     start = i * elementNnodes
    #                     end = (i + 1) * elementNnodes
    #                     filtered_nodes.extend(node_tags[start:end])

    #             element_tags = filtered_elements
    #             node_tags = filtered_nodes
    #             print("---------------------------------------------------------------")
    #             print(element_tags)
    #             print(node_tags)
    #             print("---------------------------------------------------------------")
    #             if not element_tags:
    #                 print(f"⚠️ No elements from physical group '{matname}' in this partition.")
    #                 continue

    #         # Create the material and elements
    #         solid_material_tag = add_unique_solid_material_tag(all_tags)

    #         if material.material_model_type == 'LinearElastic':
    #             tag = Element.create_linear_elastic_element(gmshmodel, material, solid_material_tag)
    #         elif material.material_model_type == 'PlasticDamage':
    #             tag = Element.create_plastic_damage_elements(gmshmodel, material, solid_material_tag)

    #         all_tags.append(tag)

    #     return all_tags
    @staticmethod
    def add_filtered_elements_to_opensees(gmshmodel, materials_dict, allowed_tags=None, pid=None):
        """Create OpenSees elements for the model, optionally filtering by element tag."""
        names = get_solid_physical_groups(gmshmodel)
        materials_dict = filter_materials_by_name(materials_dict, names)

        all_tags = []
        for matname, material in materials_dict.items():
            print(f"[PID {pid}] Processing material group: {matname}")
            print(f"[PID {pid}] Material info: {material}")

            # Get element info
            physical_group = matname
            element_tags, node_tags, element_name, elementNnodes = get_elements_and_nodes_in_physical_group(physical_group, gmshmodel)

            # ✅ Apply filtering here if a list of allowed_tags is provided
            if allowed_tags is not None:
                filtered_elements = []
                filtered_nodes = []

                for node_tag, element_tag in zip(node_tags, element_tags):
                    if element_tag in allowed_tags:
                        filtered_elements.append(element_tag)
                        filtered_nodes.append(node_tag)

                element_tags = filtered_elements
                node_tags = filtered_nodes

                # print("---------------------------------------------------------------")
                # print(f"[PID {pid}] Filtered element tags: {element_tags}")
                # print(f"[PID {pid}] Filtered node tags: {node_tags}")
                # print("---------------------------------------------------------------")

                if not element_tags:
                    print(f"[PID {pid}] ⚠️ No elements from physical group '{matname}' in this partition.")
                    continue

                # Create the material and elements
                solid_material_tag = add_unique_solid_material_tag(all_tags)

                if material.material_model_type == 'LinearElastic':
                    tag = Element.create_linear_elastic_element(gmshmodel, material, solid_material_tag, element_tags, node_tags)
                elif material.material_model_type == 'PlasticDamage':
                    tag = Element.create_plastic_damage_elements(gmshmodel, material, solid_material_tag, element_tags, node_tags)

                all_tags.append(tag)

        return all_tags


class BoundaryConditions:

    @staticmethod
    def fix_nodes(gmshmodel):
        """Fix only nodes that exist in OpenSees from the 'Fix' physical group."""
        
        # ✅ Step 1: Get nodes from the 'Fix' physical group
        elementTags2, nodeTags2, elementName2, elementNnodes2 = get_elements_and_nodes_in_physical_group("Fix", gmshmodel)
        
        # # ✅ Step 2: Filter out nodes that do not exist in OpenSees
        # valid_nodes = []
        # for node in nodeTags2:
        #     try:
        #         _ = nodeCoord(node)  # Check if node exists in OpenSees
        #         valid_nodes.append(node)
        #     except:
        #         print(f"🚨 Warning: Node {node} exists in Gmsh but not in OpenSees. Skipping fixation.")

        # # ✅ Step 3: Ensure valid nodes exist before applying fix
        # if len(valid_nodes) == 0:
        #     print("🚨 Warning: No valid OpenSees nodes found in 'Fix' physical group. Skipping fixation.")
        #     return []

        # ✅ Step 4: Apply fix constraints only to valid nodes
        fix_nodes(nodeTags2, 'XYZ')

        return nodeTags2  # Return only the nodes that were fixed


class Loads:
    def __init__(self, timeSeriesType: str, timeSeriesTag: int, patternType: str, patternTag: int):
        self.timeSeriesType = timeSeriesType
        self.timeSeriesTag = timeSeriesTag
        self.patternType = patternType
        self.patternTag = patternTag

        timeSeries(timeSeriesType, timeSeriesTag)
        pattern(patternType, patternTag, timeSeriesTag)

    @staticmethod
    def addSelfWeight(elementTags):
        eleLoad("-ele", *elementTags, "-type", "-selfWeight", 0, 0, -1)
    
    @staticmethod
    def addMassPushover_X_pos(elementTags):
        eleLoad("-ele", *elementTags, "-type", "-selfWeight", 1, 0, 0)
    
    @staticmethod
    def addMassPushover_X_neg(elementTags):
        eleLoad("-ele", *elementTags, "-type", "-selfWeight", -1, 0, 0)
    
    
    

    # def addLiveLoads(gmshmodel):
    #     elementTags3, nodeTags3, elementName3, elementNnodes3 = get_elements_and_nodes_in_physical_group("Loaded", gmshmodel)

    #     #here I need to add more stuff


