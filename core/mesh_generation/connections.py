from core.config import gmsh, np
from external.gmsh2opensees import *
from utils.string_helpers import transform_string, extract_underscored_parts
from utils.math_helpers import find_common_numbers
from utils.gmsh_helpers import close_prism, get_face_normal

import gmsh

import gmsh

def add_inward_extrusions_to_beams(
    physical_group_name: str,
    inset_depth: float = 10.0,
    cleanup: bool = True
):
    """
    For each volume in a given physical group (e.g. 'beams'), find its two smallest faces (assumed to be ends),
    and extrude them inward to simulate shortening the beam ends.

    Args:
        physical_group_name (str): Name of the physical group containing the beams.
        inset_depth (float): Depth to extrude inward on each end face.
        cleanup (bool): Whether to perform Boolean fragment to merge new volumes cleanly.
    """
    gmsh.model.occ.synchronize()

    # Find the physical group ID
    pgroups = gmsh.model.getPhysicalGroups()
    group_info = next(
        ((dim, tag) for (dim, tag) in pgroups
         if gmsh.model.getPhysicalName(dim, tag) == physical_group_name),
        None
    )
    if group_info is None:
        raise ValueError(f"Physical group '{physical_group_name}' not found.")

    dim, group_tag = group_info
    if dim != 3:
        raise ValueError(f"Physical group '{physical_group_name}' is not 3D (volume).")

    volumes = gmsh.model.getEntitiesForPhysicalGroup(dim, group_tag)

    for vol_tag in volumes:
        # Get all surfaces (faces) of the volume
        faces = gmsh.model.getBoundary([(3, vol_tag)], oriented=False, recursive=False)

        # Measure face areas to find the ends
        face_areas = []
        for face in faces:
            try:
                area = gmsh.model.occ.getMass(2, face[1])  # dim=2 for surfaces
                face_areas.append((area, face))
            except:
                continue  # In case getMass fails

        if len(face_areas) < 2:
            print(f"Skipping volume {vol_tag}: not enough faces with measurable area.")
            continue

        face_areas.sort(key=lambda x: x[0])
        end_faces = [face_areas[0][1], face_areas[1][1]]
        extruded_caps = []
        for face in end_faces:
            print(type(face))

            normal = gmsh.model.getNormal(face[1], [0.5, 0.5])
            print(normal)
            dx, dy, dz = [-inset_depth * n for n in normal]

            copied_faces = gmsh.model.occ.copy([face])  # Correctly returns list of (dim, tag)
            gmsh.model.occ.synchronize()

            extruded = gmsh.model.occ.extrude(copied_faces, dx, dy, dz)
                            # Collect only volume parts of the extrusion
            extruded_vols = [e for e in extruded if e[0] == 3]
            extruded_caps.extend(extruded_vols)
        gmsh.model.occ.synchronize()

        # Subtract the caps from the beam
        if extruded_caps:
            try:
                cut_result = gmsh.model.occ.cut([(3, vol_tag)], extruded_caps, removeObject=True, removeTool=True)
                gmsh.model.occ.synchronize()
            except Exception as e:
                print(f"Boolean cut failed for beam {vol_tag}: {e}")
                continue


    gmsh.model.occ.synchronize()


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

