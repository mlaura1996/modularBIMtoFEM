"""What differs between the IFC schemas the package reads.

The conversion reads IFC2X3, IFC4 and IFC4X3 files. The one difference it
meets is the supertype of walls, slabs, columns and the other building
elements: IfcBuildingElement up to IFC4, renamed IfcBuiltElement in IFC4X3.
Asking a file for a type its schema does not define is an error, so the
name is chosen from the file's schema.
"""


def built_elements(ifc_file):
    """The building elements of an IFC model, without proxies."""
    name = "IfcBuiltElement" if ifc_file.schema.upper().startswith("IFC4X3") else "IfcBuildingElement"
    return [e for e in ifc_file.by_type(name) if not e.is_a("IfcBuildingElementProxy")]
