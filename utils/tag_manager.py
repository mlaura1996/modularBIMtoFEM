from openseespy.opensees import *

def add_unique_solid_material_tag(excluded_list):
    """This function returns an incremental number that is not in the excluded_list - needed for the tags of the materials"""
    excluded_set = set(excluded_list)  # Convert list to set for O(1) lookups
    max_excluded = max(excluded_set) if excluded_set else -1  # Find the maximum value in the excluded list
    current_num = max_excluded + 1
    while current_num in excluded_set:
        current_num = current_num +1
    return current_num

class Opensees:
    @staticmethod
    def get_next_available_node_tag():
        all_node_tags = getNodeTags()
        if not all_node_tags:
            return 1  # If no nodes exist, start from 1
        max_tag = max(all_node_tags)
        return max_tag + 1
    
    @staticmethod
    def get_next_available_element_tag():
        all_ele_tags = getEleTags()
        if not all_ele_tags:
            return 1  # If no nodes exist, start from 1
        max_tag = max(all_ele_tags)
        return max_tag + 1

class TagManager:
    def __init__(self):
        self.material_tag_counter = 1  # Start material tags from 1
        self.element_tag_counter = 1   # Start element tags from 1

    @staticmethod    
    def add_unique_solid_material_tag(excluded_list):
        """This function returns an incremental number that is not in the excluded_list - needed for the tags of the materials"""
        print(excluded_list)
        excluded_set = set(excluded_list)  # Convert list to set for O(1) lookups
        max_excluded = max(excluded_set) if excluded_set else -1  # Find the maximum value in the excluded list
        current_num = max_excluded + 1
        while current_num in excluded_set:
            current_num = current_num +1
        return current_num
    
    def get_new_material_tag(self, tags):
        """Ensures unique material tags across models."""
        new_tag = TagManager.add_unique_solid_material_tag(tags) 
        if new_tag < self.material_tag_counter:
            new_tag = self.material_tag_counter
        self.material_tag_counter = new_tag + 1  # Increment counter
        return new_tag

    def get_new_element_tag(self):
        """Ensures unique element tags across models."""
        new_tag = self.element_tag_counter
        self.element_tag_counter += 1
        return new_tag

    def reset(self):
        """Reset counters between models if needed."""
        self.material_tag_counter = 1
        self.element_tag_counter = 1
