import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import OCC.Core.TopoDS
from OCC.Core.BRepGProp import brepgprop_VolumeProperties
from OCC.Core.GProp import GProp_GProps
import re
from Resources import Geometry

# geometry settings
settings = ifcopenshell.geom.settings()
settings.set(settings.USE_PYTHON_OPENCASCADE, True) #generalinfo


class GeometryForVolume:
    @staticmethod
    def get_shape(slab):
        product = ifcopenshell.geom.create_shape(settings, slab)
        shape = OCC.Core.TopoDS.TopoDS_Iterator(product.geometry).Value()
        shape = Geometry.get_lowest_solid(shape)
        print(shape)
        return shape

    @staticmethod
    def get_volume_from_shape(shape):
        props = GProp_GProps()
        brepgprop_VolumeProperties(shape, props)
        return props.Mass()

class Aggregation:
    @staticmethod
    def has_aggregation(element):
        """
        Check if the given IFC element has an aggregation (IsDecomposedBy relationship).

        Args:
            element (IfcElement): An IFC element to check.

        Returns:
            bool: True if the element has an aggregation, False otherwise.
        """
        return bool(element.IsDecomposedBy)
    

    @staticmethod
    def get_aggregated_elements(element):
        """
        Retrieve the aggregated elements of a given IFC element if it has an aggregation.

        Args:
            element (IfcElement): An IFC element to retrieve aggregated elements from.

        Returns:
            list: A list of aggregated elements, or the original element if none are found.
        """
        if not Aggregation.has_aggregation(element):
            return [element]

        aggregated_elements = []
        for rel in element.IsDecomposedBy:
            aggregated_elements.extend(rel.RelatedObjects)
        return aggregated_elements

class QuantitySet:
    @staticmethod  
    def get_complex_quantity(element):
        """
        Extracts material names and their associated thicknesses from the given IFC element.

        The function iterates over the relationships of the element to identify "IfcElementQuantity".
        It then looks for "IfcPhysicalComplexQuantity" layers, retrieves their names (representing
        material names), and extracts the thickness value from the associated quantities.

        Returns:
            list of dict: A list of dictionaries where each dictionary contains a material name 
                         and its associated thickness. Example:
                         [{"material_name": "Concrete", "thickness": 0.25}, ...]
        """
        element_info = []
        
        for rel in element.IsDefinedBy:
            if rel.RelatingPropertyDefinition.is_a() == "IfcElementQuantity":
                quantities = rel.RelatingPropertyDefinition.Quantities
                for layer in quantities:
                    if layer.is_a() == "IfcPhysicalComplexQuantity":
                        material_name = layer.Name
                        # Assuming thickness is the 4th quantity in HasQuantities
                        quantity_length = layer.HasQuantities[0]
                        thickness = quantity_length[3]  # Adjust index as necessary based on actual structure
                        element_info.append({"material_name": material_name, "thickness": thickness})
        
        return element_info
        
    
class PropertySet:
    pass
    
