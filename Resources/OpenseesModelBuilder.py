import openseespy.opensees as ops
from gmsh2opensees import * 
from .Materials import *

class ModelBuilder:
    def __init__(self, ndm, ndf):
        # Initialize instance variables to store model configuration
        self.ndm = ndm  # Number of dimensions
        self.ndf = ndf  # Number of degrees of freedom
        
        # Initialize the model in OpenSees using instance variables
        ops.model("basicBuilder", "-ndm", self.ndm, "-ndf", self.ndf)

    def initializeModel(self):
        # Access the instance variables with self
        print(f"Building a solid model with {self.ndm} dimensions and {self.ndf} degrees of freedom")

class Element:
    def __init__(self):
        self.nodeTags = []
        self.elementTags = []
        self.elementName = []
    
    @staticmethod
    def addUniqueSolidMaterialTag(excluded_list):
        #This function returns an incremental number that is not in the excluded_list - needed for the tags of the materials
        excluded_set = set(excluded_list)  # Convert list to set for O(1) lookups
        max_excluded = max(excluded_set) if excluded_set else -1  # Find the maximum value in the excluded list
        current_num = max_excluded + 1

        while current_num in excluded_set:
            current_num = current_num + 1

        return current_num

    def createLinearElasticElements(gmshmodel, dictionary, solidMaterialTag):
        PaE = dictionary['YoungModulus'] #Pa - N/m2
        E = (float(PaE))*1e-6 #MPa - N/mm2
        mrho = dictionary['MassDensity'] # kg / m³
        rho = float(mrho*1e-9) # kg / mm³
        nu = dictionary['PoissonRatio'] #--
        #add nD material to opensees
        ops.nDMaterial('ElasticIsotropic', solidMaterialTag, E, nu, rho)

        print('Elastic material created with tag: ', solidMaterialTag)
            #assign material to element
        PhysicalGroup = dictionary['MaterialName']

        elementTags, nodeTags, elementName, elementNnodes = get_elements_and_nodes_in_physical_group(PhysicalGroup, gmshmodel)

            #Add node tags to Opensees
        for nodeTag in nodeTags:
            add_nodes_to_ops(nodeTag, gmshmodel, True)

        #Add elements to opensees
        for eleTag, eleNodes in zip(elementTags, nodeTags):
            ops.element('FourNodeTetrahedron', eleTag, *eleNodes, solidMaterialTag, 0, 0, rho*g)

        print('FourNodeTetrahedron element with linear elastic material added.')
        
        return(solidMaterialTag)

    def createPlasticDamageElements(gmshmodel, dictionary, solidMaterialTag):

        PaE = dictionary['YoungModulus'] #Pa - N/m2
        E = (float(PaE))*1e-6 #MPa - N/mm2
        mrho = dictionary['MassDensity'] # kg / m³
        rho = float(mrho*1e-9) # kg / mm³
        nu = dictionary['PoissonRatio'] #--
        PaFc = dictionary['CompressiveStrength'] #Pa - N/m2
        fc = float(PaFc)*1e-6 #MPa - N/mm2
        PaFt = dictionary['TensileStrength'] #Pa - N/m2
        ft = float(PaFt)*1e-6 #MPa - N/mm2
        if 'CompressionFractureEnergy' in dictionary:
            Gc = float(dictionary['CompressionFractureEnergy'])
        else: 
            Gc = 15 + (0.43*fc) - 0.0036*(fc**2)
        
        if 'TensionFractureEnergy' in dictionary:
            Gt = float(dictionary['TensionFractureEnergy'])
        else: 
            Gt = 0.025*(fc/10)**(0.7)
        
        if 'CompressiveStressElasticBehaviour' in dictionary:
            f0 = float(dictionary['CompressiveStressElasticBehaviour'])
        else:
            f0 = fc/3

        #Creating the geometry
        PhysicalGroup = dictionary['MaterialName']
        
        #Getting the gmsh model
        elementTags, nodeTags, elementName, elementNnodes = get_elements_and_nodes_in_physical_group(PhysicalGroup, gmshmodel)

        #Add node tags to Opensees
        for nodeTag in nodeTags:
            add_nodes_to_ops(nodeTag, gmshmodel, True)

        volumes = gmsh.model.mesh.getElementQualities(elementTags, "volume")
        for volume, elementTag, nodeTag in zip(volumes, elementTags, nodeTags):
            

            solidMaterialTag = solidMaterialTag + 1
            side_length = (6 * math.sqrt(2) * volume) ** (1/3)
            #print(side_length)

            #Traction
            Te, Ts, Td = Masonry.ExponentialSoftening_Tension.tension(E, ft, Gt, side_length)

            #Compression
            Ce, Cs, Cd = Masonry.BezierCurve_Compression.Compression(E, f0, fc, Gc, side_length)

            #Definition of the OpenSees material
            
            ops.nDMaterial('ASDConcrete3D', solidMaterialTag,
            E, nu, # elasticity
            '-Te', *Te, '-Ts', *Ts, '-Td', *Td, # tensile law
            '-Ce', *Ce, '-Cs', *Cs, '-Cd', *Cd, # compressive law
            )

            print('Plastic material created with tag: ', solidMaterialTag)

            #Add the tetrahedron

            ops.element('FourNodeTetrahedron', elementTag, *nodeTag, solidMaterialTag, 0, 0, rho*g)
            #print('Nonlinear element added!')

            
        return solidMaterialTag
            
    def addElementsToOpenSees(gmshmodel, data):
            
        tags = []
        for dictionary in data:

            #Get all the tags that will be in OpenSees - needed to show the results in Gmsh
            PhysicalGroup = dictionary['MaterialName']

            elementTags, nodeTags, elementName, elementNnodes = get_elements_and_nodes_in_physical_group(PhysicalGroup, gmshmodel)
            elementTags.append(elementTags)
            
            #Create the material
            solidMaterialTag = addUniqueSolidMaterialTags(tags)

            #Define Material Type
            if dictionary['MaterialModelType'] == 'LinearElastic':
                tag = Element.createLinearElasticElements(gmshmodel, dictionary, solidMaterialTag)                      
            if dictionary['MaterialModelType'] == 'PlasticDamage':
                tag = Element.createPlasticDamageElements(gmshmodel, dictionary, solidMaterialTag)  
            tags.append(tag)         

        return elementTags, nodeTags

class Constraints:
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
    

    def addLiveLoads(gmshmodel):
        elementTags3, nodeTags3, elementName3, elementNnodes3 = get_elements_and_nodes_in_physical_group("Loaded", gmshmodel)

        #here I need to add more stuff


