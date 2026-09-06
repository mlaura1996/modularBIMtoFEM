from core.config import G
from openseespy.opensees import *
from external.gmsh2opensees import *
from models.damage_law import *
from utils.gmsh_helpers import get_solid_physical_groups
from utils.dict_helper import filter_materials_by_name
from utils.tag_manager import add_unique_solid_material_tag
import gmsh
import math
import numpy as np


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
        E = (float(E))*1e6 #Pa - N/m2
        rho = material.density # kg / m³
        #rho = float(rho*1e-12) # Ton / mm³
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
        """Builds ASDConcrete3D + FourNodeTetrahedron elements.

        UNIT FIX (see chat log for the full trace): this function used to
        leave E/fc/ft in MPa and convert density to ton/mm^3 - i.e.
        calibrated for an N-mm-ton system - while add_nodes_to_ops() feeds
        it node coordinates straight from the gmsh mesh, which are in
        METRES (core/config.py's STEP_UNIT='M', confirmed empirically on
        the real Castelnuovo geometry throughout this session: wall
        coordinates like (17.88, 5.93, 4.1), not (17880, 5930, 4100)).
        FourNodeTetrahedron computes stiffness/mass directly from nodal
        coordinates with no unit conversion of its own, so feeding it
        mm-calibrated material constants against metre-scale coordinates
        silently produced wrong element volumes/mass/stiffness (off by
        factors around 10^9) - nothing errors, the analysis just runs on
        the wrong physics. Also fed the crack-band regularisation length
        (side_length, itself in metres, from Element.get_element_side_lenght
        -> gmsh's own volume metric) into the same formulas as E/fc/ft/Gc/Gt
        in mm-calibrated units, corrupting the constitutive law itself, not
        just the FE assembly.

        Now consistently SI (Pa, m, kg, N) throughout, matching
        create_linear_elastic_element's convention (which was already
        correct - E converted to Pa, density left in kg/m^3, no fix needed
        there).
        """
        # Gc/Gt fallback formulas need fc in MPa - they are NOT
        # unit-independent physical laws, they're specific empirical curve
        # fits (Gc: CEB-FIP Model Code 90 compressive fracture energy,
        # Gf=15+0.43*fc-0.0036*fc^2, valid for fc in MPa between 12-80 MPa -
        # confirmed by web search, see chat log). Their raw numeric output
        # is in N/mm, not N/m or Pa*m - cross-checked against
        # PROJECT_BRIEF.md's own Chapter 6 (SERA-AIMS) reference values
        # (explicitly stated to be in the N-mm-t system): at fc=1.30 MPa the
        # Gt formula below gives 0.0056 N/mm vs. the brief's calibrated
        # Gt=0.006 N/mm - close enough (~7%) to confirm the unit, not close
        # enough to expect (a generic code-formula fallback isn't meant to
        # reproduce one specific experimental calibration exactly).
        fc_MPa = material.compressive_strength
        ft_MPa = material.tensile_strength

        if material.compression_fracture_energy != 0:
            Gc_Nmm = float(material.compression_fracture_energy)
        else:
            Gc_Nmm = 15 + (0.43 * fc_MPa) - 0.0036 * (fc_MPa ** 2)

        if material.tensile_fracture_energy != 0:
            Gt_Nmm = float(material.tensile_fracture_energy)
        else:
            Gt_Nmm = 0.025 * (fc_MPa / 10) ** 0.7

        # Now convert everything to SI (Pa, m, N) for the actual element/
        # material creation below. 1 MPa = 1e6 Pa; 1 N/mm = 1000 N/m.
        E = float(material.young_modulus) * 1e6
        fc = fc_MPa * 1e6
        ft = ft_MPa * 1e6
        Gc = Gc_Nmm * 1000
        Gt = Gt_Nmm * 1000
        rho = material.density  # kg/m^3 already - no conversion needed
        nu = material.poisson_ratio

        if material.compressive_elastic_behaviour != 0:
            f0 = float(material.compressive_elastic_behaviour) * 1e6  # MPa -> Pa
        else:
            f0 = fc / 3  # fc is already in Pa at this point

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
    def _get_volume_elements(volume_tag, node_substitution=None):
        """Per-volume equivalent of get_elements_and_nodes_in_physical_group
        (external/gmsh2opensees/g2o_elements_functions.py) - same element
        type / node-shape handling, but scoped to a single gmsh volume
        entity instead of a whole physical group, so that a wall-to-wall
        interface split (core.mesh_generation.wall_interfaces.NodeSplitter)
        can be applied to just one side of a shared interface without
        touching the neighbouring volume's connectivity.

        node_substitution: optional {volume_tag: {orig_node_tag: dup_node_tag}}
        (NodeSplitter.create_duplicate_nodes's return value). Only affects
        which node tag shows up in the element *connectivity* - node
        creation for the substituted (duplicate) tags already happened in
        NodeSplitter, and add_nodes_to_ops silently skips tags already
        defined in OpenSees, so this doesn't need to special-case anything
        node-creation-side.
        """
        element_types, element_tags, node_tags_flat = gmsh.model.mesh.getElements(dim=3, tag=volume_tag)
        if len(element_types) == 0:
            return [], []
        if len(element_types) != 1:
            print("Cannot handle more than one element type per volume at this moment.")
            exit(-1)

        _, nnodes = get_element_info_from_elementType(element_types[0])
        node_tags = np.array(node_tags_flat[0], dtype=int).reshape((-1, nnodes))

        sub = (node_substitution or {}).get(volume_tag, {})
        if sub:
            node_tags = np.array([[sub.get(int(n), int(n)) for n in row] for row in node_tags])

        return element_tags[0].tolist(), node_tags.tolist()

    @staticmethod
    def add_elements_to_opensees(gmshmodel, materials_dict, node_substitution=None):
        """This method create the opensees elements to add to the model.

        node_substitution (optional): {volume_tag: {orig_node_tag: dup_node_tag}},
        from core.mesh_generation.wall_interfaces.NodeSplitter.create_duplicate_nodes.
        When given, the tetrahedra of any volume acting as a confirmed
        interface's "split side" are built against the duplicate node
        instead of the one shared with its neighbour, so the
        zeroLengthContactASDimplex elements built on top of those
        duplicates (ContactInterfaceGenerator.generate) actually decouple
        the two sides instead of connecting to a rigidly-shared node.
        """
        names = get_solid_physical_groups(gmshmodel)
        materials_dict = filter_materials_by_name(materials_dict, names)

        tags = []
        all_element_tags = []
        for matname, material in materials_dict.items():

            #Get all the volumes in this material's physical group, and flatten
            #their element/node connectivity together - same aggregate
            #get_elements_and_nodes_in_physical_group used to produce, just
            #built per volume so node_substitution can be applied per volume
            #before flattening. This keeps create_linear_elastic_element's
            #single nDMaterial() call, and create_plastic_damage_elements'
            #per-element regularized material, both exactly as before when
            #node_substitution is None.
            dim, pg_tag = get_physical_groups_map(gmshmodel)[matname]
            volumes = gmshmodel.getEntitiesForPhysicalGroup(dim, pg_tag)

            element_tags, node_tags = [], []
            for volume in volumes:
                v_element_tags, v_node_tags = Element._get_volume_elements(volume, node_substitution)
                element_tags.extend(v_element_tags)
                node_tags.extend(v_node_tags)

            if not element_tags:
                continue

            #Create the material
            solid_material_tag = add_unique_solid_material_tag(tags)

            #Define Material Type
            if material.material_model_type == 'LinearElastic':
                tag = Element.create_linear_elastic_element(gmshmodel, material, solid_material_tag, element_tags, node_tags)
            elif material.material_model_type == 'PlasticDamage':
                tag = Element.create_plastic_damage_elements(gmshmodel, material, solid_material_tag, element_tags, node_tags)
            tags.append(tag)
            all_element_tags.extend(element_tags)

        return all_element_tags
    
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