class MaterialsAndThicknesses:

    @staticmethod
    def get_thickness_from_pset(element):
        if element.is_a() == "IfcBeam":
            psets = ifcopenshell.util.element.get_psets(element)
            thickness = psets["Pset_BeamCommon"]["CrossSectionHeight"]
        elif element.is_a() == "IfcColumn":
            psets = ifcopenshell.util.element.get_psets(element)
            thickness = psets["Pset_ColumnCommon"]["CrossSectionHeight"]
        elif element.is_a() == "IfcRoof":
            psets = ifcopenshell.util.element.get_psets(element)
            thickness = psets["Pset_RoofCommon"]["Thickness"]
        if thickness is not None:
             thickness = thickness/1000

        return thickness
    
    @staticmethod
    def get_thickness_from_qset(element):
        qsets = ifcopenshell.util.element.get_psets(element, qtos_only=True)
        if element.is_a() == "IfcWall":
            thickness = qsets['Qto_WallBaseQuantities'].get('Width', 0)
        elif element.is_a() == "IfcSlab":
            slab_qset = qsets.get('Qto_SlabBaseQuantities', {})
            thickness = slab_qset.get('Thickness') or slab_qset.get('Depth') 
            if thickness == 0:
                thickness = 0.05
                print(f"Warning: No thickness or depth found for element {element.Name}")
        elif element.is_a() == "IfcFooting":
            thickness = qsets['Qto_FootingBaseQuantities'].get('Width', 0)
        print(type(thickness))
        # if thickness is not None:
        #     thickness = thickness*1000
        return thickness

    @staticmethod
    def get_roof_thickness_from_pset(element):
        psets = ifcopenshell.util.element.get_psets(element)
        thickness = psets["Dimensions"]["Thickness"]
        if thickness is not None:
            thickness = thickness/1000
        else:
            thickness = 0.05
            
        return thickness

    @staticmethod
    def get_door_windows_thickness_from_pset(element):
        psets = ifcopenshell.util.element.get_psets(element)
        thickness = psets["Structural"]["LintelThickness"]
        if thickness is not None:
             thickness = thickness/1000
        return thickness

    @staticmethod    
    def get_info_from_material_layer(material_layer):
        """
        Extracts and returns the material name and thickness from a material layer object.

        Args:
            material_layer: An object representing a material layer, 
                            expected to have properties 'LayerThickness' and 'Material.Name'.

        Returns:
            tuple: A tuple containing:
                - material_name (str): The name of the material.
                - thickness (str): The thickness of the material layer as a string.
        """
        thickness = material_layer.LayerThickness
        material_name = material_layer.Material.Name
        thickness = str(thickness)

        return material_name, thickness
    
    @staticmethod
    def get_dimensions_from_profile(profile):
        """
        Extracts the dimensions from a profile and determines the thickness.

        Parameters:
        - profile: The profile object to be evaluated. It is expected to be of type "IfcRectangleProfileDef" 
                   or a similar profile type that provides dimension attributes.

        Returns:
        - The thickness of the profile, calculated as the maximum of its `XDim` and `YDim` attributes 
          (converted to floats) if the profile is of type "IfcRectangleProfileDef".
        - None if the profile type is not supported.
        """
        profile_type = profile.Profile

        if profile_type.is_a() == "IfcRectangleProfileDef":
            xDim = float(profile_type.XDim)                           
            yDim = float(profile_type.YDim)
            thickness = max(xDim, yDim)                 
        else: 
            thickness = None
            print("Type of profile not supported. Check IDS specifications.")    
        return thickness
    
    @staticmethod
    def get_info_from_material_profile(material_profile):
        """
        Extracts and returns the material name and profile from a material profile object.

        Args:
            material_profile: An object representing a material profile,
                            expected to have properties 'Profile' and 'Material.Name'.

        Returns:
            tuple: A tuple containing:
                - material_name (str): The name of the material.
                - profile: The profile thickness (data type depends on the 'Profile' property).
        """
        thickness = MaterialsAndThicknesses.get_dimensions_from_profile(material_profile)
        material_name = material_profile.Material.Name
        return material_name, thickness
    
    @staticmethod
    def get_RelAssociateMaterial(element):
        """
        Retrieves the `IfcRelAssociateMaterial` relationship associated with an element.

        Parameters:
        - element: The element object whose material association relationship is to be retrieved.
                   This object is expected to have attributes `HasAssociations` and `IsTypedBy`.

        Returns:
        - `rel_associate_material`: The `IfcRelAssociateMaterial` relationship associated with the element, 
          if found.
          """
        

        if element.HasAssociations != ():
            for rel in element.HasAssociations: 
                if rel.is_a() == "IfcRelAssociatesMaterial":
                   rel_associate_material = rel 
                   
        elif element.HasAssociations == ():
            for Type in element.IsTypedBy:
                element_type = Type.RelatingType
                for rel in element_type.HasAssociations:
                    if rel.is_a() == "IfcRelAssociatesMaterial":
                        rel_associate_material = rel
        
        return rel_associate_material
    
    
    @staticmethod
    def exporting_materials_and_thicknesses(element):
        """Extracts material and thickness information from an element based on its associated material relationship.

        Parameters:
        - element: The element object whose material and thickness information is to be extracted.

        Returns:
        - A tuple containing:
            - `material_name`: The name of the material associated with the element.
            - `thickness`: The thickness of the material or the element based on its type and configuration."""
        
        print(element.Name)
        thickness = None
        material_name = None
        rel_associate_material = MaterialsAndThicknesses.get_RelAssociateMaterial(element)
        print(rel_associate_material.RelatingMaterial.is_a())

        #Simple material
        if rel_associate_material.RelatingMaterial.is_a()=="IfcMaterial":
            print(rel_associate_material.RelatingMaterial)
            material_name = rel_associate_material.RelatingMaterial.Name
            print("Retriving thickness from QSets")
            if element.is_a() == "IfcBeam" or element.is_a() == "IfcColumn":
                thickness = MaterialsAndThicknesses.get_thickness_from_pset(element)
            elif element.is_a() == "IfcWall" or element.is_a() == "IfcSlab" or element.is_a() == "IfcFooting":
                thickness = MaterialsAndThicknesses.get_thickness_from_qset(element)
            elif element.is_a() == "IfcRoof":
                thickness = MaterialsAndThicknesses.get_roof_thickness_from_pset(element)
            elif element.is_a() == "IfcDoor" or element.is_a() == "IfcWindow":
                thickness = MaterialsAndThicknesses.get_door_windows_thickness_from_pset(element)
            else:
                thickness = None
                print("work in progress")
            element_info = {"material_name": material_name, "thickness": thickness}

        #Layer    
        elif rel_associate_material.RelatingMaterial.is_a()=="IfcMaterialLayerSetUsage":
            element_info = []
            material_layers = rel_associate_material.RelatingMaterial.ForLayerSet              
            material_layers = material_layers[0]                
            for material_layer in material_layers:
                material_name, thickness = MaterialsAndThicknesses.get_info_from_material_layer(material_layer)
                element_info.append({"material_name": material_name, "thickness": thickness})

        #LayerSet    
        elif rel_associate_material.RelatingMaterial.is_a()=="IfcMaterialLayerSet":
            element_info = []
            material_layers = rel_associate_material.RelatingMaterial            
            material_layers = material_layers[0]                
            for material_layer in material_layers:
                material_name, thickness = MaterialsAndThicknesses.get_info_from_material_layer(material_layer)
                element_info.append({"material_name": material_name, "thickness": thickness})

        #Profile
        elif rel_associate_material.RelatingMaterial.is_a()=="IfcMaterialProfileSetUsage":
            element_info = []
            material_profiles_set = rel_associate_material.RelatingMaterial.ForProfileSet              
            material_profiles = material_profiles_set.MaterialProfiles
            for material_profile in material_profiles:
                material_name, thickness = MaterialsAndThicknesses.get_info_from_material_profile(material_profile)
                element_info.append({"material_name": material_name, "thickness": thickness})

        #ProfileSet
        elif rel_associate_material.RelatingMaterial.is_a()=="IfcMaterialProfileSet":
            element_info = []
            material_profile_set = rel_associate_material.RelatingMaterial   
            material_profiles = material_profile_set.MaterialProfiles  
      
            for material_profile in material_profiles:
                material_name, thickness = MaterialsAndThicknesses.get_info_from_material_profile(material_profile)
                element_info.append({"material_name": material_name, "thickness": thickness})
        
        #ConstituentSet
        elif rel_associate_material.RelatingMaterial.is_a()=="IfcMaterialConstituentSet":
            material_constituent_set = rel_associate_material.RelatingMaterial   
            material_constituent = material_constituent_set.MaterialConstituents 
            element_info = QuantitySet.get_complex_quantity(element)

               

        return element_info
    
    @staticmethod
    def exporting_materials_and_thicknesses_for_complex_elements(element):
        if Aggregation.has_aggregation(element):
            elements = Aggregation.get_aggregated_elements(element)
            for element in elements:
                info = MaterialsAndThicknesses.exporting_materials_and_thicknesses(element)
        else:
            info = MaterialsAndThicknesses.exporting_materials_and_thicknesses(element)

        return info
    
    @staticmethod
    def exporting_thickness_materials_for_IFCBuildingElements(ifc_file):
        dictionaries = []
        elements = ifc_file.by_type("IfcBuildingElement")
        elements = [element for element in ifc_file.by_type("IfcBuildingElement")
            if not element.is_a("IfcBuildingElementProxy")]
        for element in elements:
            info = (MaterialsAndThicknesses.exporting_materials_and_thicknesses_for_complex_elements(element))
            dictionaries.append(info)
        return dictionaries

