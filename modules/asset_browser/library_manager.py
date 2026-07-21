import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath
import bpy
from bpy.types import Operator
from .gen_functions import openFolder
from .runtime import _get_reme_preferences
from .asset.re_asset_operators import (
    WM_OT_FetchREAssetThumbnails,
    WM_OT_ImportREAssetLibraryFromCatalog,
    WM_OT_InitializeREAssetLibrary
)

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

def _validate_archive_member(member_name):
    normalized_name = member_name.replace("\\", "/")
    relative_path = PurePosixPath(normalized_name)

    if relative_path.is_absolute():
        raise ValueError(f"Archive contains an absolute path: {member_name}")

    if ".." in relative_path.parts:
        raise ValueError(f"Archive contains a parent directory path: {member_name}")

    if any(":" in part for part in relative_path.parts):
        raise ValueError(f"Archive contains an invalid drive path: {member_name}")

    return relative_path

def _extract_library_package(package_path, library_root):
    package_path = Path(package_path)
    library_root = Path(library_root)
    library_root.mkdir(parents=True, exist_ok=True)
    resolved_root = library_root.resolve()

    validated_members = []
    game_info_entries = []

    with zipfile.ZipFile(package_path, "r") as archive:
        for member in archive.infolist():
            relative_path = _validate_archive_member(member.filename)

            if not relative_path.parts:
                continue

            destination = resolved_root.joinpath(*relative_path.parts).resolve()

            if (destination != resolved_root and resolved_root not in destination.parents):
                raise ValueError(f"Archive path escapes the library folder: {member.filename}")

            game_info_match = re.fullmatch(r"GameInfo_(.+)\.json", relative_path.name, flags=re.IGNORECASE)

            if game_info_match:
                game_info_entries.append((game_info_match.group(1), relative_path.parent))

            validated_members.append((member, relative_path, destination))

        if len(game_info_entries) != 1:
            raise ValueError("The package must contain exactly one GameInfo file")

        game_name, game_info_parent = game_info_entries[0]

        if (len(game_info_parent.parts) != 1 or game_info_parent.parts[0].casefold() != game_name.casefold()):
            raise ValueError("The GameInfo file must be inside its matching top level game folder.")

        for member, relative_path, destination in validated_members:
            normalized_name = member.filename.replace("\\", "/")

            if member.is_dir() or normalized_name.endswith("/"):
                destination.mkdir(parents=True, exist_ok=True)
                continue
            
            destination.parent.mkdir(parents=True, exist_ok=True)

            with archive.open(member, "r") as source:
                with destination.open("wb") as output:
                    shutil.copyfileobj(source, output)

    library_directory = resolved_root / game_info_parent.parts[0]
    return game_name, library_directory

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
    WM_OT_FetchREAssetThumbnails,
    WM_OT_ImportREAssetLibraryFromCatalog,
    WM_OT_InitializeREAssetLibrary,
    WM_OT_DetectREAssetLibraries,
    WM_OT_OpenREAssetLibraryFolder
)