"""What the IFC schemas fix and what the package adds to them.

The conversion reads IFC2X3, IFC4 and IFC4X3 files. The one difference it
meets is the supertype of walls, slabs, columns and the other building
elements: IfcBuildingElement up to IFC4, renamed IfcBuiltElement in IFC4X3.
Asking a file for a type its schema does not define is an error, so the
name is chosen from the file's schema.

The prefix Pset_ is reserved for the property sets the standard defines, and
those sets hold only the properties defined for them. Pset_MaterialCommon
(MassDensity) and Pset_MaterialMechanical (YoungModulus, ShearModulus,
PoissonRatio) are used as the standard defines them; what the conversion needs
beyond them is kept in sets of the package, with the prefix OBTF_ (openBIMtoFEM):

    OBTF_MaterialModel   on IfcMaterial: ConstitutiveModel, IsStructural, the
                         strengths and fracture energies, Source
    OBTF_SectionSize     on beams, columns and roofs: the section dimensions
    OBTF_BeamConnection  on IfcBeam: Connectivity (Tied, Supported, Disconnected)
"""
MATERIAL_MODEL_PSET = "OBTF_MaterialModel"
SECTION_SIZE_PSET = "OBTF_SectionSize"
BEAM_CONNECTION_PSET = "OBTF_BeamConnection"
# non-standard properties that files written before these sets carry in the standard ones
LEGACY_MATERIAL_PROPERTIES = {
    "Pset_MaterialCommon": ("MaterialModelType", "CompressiveStressElasticBehaviour"),
    "Pset_MaterialMechanical": ("ConstitutiveModel", "isStructural", "CompressiveStrength", "TensileStrength",
                                "ShearStrength", "CompressionFractureEnergy", "TensileFractureEnergy"),
}


def built_elements(ifc_file):
    """The building elements of an IFC model, without proxies."""
    name = "IfcBuiltElement" if ifc_file.schema.upper().startswith("IFC4X3") else "IfcBuildingElement"
    return [e for e in ifc_file.by_type(name) if not e.is_a("IfcBuildingElementProxy")]