def extrude_beam_interface_surfaces(gmsh_model, offset=1e-6):
    """
    Identifies beam faces that are shared with walls and extrudes them slightly inward,
    ensuring correct volume-face association and mesh separation.

    :param gmsh_model: Gmsh model object.
    :param offset: Small offset value for extrusion (default: 1e-6).
    :return: Dictionary mapping original beam faces to their extruded versions.
    """
    print("🔍 Identifying common beam-wall faces for extrusion...")

    gmsh_model.occ.synchronize()
    
    physical_groups = gmsh.model.getPhysicalGroups()

    # Get beam and wall entities
    beam_volumes = set()
    wall_volumes = set()

    for dim, tag in physical_groups:
        name = gmsh.model.getPhysicalName(dim, tag)
        if "StructuralTimber" in name:
            beam_entities = gmsh.model.getEntitiesForPhysicalGroup(3, tag)
            beam_volumes.update(beam_entities)
        elif "Masonry" in name:
            wall_entities = gmsh.model.getEntitiesForPhysicalGroup(3, tag)
            wall_volumes.update(wall_entities)

    print(f"🔹 Total beam volumes found: {len(beam_volumes)}")
    print(f"🔹 Total wall volumes found: {len(wall_volumes)}")

    if not beam_volumes:
        print("⚠️ Warning: No beam volumes found! Check physical groups.")
        return {}

    # Get faces
    beam_faces = {sublist[1] for beam in beam_volumes for sublist in gmsh_model.getBoundary([(3, beam)], oriented=False)}
    wall_faces = {sublist[1] for wall in wall_volumes for sublist in gmsh_model.getBoundary([(3, wall)], oriented=False)}

    print(f"🔹 Total beam faces found: {len(beam_faces)}")
    print(f"🔹 Total wall faces found: {len(wall_faces)}")

    if not beam_faces or not wall_faces:
        print("⚠️ Warning: No beam or wall faces detected! Check if geometry exists.")
        return {}

    # Identify matching faces based on bounding box
    matching_surfaces = []
    tolerance = 1e-6

    for wall_face in wall_faces:
        x_min_w, y_min_w, z_min_w, x_max_w, y_max_w, z_max_w = gmsh_model.getBoundingBox(2, wall_face)

        for beam_face in beam_faces:
            x_min_b, y_min_b, z_min_b, x_max_b, y_max_b, z_max_b = gmsh_model.getBoundingBox(2, beam_face)

            # Bounding box check
            if (abs(x_min_w - x_min_b) <= tolerance and abs(x_max_w - x_max_b) <= tolerance and
                abs(y_min_w - y_min_b) <= tolerance and abs(y_max_w - y_max_b) <= tolerance and
                abs(z_min_w - z_min_b) <= tolerance and abs(z_max_w - z_max_b) <= tolerance):

                matching_surfaces.append((wall_face, beam_face))

    print(f"🔍 Found {len(matching_surfaces)} matching beam-wall faces.")

    if not matching_surfaces:
        print("⚠️ No shared beam-wall faces found!")
        return {}

    extruded_faces = {}

    for wall_face, beam_face in matching_surfaces:
        normal = get_face_normal(gmsh_model, beam_face)  # Compute normal direction
        print(f"🔍 Processing beam face {beam_face}, normal: {normal}")

        # Find the associated volume
        beam_volume = None
        for vol in beam_volumes:
            faces = [sublist[1] for sublist in gmsh_model.getBoundary([(3, vol)], oriented=False)]
            if beam_face in faces:
                beam_volume = vol
                break

        if not beam_volume:
            print(f"⚠️ Warning: No volume found for beam face {beam_face}. Skipping.")
            continue

        # Perform an inward extrusion instead of translation
        try:
            extruded_entity = gmsh_model.occ.extrude([(2, beam_face)], 
                                                     -offset * normal[0], 
                                                     -offset * normal[1], 
                                                     -offset * normal[2])
            gmsh_model.occ.synchronize()
            extruded_faces[beam_face] = extruded_entity[0][1]  # Store modified face
            print(f"✅ Extruded beam face {beam_face} inward.")
        except Exception as e:
            print(f"⚠️ Failed to extrude beam face {beam_face}. Error: {e}")

    print(f"✅ Successfully extruded {len(extruded_faces)} beam-wall faces.")

    return extruded_faces


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
                try:
                    _, fragment_map = gmsh.model.occ.fragment([fragment], [(2, missing_surface)])
                except TypeError:
                    pass
                #_, fragment_map = gmsh.model.occ.intersect([fragment], [(2, missing_surface)])                
                
                gmsh.model.occ.synchronize()

                new_fragments.extend([vol for vol in gmsh.model.getEntities(3) if vol not in initial_volumes])

            fragments = new_fragments  # Update fragments for next iteration

            # **NEW: Assign inner beam fragments to wall groups**
            assign_beam_fragments_to_walls(beam_tag, walls, fragments, i)
            # **🚀 Mini-Extrusion After Beam Splitting**
            #Mesh.createMatPhisicalGroups(gmshmodel, labels)
            #gmsh.model.occ.synchronize()

    # Cleanup duplicates
    gmsh.model.occ.removeAllDuplicates()
    gmsh.model.geo.removeAllDuplicates()
    gmsh.model.occ.synchronize()
    # gmsh.fltk.run()

