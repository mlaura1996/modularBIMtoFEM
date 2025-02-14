import re

def transform_string(input_string):
    """ Use regex to capture everything before the first underscore"""
    transformed_string = re.sub(r'_(.*)', '', input_string)
    return transformed_string

def extract_underscored_parts(input_string):
    """ Use regex to find all substrings between underscores, including underscores"""
    matches = re.findall(r'(_[^_]+_)', input_string)
    return matches