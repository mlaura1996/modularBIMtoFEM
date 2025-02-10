import gmsh
import numpy as np
from Resources import Mesh
import re
from .gmsh2opensees import * 

def transform_string(input_string):
    # Use regex to capture everything before the first underscore
    transformed_string = re.sub(r'_(.*)', '', input_string)
    return transformed_string

def extract_underscored_parts(input_string):
    # Use regex to find all substrings between underscores, including underscores
    matches = re.findall(r'(_[^_]+_)', input_string)
    return matches

def get_normals(tags, return_dict=True):
    """
    Retrieves surface normals for a list of surface tags.
    
    :param tags: List of surface tags.
    :param return_dict: If True, returns a dictionary {tag: normal}. If False, returns a list.
    :return: Dictionary of normals if return_dict=True, else a list of normal vectors.
    """
    normals = {tag: gmsh.model.getNormal(tag, [1, 0, 0, 1]) for tag in tags}
    return normals if return_dict else list(normals.values())

def find_common_numbers(tuple1, list_of_tuples):
    """
    Finds common numbers between a given tuple and a list of tuples.

    :param tuple1: Tuple with structure (int, [list of numbers])
    :param list_of_tuples: List of tuples with the same structure.
    :return: A dictionary with keys as first numbers of matching tuples and values as common numbers.
    """
    list1 = set(tuple1[1])
    return {t[0]: list1 & set(t[1]) for t in list_of_tuples if list1 & set(t[1])}

def find_unique_numbers(tuple1, list_of_tuples):
    """
    Finds numbers unique to the first tuple.

    :param tuple1: Tuple with structure (int, [list of numbers])
    :param list_of_tuples: List of tuples with the same structure.
    :return: A set of numbers unique to tuple1.
    """
    all_other_numbers = {num for t in list_of_tuples for num in t[1]}
    return set(tuple1[1]) - all_other_numbers

def group_arrays_by_absolute_values(arrays, tol=1e-9):
    """
    Groups numpy arrays based on absolute values.

    :param arrays: List of numpy arrays.
    :param tol: Tolerance for numerical comparison.
    :return: List of groups of arrays with matching absolute values.
    """
    groups = []
    for array in arrays:
        abs_array = np.abs(array)
        for group in groups:
            if np.allclose(np.abs(group[0]), abs_array, atol=tol):
                group.append(array)
                break
        else:
            groups.append([array])
    return groups

def find_matching_keys_with_absolute_values(beam_surfaces, reference_plan):
    """
    Finds keys in a dictionary where values match a reference plan (absolute values).

    :param beam_surfaces: Dictionary {tag: normal vector}.
    :param reference_plan: Numpy array to compare against.
    :return: List of matching keys.
    """
    return [key for key, value in beam_surfaces.items() if np.allclose(np.abs(value), np.abs(reference_plan), atol=1e-9)]

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

def is_inside_wall(fragment, walls):
    """
    Checks if a fragment is inside any of the walls using bounding box overlap.
    """
    x_min_f, y_min_f, z_min_f, x_max_f, y_max_f, z_max_f = gmsh.model.getBoundingBox(3, fragment)
    
    for wall in walls:
        x_min_w, y_min_w, z_min_w, x_max_w, y_max_w, z_max_w = gmsh.model.getBoundingBox(3, wall)
        
        # Check if bounding boxes overlap
        if (
            x_min_f >= x_min_w and x_max_f <= x_max_w and
            y_min_f >= y_min_w and y_max_f <= y_max_w and
            z_min_f >= z_min_w and z_max_f <= z_max_w
        ):
            return wall  # Return wall ID if inside
    
    return None  # Not inside any wall

def assign_beam_fragments_to_walls(beam, walls, fragments, i):
    """
    Assigns side fragments to masonry and middle fragments to timber.
    """
    beam_name = gmsh.model.get_entity_name(3, beam)
    beam_dim = extract_underscored_parts(beam_name)
    beam_dim = beam_dim[0]
    print(beam_dim)
    assigned_fragments = set()

    middle_fragments = []
    
    for fragment in fragments:
        i = i + 1
        fragment_tag = fragment[1]
        intersecting_wall = is_inside_wall(fragment_tag, walls)

        if intersecting_wall:
            wall_name = gmsh.model.get_entity_name(3, intersecting_wall)
            wall_name = transform_string(wall_name)
            wall_name = wall_name + beam_dim + "" + str(i) 
            gmsh.model.set_entity_name(3, fragment_tag, wall_name)
            print(f"✅ Assigned fragment {fragment_tag} to {wall_name}")
            assigned_fragments.add(fragment_tag)
        else:
            middle_fragments.append(fragment_tag)

    for mid_frag in middle_fragments:
        gmsh.model.set_entity_name(3, mid_frag, beam_name)
        print(f"✅ Assigned middle fragment {mid_frag} to Timber")

    gmsh.model.occ.synchronize()