def get_interface_volumes(gmsh_model):
    """
    Identifies volumes that do not belong to any physical group, which are likely the extruded interfaces.

    :param gmsh_model: Gmsh model object.
    :return: List of volume tags corresponding to interface regions.
    """
    gmsh_model.occ.synchronize()

    # Get all volume entities
    all_volumes = [tag for dim, tag in gmsh_model.getEntities(3)]  # 3 = Volume dimension

    # Get all volumes that are in a physical group
    physical_groups = gmsh_model.getPhysicalGroups(3)  # Get physical groups of volumes
    assigned_volumes = set()
    
    for dim, tag in physical_groups:
        assigned_volumes.update(gmsh_model.getEntitiesForPhysicalGroup(dim, tag))

    # Interface volumes are those NOT in any physical group
    interface_volumes = list(set(all_volumes) - assigned_volumes)
    
    print(f"🔍 Found {len(interface_volumes)} interface volumes (not assigned to any physical group).")
    return interface_volumes

def select_and_trim_all_beams(gmsh_model):
    """
    Identifies all beam volumes from the physical group, detects interface volumes,
    and trims all beams using Boolean subtraction.

    :param gmsh_model: Gmsh model object.
    :return: List of trimmed beam volumes.
    """
    gmsh_model.occ.synchronize()

    # Step 1: Get all physical groups
    physical_groups = gmsh_model.getPhysicalGroups(3)  # Get volume physical groups (dim=3)

    # Step 2: Identify original beam volumes (from StructuralTimber group)
    beam_volumes = set()
    for dim, tag in physical_groups:
        name = gmsh_model.getPhysicalName(dim, tag)
        if "StructuralTimber" in name:  # Assuming this is the name of the timber group
            beam_volumes.update(gmsh_model.getEntitiesForPhysicalGroup(dim, tag))

    beam_volumes = list(beam_volumes)  # Convert to list for iteration

    if not beam_volumes:
        print("⚠️ No beam volumes found in the StructuralTimber group.")
        return []

    print(f"🔍 Found {len(beam_volumes)} original beam volumes.")

    # Step 3: Detect extruded interface volumes (solids without a physical group)
    interface_volumes = get_interface_volumes(gmsh_model)

    if not interface_volumes:
        print("⚠️ No interface volumes found, skipping trimming.")
        return beam_volumes

    print(f"🔍 Found {len(interface_volumes)} interface volumes.")

    # Step 4: Trim each beam **one-by-one**, applying all interface volumes
    trimmed_beams = []
    for beam in beam_volumes:
        print(f"✂️ Trimming beam {beam} with interface volumes...")
        trimmed_beam = trim_beam_with_interfaces(gmsh_model, beam, interface_volumes)
        if trimmed_beam:
            trimmed_beams.append(trimmed_beam)

    gmsh_model.occ.synchronize()

    print(f"✅ Successfully trimmed {len(trimmed_beams)} beams.")

    return trimmed_beams  # Return updated beam volumes


def trim_beam_with_interfaces(gmsh_model, beam, interface_volumes):
    """
    Trims a single beam with all detected interface volumes and assigns new entity names to the largest trimmed volumes.

    :param gmsh_model: Gmsh model object.
    :param beam: The beam volume (single entity).
    :param interface_volumes: List of interface volumes to trim the beam.
    :return: List of assigned new beam volumes.
    """
    gmsh_model.occ.synchronize()
    original_name = gmsh_model.getEntityName(3, beam)

    try:
        result = gmsh_model.occ.fragment([(3, beam)], [(3, v) for v in interface_volumes])
        gmsh_model.occ.synchronize()

        trimmed_volumes = [vol[1] for vol in result[0] if vol[0] == 3]  # Extract trimmed solids

        if not trimmed_volumes:
            print(f"⚠️ No new trimmed volume generated for beam {beam}")
            return []

        # Compute volumes and sort them by size (largest first)
        volume_sizes = {}
        for vol in trimmed_volumes:
            bbox = gmsh_model.getBoundingBox(3, vol)
            volume_sizes[vol] = (bbox[3] - bbox[0]) * (bbox[4] - bbox[1]) * (bbox[5] - bbox[2])

        sorted_volumes = sorted(volume_sizes.keys(), key=lambda v: volume_sizes[v], reverse=True)
        largest_volumes = sorted_volumes[:2]  # Keep only the two largest volumes

        # Assign new entity name to the largest volumes
        #new_group_tag = gmsh_model.addPhysicalGroup(3, largest_volumes)
        i = 1
        for volume in largest_volumes:
            gmsh_model.set_entity_name(3, volume, original_name)

        print(f"✅ Trimmed beam {beam}. New volumes assigned to StructuralTimberNewVolumes: {largest_volumes}")

        gmsh_model.occ.synchronize()
        return largest_volumes

    except Exception as e:
        print(f"❌ Error while trimming beam {beam}: {e}")
        return []


