class StructuralProperties:

    @staticmethod
    def get_common_properties(material):
        psets = ifcopenshell.util.element.get_psets(material)
        properties = psets["Pset_MaterialCommon"]
        if not properties:
            print(f"Warning: 'Pset_MaterialMechanical' not found for material {material.Name}")
        properties.pop('id', None) 
        return properties
    
    @staticmethod
    def get_mechanical_properties(material):
        psets = ifcopenshell.util.element.get_psets(material)
        properties = psets["Pset_MaterialMechanical"]
        if not properties:
            print(f"Warning: 'Pset_MaterialMechanical' not found for material {material.Name}")
        properties.pop('id', None) 
        return properties
    

class Material:
    def __init__(self, name, density, young_modulus, poisson_ratio, is_structural, material_model_type,
                 compressive_strength, tensile_strength,compression_fracture_energy, tensile_fracture_energy,
                  compressive_elastic_behaviour ):
        self.name = name
        self.density = density
        self.young_modulus = young_modulus
        self.poisson_ratio = poisson_ratio
        self.is_structural = is_structural
        self.material_model_type = material_model_type
        self.compressive_strength = compressive_strength 
        self.tensile_strength = tensile_strength 
        self.compression_fracture_energy = compression_fracture_energy 
        self.tensile_fracture_energy = tensile_fracture_energy 
        self.material_model_type = material_model_type 
        self.compressive_elastic_behaviour = compressive_elastic_behaviour
        
    
    def __repr__(self):
        return (f"Material(name={self.name}, density={self.density} kg/m³, "
                f"YoungModulus={self.young_modulus} MPa, "
                f"PoissonRatio={self.poisson_ratio}, "
                f"Structural={self.is_structural}, " f"MaterialModelType={self.material_model_type}")