def split_beam_and_assign_to_wall(gmshmodel, labels):
    """
    Splits beam volumes into parts based on wall planes.

    :param gmshmodel: Gmsh model object.
    :param labels: Labels for material groups.
    """
    # Retrieve and categorize physical groups
    physical_groups = gmsh.model.getPhysicalGroups()
    beams = [entity for dim, tag in physical_groups if "StructuralTimber" in gmsh.model.getPhysicalName(dim, tag)
             for entity in gmsh.model.getEntitiesForPhysicalGroup(dim, tag)]
    walls = [entity for dim, tag in physical_groups if "Masonry" in gmsh.model.getPhysicalName(dim, tag)
             for entity in gmsh.model.getEntitiesForPhysicalGroup(dim, tag)]

    # Collect wall boundaries
    wall_tuples = [(wall, [sublist[1] for sublist in gmsh.model.getBoundary([(3, wall)], oriented=False)])
                   for wall in walls]
    i = 0
    for beam_tag in beams:
        beam_vertices = gmsh.model.getBoundary([(3, beam_tag)], oriented=False)
        beam_tuple = (beam_tag, [sublist[1] for sublist in beam_vertices])

        common_walls = find_common_numbers(beam_tuple, wall_tuples)
        # if not common_walls:
        #     continue

        fragments = [(3, beam_tag)]
        for wall_tag, shared_surfaces in common_walls.items():
            wall_name = gmsh.model.get_entity_name(3, wall_tag)
            new_fragments = []

            for fragment in fragments:
                i =  i + 1 
                shared_surface_list = list(shared_surfaces)
                missing_surface = close_prism(shared_surface_list, method="loop")

                initial_volumes = gmsh.model.getEntities(3)
                _, fragment_map = gmsh.model.occ.fragment([fragment], [(2, missing_surface)])
                #_, fragment_map = gmsh.model.occ.intersect([fragment], [(2, missing_surface)])

                
                
                gmsh.model.occ.synchronize()

                new_fragments.extend([vol for vol in gmsh.model.getEntities(3) if vol not in initial_volumes])

            fragments = new_fragments  # Update fragments for next iteration

            # **NEW: Assign inner beam fragments to wall groups**
            assign_beam_fragments_to_walls(beam_tag, walls, fragments, i)
            #Mesh.createMatPhisicalGroups(gmshmodel, labels)
            gmsh.model.occ.synchronize()


    # Cleanup duplicates
    gmsh.model.occ.removeAllDuplicates()
    gmsh.model.geo.removeAllDuplicates()
    gmsh.model.occ.synchronize()
    # gmsh.fltk.run()


def cutMod():

    # Retrieve all physical groups (walls and beams)
    physical_groups = gmsh.model.getPhysicalGroups()

    walls = [entity for dim, tag in physical_groups if "Masonry" in gmsh.model.getPhysicalName(dim, tag)
            for entity in gmsh.model.getEntitiesForPhysicalGroup(dim, tag)]

    beams = [entity for dim, tag in physical_groups if "StructuralTimber" in gmsh.model.getPhysicalName(dim, tag)
            for entity in gmsh.model.getEntitiesForPhysicalGroup(dim, tag)]

    shared_surfaces = []
    wall_boundary_faces = set()

    # Get boundaries of walls
    for wall in walls:
        wall_boundaries = gmsh.model.getBoundary([(3, wall)], oriented=False)
        wall_boundary_faces.update(wall_boundaries)  # Store all wall boundary faces

    # Get boundaries of beams and find the shared surfaces
    for beam in beams:
        beam_boundaries = gmsh.model.getBoundary([(3, beam)], oriented=False)

        for beam_face in beam_boundaries:
            if beam_face in wall_boundary_faces:  # Check for shared faces
                shared_surfaces.append(beam_face)  # Store shared surfaces

    # Perform cut operation to separate the touching elements
    for wall in walls:
        for beam in beams:
            try:
                _, fragment_map = gmsh.model.occ.cut([(3, wall)], [(3, beam)], removeObject=False, removeTool=False)
                gmsh.model.occ.synchronize()
            except Exception as e:
                print(f"Skipping cut for wall {wall} and beam {beam} due to error: {e}")


def create2DPhysicalGroups(gmsh_model):
    # Retrieve all physical groups (walls and beams)
    physical_groups = gmsh_model.getPhysicalGroups()

    walls = [entity for dim, tag in physical_groups if "Masonry" in gmsh_model.getPhysicalName(dim, tag)
             for entity in gmsh_model.getEntitiesForPhysicalGroup(dim, tag)]

    beams = [entity for dim, tag in physical_groups if "StructuralTimber" in gmsh_model.getPhysicalName(dim, tag)
             for entity in gmsh_model.getEntitiesForPhysicalGroup(dim, tag)]
    
    wall_boundary_faces = set()
    beam_boundary_faces = set()
    matching_surfaces = []

    # Get boundaries of walls
    for wall in walls:
        wall_boundaries = gmsh_model.getBoundary([(3, wall)], oriented=False)
        wall_boundary_faces.update(wall_boundaries)  # Store all wall boundary faces

    # Get boundaries of beams
    for beam in beams:
        beam_boundaries = gmsh_model.getBoundary([(3, beam)], oriented=False)
        beam_boundary_faces.update(beam_boundaries)  # Store all beam boundary faces

    # Identify surfaces that now occupy the same location after the cut
    for wall_face in wall_boundary_faces:
        for beam_face in beam_boundary_faces:
            if gmsh_model.getEntitiesInBoundingBox(*gmsh_model.getBoundingBox(wall_face[0], wall_face[1])) == \
               gmsh_model.getEntitiesInBoundingBox(*gmsh_model.getBoundingBox(beam_face[0], beam_face[1])):
                matching_surfaces.append((wall_face, beam_face))

    # Define separate 2D physical groups for the surfaces in the same place
    if matching_surfaces:
        walls_cut_surfaces = [s[0][1] for s in matching_surfaces]
        beams_cut_surfaces = [s[1][1] for s in matching_surfaces]

        gmsh_model.addPhysicalGroup(2, walls_cut_surfaces, tag=10)
        gmsh_model.setPhysicalName(2, 10, "Wall_Cut_Surfaces")

        gmsh_model.addPhysicalGroup(2, beams_cut_surfaces, tag=20)
        gmsh_model.setPhysicalName(2, 20, "Beam_Cut_Surfaces")

    print("2D Physical Groups assigned for cut surfaces.")













