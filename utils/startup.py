# import os
#
# def load_cogs(disallowed: set):
#     file_list = []
#     for root, _, files in os.walk('extensions/commands'):
#         for filename in files:
#             if not filename.endswith('.py'):
#                 continue
#             path = f"{root}.{filename.replace('.py', '')}".replace("/", '.')
#             if path.split('.')[-1] in disallowed:
#                 continue
#             file_list.append(path)
#     return file_list

import os

def load_cogs(disallowed: set):
    file_list = []

    for root, _, files in os.walk("extensions/commands"):
        for filename in files:
            if not filename.endswith(".py") or filename.startswith("__"):
                continue

            full_path = os.path.join(root, filename)
            module_path = full_path.replace("\\", ".").replace("/", ".").replace(".py", "")

            if module_path.split(".")[-1] in disallowed:
                continue

            file_list.append(module_path)

    return file_list

