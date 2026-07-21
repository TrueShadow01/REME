from pathlib import Path
import bpy
from bpy.types import Operator
from .gen_functions import openFolder
from .runtime import _get_reme_preferences

RE_ASSET_LIBRARY_PREFIX = "RE Assets - "

def _get_library_root():
    preferences = _get_reme_preferences()
    return Path(bpy.path.abspath(preferences.assetLibraryPath)).expanduser()

def _find_asset_library(name):
    libraries = bpy.context.preferences.filepaths.asset_libraries

    for library in libraries:
        if library.name == name:
            return library
    
    return None

class WM_OT_DetectREAssetLibraries(Operator):
    bl_idname = "re_asset.detect_re_asset_library"
    bl_label = "Refresh RE Asset Libraries"
    bl_description = "Find installed RE Asset Libraries and register them with Blender's Asset Browser"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        library_root = _get_library_root()

        if not library_root.is_dir():
            self.report({"ERROR"}, f"Asset Library Path does not exist: {library_root}")
            return {"CANCELLED"}
        
        detected_count = 0
        libraries = context.preferences.filepaths.asset_libraries

        for game_directory in library_root.iterdir():
            if not game_directory.is_dir():
                continue

            game_name = game_directory.name.upper()
            blend_path = game_directory / f"REAssetLibrary_{game_name}.blend"

            if not blend_path.is_file():
                continue

            library_name = f"{RE_ASSET_LIBRARY_PREFIX}{game_name}"
            library = _find_asset_library(library_name)

            if library is None:
                library = libraries.new(name=library_name, directory=str(game_directory))
            else:
                library.path = str(game_directory)
            
            detected_count += 1
        
        bpy.ops.wm.save_userpref()

        self.report({"INFO"}, f"Detected {detected_count} RE Asset Library installation(s)")
        return {"FINISHED"}

class WM_OT_OpenREAssetLibraryFolder(Operator):
    bl_idname = "re_asset.open_re_asset_library_folder"
    bl_label = "Open RE Asset Library Folder"
    bl_description = "Open the folder containing downloaded RE Asset Libraries"

    def execute(self, context):
        library_root = _get_library_root()

        if not library_root.is_dir():
            self.report({"ERROR"}, f"Asset Library Path does not exist: {library_root}")
            return {"CANCELLED"}
        
        openFolder(str(library_root))
        return {"FINISHED"}

CLASSES = (
    WM_OT_DetectREAssetLibraries,
    WM_OT_OpenREAssetLibraryFolder
)