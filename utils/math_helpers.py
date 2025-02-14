import numpy as np

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


def add_incremental_number(existing_list: list) -> int:
    """This method returns an incremental number that is not in the provided list."""
    
    excluded_set = set(existing_list)  # Convert list to set for O(1) lookups
    max_excluded = max(excluded_set) if excluded_set else -1  # Find the maximum value in the excluded list
    current_num = max_excluded + 1

    while current_num in excluded_set:
        current_num = current_num + 1

    return current_num