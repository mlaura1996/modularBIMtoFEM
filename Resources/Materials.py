import openseespy.opensees as ops
from .gmsh2opensees import * 
import gmsh
import numpy as np
import math
import matplotlib.pyplot as plt
from  .ConstitutiveLaws import ConstitutiveLaws as Masonry

#constants
g = -9.810 #mm/s2

def addUniqueSolidMaterialTags(excluded_list):

    #This function returns an incremental number that is not in the excluded_list - needed for the tags of the materials

    excluded_set = set(excluded_list)  # Convert list to set for O(1) lookups
    max_excluded = max(excluded_set) if excluded_set else -1  # Find the maximum value in the excluded list
    current_num = max_excluded + 1

    while current_num in excluded_set:
        current_num = current_num +1

    return current_num

def getElementHeights(gmshmodel):
    #Getting the gmsh model to calibrate the fracture energy
    elementTags, nodeTags, elementName, elementNnodes = get_elements_and_nodes_in_physical_group('StructuralMasonry3', gmshmodel)
    volumes = gmsh.model.mesh.getElementQualities(elementTags, "volume")
    print(len(elementTags))
    print(len(volumes))
    for volume in volumes:
        side_length = (6 * math.sqrt(2) * volume) ** (1/3)
        print(side_length)

        return side_length
    
def CreateLinearElasticModel(gmshmodel, dictionary, solidMaterialTag):
    PaE = dictionary['YoungModulus'] #Pa - N/m2
    E = (float(PaE))*1e-6 #MPa - N/mm2
    mrho = dictionary['MassDensity'] # kg / m³
    rho = float(mrho*1e-9) # kg / mm³
    nu = dictionary['PoissonRatio'] #--

    #add material to opensees
    ops.nDMaterial('ElasticIsotropic', solidMaterialTag, E, nu, rho)
    print('Elastic material created with tag: ', solidMaterialTag)

    
    #assign material to element
    PhysicalGroup = dictionary['MaterialName']
    elementTags, nodeTags, elementName, elementNnodes = get_elements_and_nodes_in_physical_group(PhysicalGroup, gmshmodel)

    #Add elements to opensees
    for eleTag, eleNodes in zip(elementTags, nodeTags):
        ops.element('FourNodeTetrahedron', eleTag, *eleNodes, solidMaterialTag, 0, 0, rho*g)

    print('Linear elements added!')
    
    return(solidMaterialTag)

def CreatePlasticDamageModel(gmshmodel, dictionary, solidMaterialTag):

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
        print('Nonlinear element added!')

        
    return solidMaterialTag




