import os

def rename_files_in_directory(directory):
    for filename in os.listdir(directory):
        new_filename = filename.replace('-', '_')
        os.rename(os.path.join(directory, filename), os.path.join(directory, new_filename))
    print(f"Renamed files in {directory}")

if __name__ == "__main__":
    directory = r"C:\Users\JJ\Downloads\manamoji-slack-main"
    rename_files_in_directory(directory)