# Function to create material database from IFC file
def create_material_database(ifc_file):
    material_db = {}
    materials = ifc_file.by_type("IfcMaterial")

    for material in materials:
        name = material.Name
        common_properties = StructuralProperties.get_common_properties(material)
        
        try:
            properties = StructuralProperties.get_mechanical_properties(material)
            young_modulus = properties.get('YoungModulus', 0)
            poisson_ratio = properties.get('PoissonRatio', 0)
            is_structural = properties.get('isStructural', False)
            compressive_strength = properties.get('CompressiveStrength', 0)
            tensile_strength = properties.get('TensileStrength', 0)
            compression_fracture_energy = properties.get('CompressionFractureEnergy', 0)
            tensile_fracture_energy = properties.get('TensileFractureEnergy', 0)
            material_model_type = common_properties.get('MaterialModelType', None)
            compressive_elastic_behaviour = common_properties.get('CompressiveStressElasticBehaviour', 0)
        except Exception as e:
            print(f"The material {name}: is not structural, and it has not {e}")
            young_modulus = 0
            poisson_ratio = 0
            is_structural = False
            material_model_type = None

        density = common_properties.get('MassDensity', 0)

        material_db[name] = Material(
            name,
            density,
            young_modulus,
            poisson_ratio,
            is_structural,
            material_model_type, 
            compressive_strength,
            tensile_strength,
            compression_fracture_energy,
            tensile_fracture_energy, 
            compressive_elastic_behaviour
        )
    
    return material_db

def is_structural_material(material_name, materials):
    """
    Checks if a given material in the database is structural.
    
    :param material_name: Name of the material to check
    :param materials: Dictionary of material objects
    :return: The material if Structural=True, otherwise None
    """
    material = materials.get(material_name)
    
    if material and getattr(material, 'Structural', False) == True:
        return material
    

# Homogenize slab function (updated to use new material database generation)
# def homogenize_slab(layers, slab, material_db):
#     total_volume = 0
#     total_density = 0
#     total_poisson_ratio = 0
#     weighted_young_modulus = 0
#     total_thickness = 0

