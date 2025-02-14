def filter_materials_by_name(materials_dict, selected_names):
    """
    Filters a materials dictionary to include only the materials whose names are in the selected_names list.

    Parameters:
        materials_dict (dict): A dictionary of Material objects (keys are material names).
        selected_names (list): A list of material names to keep.

    Returns:
        dict: A filtered dictionary containing only the selected materials.
    """
    return {name: material for name, material in materials_dict.items() if name in selected_names}