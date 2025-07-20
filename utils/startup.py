import os


def load_cogs(disallowed: set, disallowed_folders: set = None):
    if disallowed_folders is None:
        disallowed_folders = set()

    file_list = []

    for root, _, files in os.walk("extensions/commands"):
        # Check if any part of the current path is a disallowed folder
        path_parts = root.replace("\\", "/").split("/")
        if any(folder in disallowed_folders for folder in path_parts):
            continue  # Skip this entire directory

        for filename in files:
            if not filename.endswith(".py") or filename.startswith("__"):
                continue

            full_path = os.path.join(root, filename)
            module_path = full_path.replace("\\", ".").replace("/", ".").replace(".py", "")

            # Check if the filename (without .py) is in disallowed
            if module_path.split(".")[-1] in disallowed:
                continue

            file_list.append(module_path)

    return file_list