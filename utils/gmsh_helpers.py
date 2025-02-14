import gmsh

def get_normals(tags, return_dict=True):
    """
    Retrieves surface normals for a list of surface tags.
    
    :param tags: List of surface tags.
    :param return_dict: If True, returns a dictionary {tag: normal}. If False, returns a list.
    :return: Dictionary of normals if return_dict=True, else a list of normal vectors.
    """
    normals = {tag: gmsh.model.getNormal(tag, [1, 0, 0, 1]) for tag in tags}
    return normals if return_dict else list(normals.values())


def close_prism(surfaces, method="shell"):
    """
    Closes a prism by creating a missing surface.

    :param surfaces: List of surface tags (5 expected).
    :param method: "shell" (default) or "loop" to define closure method.
    :return: Created solid (volume) or missing surface.
    """
    if len(surfaces) != 5:
        raise ValueError("Exactly 5 surface tags must be provided.")

    # Get boundary edges
    boundary_edges = [edge[1] for surface in surfaces for edge in gmsh.model.getBoundary([(2, surface)], oriented=False)]
    edge_counts = {edge: boundary_edges.count(edge) for edge in boundary_edges}
    open_edges = [edge for edge, count in edge_counts.items() if count == 1]

    if len(open_edges) < 3:
        raise ValueError("Not enough open edges to create a missing surface.")

    missing_surface = gmsh.model.occ.addPlaneSurface([gmsh.model.occ.addWire(open_edges)])
    gmsh.model.occ.synchronize()

    if method == "loop":
        return missing_surface  # Return only missing surface if needed

    shell = gmsh.model.occ.addShell(surfaces + [missing_surface])
    gmsh.model.occ.synchronize()

    solid = gmsh.model.occ.addVolume([shell])
    gmsh.model.occ.synchronize()

    return solid

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
        print(solid_physical_groups)
        return solid_physical_groups