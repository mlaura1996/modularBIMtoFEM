from core.config import plt, csv, pd 

def visualize_timeseries(df):
    # Extract time and displacement values
    time_values = df['Estimated Time (s)'].values  # Time steps
    displacement_values = df['Ux_top [mm]'].values  # Displacement history at top of the wall
    # Plot the cyclic loading time series
    plt.figure(figsize=(10, 5))
    plt.plot(time_values, displacement_values, marker="o", linestyle="-", color="b")
    plt.xlabel("Time (s)")
    plt.ylabel("Displacement (mm)")
    plt.title("Cyclic Loading Time Series (Displacement vs. Time)")
    plt.grid(True)
    plt.show()

@staticmethod
def create_csv_file_for_force_displacement_recorder(reaction_file, displacement_file, output_csv_file):
    """
    Processes reaction and displacement data files and writes the combined results to a CSV file.
    
    :param reaction_file: Path to the file containing reaction data
    :param displacement_file: Path to the file containing displacement data
    :param output_csv_file: Path to the output CSV file
    """
    # Lists to store processed data
    reaction_sums = []
    displacements = []

    # Process the reaction file to sum the values (ignoring the first column)
    with open(reaction_file, 'r') as file:
        for line in file:
            # Split the line into columns
            columns = line.strip().split()
            
            # Ignore the first column and keep the rest
            data_without_first_column = columns[1:]
            
            # Convert the remaining data to float and sum them
            row_sum = sum(float(value) for value in data_without_first_column)
            
            # Store the sum for later use
            reaction_sums.append(row_sum)

    # Process the displacement file and store processed data
    with open(displacement_file, 'r') as file:
        for line in file:
            # Split the line into columns
            columns = line.strip().split()
            
            # Ignore the first column and keep the rest
            if len(columns) > 1:  # Ensure there are more columns to process
                displacement_value = float(columns[1])
                
                # Store the displacement for later use
                displacements.append(displacement_value)

    # Ensure both lists have the same length (just in case there's a mismatch)
    min_length = min(len(reaction_sums), len(displacements))
    reaction_sums = reaction_sums[:min_length]
    displacements = displacements[:min_length]

    # Add (0, 0) as the first row
    reaction_sums.insert(0, 0)
    displacements.insert(0, 0)

    # Write to CSV file
    with open(output_csv_file, 'w', newline='') as csvfile:
        csv_writer = csv.writer(csvfile)
        
        # Write header
        csv_writer.writerow(['TotalReaction', 'Displacement'])
        
        # Write data rows
        for reaction, displacement in zip(reaction_sums, displacements):
            csv_writer.writerow([reaction, displacement])

def plot_reaction_vs_displacement(file_path):
        """
        Reads a CSV file and plots Displacement (X-axis) vs Reaction Sum (Y-axis)
        
        :param file_path: Path to the CSV file containing the data
        """
        data = pd.read_csv(file_path)

        # Extract the columns, assuming they are named 'Reaction Sum' and 'Displacement'
        reaction_sums = data['TotalReaction']
        displacements = data['Displacement']
        plt.figure(figsize=(8, 6))
        plt.plot(displacements, reaction_sums, linestyle='-', color = 'k')
        plt.xlabel("Displacement (mm)")
        plt.ylabel("Reactions (N)")
        plt.title("Reactions vs Displacement")
        plt.grid(True)
        plt.show()





                