#     for layer in layers:
#         material = material_db[layer['material_name']]
#         shape = GeometryForVolume.get_shape(slab)
#         volume = GeometryForVolume.get_volume_from_shape(shape)
#         layer['volume'] = volume
#         total_volume += volume
#         total_density += material.density * volume
#         total_poisson_ratio += material.poisson_ratio * volume
#         weighted_young_modulus += material.young_modulus * volume
#         total_thickness += layer.get('thickness', 0)

#     E_eff = weighted_young_modulus / total_volume if total_volume > 0 else 0
#     nu_eff = total_poisson_ratio / total_volume if total_volume > 0 else 0
#     rho_eff = total_density / total_volume if total_volume > 0 else 0

#     fictitious_material_name = f"Fictitious_Material{len(material_db) + 1}"
#     material_db[fictitious_material_name] = Material(
#         fictitious_material_name,
#         rho_eff,
#         E_eff,
#         nu_eff,
#         True
#     )

#     return {
#         'Effective Young Modulus (MPa)': E_eff,
#         'Effective Poisson Ratio': nu_eff,
#         'Effective Density (kg/m^3)': rho_eff,
#         'Material Tag': fictitious_material_name,
#         'Total Thickness (m)': total_thickness
#     }

def homogenize_slab(layers, slab, material_db):
    qsets = ifcopenshell.util.element.get_psets(slab, qtos_only=True)

    gross_area = qsets['Qto_SlabBaseQuantities'].get('GrossArea', 0)
    print(gross_area)

    total_density = 0

    structural_thickness = 0
    structural_poisson_ratio = 0
    structural_young_modulus = 0
    compound = Geometry.get_geom(slab)
    
    tot_geom = GeometryForVolume.get_volume_from_shape(compound)
    print(tot_geom)
    structural_geom = Geometry.get_lowest_solid(compound)
    structural_volume = GeometryForVolume.get_volume_from_shape(structural_geom)
    print(structural_volume)


    structural_materials = []
    for layer in layers:
        print(layer)
        material_name = layer['material_name']
        material = material_db.get(material_name)
        total_density = + material.density


        if material.is_structural == True:
            structural_young_modulus = material.young_modulus
            structural_poisson_ratio = material.poisson_ratio
            structural_thickness = layer['thickness']
            structural_density = material.density
            struc_volume = gross_area*structural_thickness
            structural_mass = struc_volume*structural_density
            # Get shape and calculate volume
        
        else:
            non_structural_thickness = layer['thickness']
            non_struc_volume = gross_area*non_structural_thickness
            non_structural_density = material.density
            non_structural_mass = +(non_structural_density*non_struc_volume) #fare in modo di sommare
    
    calibrated_density =(structural_mass+non_structural_mass)/struc_volume
    fictitious_material_name = f"Fictitious_Material{len(material_db) + 1}"
    material_db[fictitious_material_name] = Material(
        fictitious_material_name,
        calibrated_density,
        structural_young_modulus,
        structural_poisson_ratio,
        True,
        "LinearElastic", 
        0, 0, 0, 0, 0
    )

    return {
        'Effective Young Modulus (MPa)': structural_young_modulus,
        'Effective Poisson Ratio': structural_poisson_ratio,
        'Effective Density (kg/m^3)': calibrated_density,
        'Material Tag': fictitious_material_name,
        'Thickness (m)': structural_thickness,
        'Structural Layer Thickness (m)': structural_thickness,
        'Structural Layer Young Modulus (MPa)': structural_young_modulus,
        'Structural Layer Poisson Ratio': structural_poisson_ratio
    }


def assign_material_tags(elements, material_db):
    element_tags = {}  # Dictionary to store tags
    
    for element in elements:
        info = MaterialsAndThicknesses.exporting_materials_and_thicknesses_for_complex_elements(element)
        
        if isinstance(info, list):
            result = homogenize_slab(info, element, material_db)
            fictitious_material_name = result['Material Tag']
            total_thickness = result['Thickness (m)']
            tag = f"{fictitious_material_name}_{total_thickness:.2f}_m"
        else:
            thickness = info.get('thickness', 0) or 0
            tag = f"{info['material_name']}_{thickness:.2f}_m"
        
        element_tags[element] = tag  # Store element-tag mapping
    
    return element_tags


