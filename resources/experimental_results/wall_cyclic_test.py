import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import argrelextrema
from scipy.spatial.distance import pdist, squareform

def clean_nearby_points(array1, array2, threshold=1.0):
    """
    Merge very close points by averaging them.
    
    :param array1: First numpy array (X coordinates)
    :param array2: Second numpy array (Y coordinates)
    :param threshold: Distance threshold to merge points
    :return: Cleaned numpy arrays
    """
    points = np.vstack((array1, array2)).T
    
    # Compute pairwise distances
    distances = squareform(pdist(points))
    
    # Group points that are very close
    visited = set()
    new_points = []
    
    for i in range(len(points)):
        if i in visited:
            continue
        
        # Find all points within the threshold
        close_indices = np.where(distances[i] < threshold)[0]
        visited.update(close_indices)
        
        # Compute the average of close points
        avg_point = np.mean(points[close_indices], axis=0)
        new_points.append(avg_point)
    
    new_points = np.array(new_points)
    return new_points[:, 0], new_points[:, 1]

def select_y_for_near_x(array1, array2, threshold_inner=1.0, threshold_outer=2.0):
    """
    For points with similar X values, select the max Y if Y > 0 and min Y if Y < 0,
    using different thresholds for inner (-10 < X < 10) and outer (X < -10 or X > 10) regions.
    
    :param array1: First numpy array (X coordinates)
    :param array2: Second numpy array (Y coordinates)
    :param threshold_inner: Threshold for grouping points when -10 < X < 10
    :param threshold_outer: Threshold for grouping points when X < -10 or X > 10
    :return: Cleaned numpy arrays with selected Y values
    """
    df = pd.DataFrame({'X': array1, 'Y': array2})
    
    # Sort by X values
    df = df.sort_values(by='X').reset_index(drop=True)
    
    grouped_x = []
    grouped_y = []
    
    while not df.empty:
        # Take the first X as reference
        ref_x = df.iloc[0]['X']
        
        # Determine the threshold based on X value
        if -10 < ref_x < 10:
            threshold = threshold_inner
        else:
            threshold = threshold_outer
        
        close_points = df[np.abs(df['X'] - ref_x) <= threshold]
        
        # Select max Y if Y > 0, min Y if Y < 0
        if (close_points['Y'] > 0).any():
            selected_y = close_points[close_points['Y'] > 0]['Y'].max()
        else:
            selected_y = close_points[close_points['Y'] < 0]['Y'].min()
        
        grouped_x.append(ref_x)
        grouped_y.append(selected_y)
        
        # Drop processed points
        df = df.drop(close_points.index).reset_index(drop=True)
    
    return np.array(grouped_x), np.array(grouped_y)
    

def save_arrays_to_excel(array1, array2, filename="output.xlsx"):
    """
    Save two numpy arrays into an Excel file as two columns.
    
    :param array1: First numpy array
    :param array2: Second numpy array
    :param filename: Name of the Excel file to save (default: "output.xlsx")
    """
    # Create a DataFrame with the two arrays as columns
    df = pd.DataFrame({'Column 1': array1, 'Column 2': array2})
    
    # Save to Excel
    df.to_excel(filename, index=False)
    
    print(f"Data saved to {filename}")


def plot_envelope_curve(displacements, forces):
    # Convert inputs to numpy arrays (if not already)
    displacements = np.array(displacements)
    forces = np.array(forces)

    # Find local maxima and minima (peaks of each cycle)
    max_indices = argrelextrema(forces, np.greater)[0]  # Indices of local maxima
    min_indices = argrelextrema(forces, np.less)[0]     # Indices of local minima

    # Extract peak points
    peak_displacements = np.concatenate((displacements[max_indices], displacements[min_indices]))
    peak_forces = np.concatenate((forces[max_indices], forces[min_indices]))

    # Sort peaks by displacement for smooth curve plotting
    sorted_indices = np.argsort(peak_displacements)
    envelope_disp = peak_displacements[sorted_indices]
    envelope_force = peak_forces[sorted_indices]

    # Plot Hysteresis (Force-Displacement) Curve
    plt.figure(figsize=(8, 6))
    plt.plot(displacements, forces, color='gray', alpha=0.5, label='Hysteresis Curve')

    print(len(envelope_disp))

    envelope_disp, envelope_force = select_y_for_near_x(envelope_disp, envelope_force, 0.2, 1)
    print(len(envelope_disp))

    # Plot Envelope Curve
    plt.plot(envelope_disp, envelope_force, 'black', linewidth=2, label='Envelope Curve')



    # Highlight Peak Points
    plt.scatter(envelope_disp, envelope_force, color='black', s=8, label='Peak Points')
    save_arrays_to_excel(envelope_disp, envelope_force,"resources/experimental_results/CT02_env.xlsx")

    # Labels and legend
    plt.xlabel("Displacement")
    plt.ylabel("Force")
    plt.title("Envelope Curve of a Cyclic Test")
    plt.legend()
    plt.grid(True)
    plt.show()

# Load the Excel file
file_path = "resources/experimental_results/CT02.xlsx"
output_file = "resources/experimental_results/CT02_cyclic_test_combined.xlsx"

# Read all sheets into a dictionary
sheets_dict = pd.read_excel(file_path, sheet_name=None)

# Lists to store combined data
x_values = []
y_values = []

# Dictionary to save processed data for each sheet
filtered_data = {}

# Process each sheet
for sheet_name, df in sheets_dict.items():
    if df.shape[1] < 6:  # Ensure the sheet has at least 6 columns
        print(f"Skipping sheet {sheet_name}, not enough columns.")
        continue

    # Extract first and sixth columns
    col1 = df.iloc[:, 0].dropna().tolist()  # First column (Displacements)
    col6 = df.iloc[:, 5].dropna().tolist()  # Sixth column (Force)

    # Remove the first element from each column
    if len(col1) > 1 and len(col6) > 1:
        x_values.extend(col1[1:])
        y_values.extend(col6[1:])

        # Store filtered data for this sheet
        filtered_data[sheet_name] = pd.DataFrame({"Displacements": col1[1:], "Force": col6[1:]})

# Check if data was extracted
if len(x_values) == 0 or len(y_values) == 0:
    print("Error: No valid data extracted from the Excel file.")
else:
    print(f"Extracted {len(x_values)} x-values and {len(y_values)} y-values.")

# Save filtered data to a new Excel file
with pd.ExcelWriter(output_file) as writer:
    for sheet_name, df in filtered_data.items():
        df.to_excel(writer, sheet_name=sheet_name, index=False)

print(f"Filtered data has been saved to '{output_file}'")

# Convert to NumPy arrays before passing to function
x_values = np.array(x_values)
y_values = np.array(y_values)
plot_envelope_curve(x_values, y_values)




