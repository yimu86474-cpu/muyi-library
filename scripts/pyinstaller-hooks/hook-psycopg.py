from PyInstaller.utils.hooks import copy_metadata

# Keep the driver as Python source which can be inspected and replaced.
module_collection_mode = "py"
datas = copy_metadata("psycopg")
