import re
import shutil
import zipfile
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
import bpy
from bpy.types import Operator
from bpy.props import StringProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper
from .gen_functions import openFolder, formatByteSize
from .runtime import _get_reme_preferences
from .asset.re_asset_operators import (
    WM_OT_FetchREAssetThumbnails,
    WM_OT_ImportREAssetLibraryFromCatalog,
    WM_OT_InitializeREAssetLibrary,
    downloadREAssetLibDirectory,
    download_file_from_google_drive,
    getFileCRC
)

RE_ASSET_LIBRARY_PREFIX = "RE Assets - "

_download_library_entries = []
_download_library_enum_items = []

_REQUIRED_DOWNLOAD_FIELDS = frozenset({
    "displayName",
    "gameName",
    "URL",
    "CRC",
    "compressedSize",
    "uncompressedSize"
})

def _refresh_download_library_entries():
    directory = downloadREAssetLibDirectory()
    library_list = directory.get("libraryList") if isinstance(directory, dict) else None

    _download_library_entries.clear()
    _download_library_enum_items.clear()

    if not isinstance(library_list, list):
        return 0

    for entry in library_list:
        if not isinstance(entry, dict):
            continue

        if not _REQUIRED_DOWNLOAD_FIELDS.issubset(entry):
            continue

        entry_index = len(_download_library_entries)
        description = str(entry.get("releaseDescription", ""))
        description = description.replace("\r", " ").replace("\n", " ")

        _download_library_entries.append(entry)
        _download_library_enum_items.append((
            str(entry_index),
            str(entry["displayName"]),
            description
        ))

    return len(_download_library_entries)

def _get_download_library_items(self, context):
    return _download_library_enum_items

def _get_library_root():
    preferences = _get_reme_preferences()
    return Path(bpy.path.abspath(preferences.assetLibraryPath)).expanduser()

def _find_asset_library(name):
    libraries = bpy.context.preferences.filepaths.asset_libraries

    for library in libraries:
        if library.name == name:
            return library
    
    return None

def _start_library_initialization(output_blend):
    output_blend = Path(output_blend)
    initialize_script = (
        Path(__file__).resolve().parent
        / "Resources"
        / "Scripts"
        / "initializeLibrary.py"
    )

    if not output_blend.is_file():
        raise ValueError(f"Asset Library blend file is missing: {output_blend}")

    if not initialize_script.is_file():
        raise ValueError(f"Asset Library initialization script is missing: {initialize_script}")

    command = [
        bpy.app.binary_path,
        "--background",
        str(output_blend),
        "--python",
        str(initialize_script)
    ]
    process_options = {}

    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        process_options["creationflags"] = subprocess.CREATE_NO_WINDOW

    return subprocess.Popen(command, **process_options)

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

class WM_OT_DownloadREAssetLibrary(Operator):
    bl_idname = "re_asset.downloadlibrary"
    bl_label = "Download RE Asset Library"
    bl_description = "Download and install a RE Asset Library"
    bl_options = {"INTERNAL"}

    selected_library: EnumProperty(
        name="Asset Library",
        description="Choose a RE Asset Library to download",
        items=_get_download_library_items
    )

    def _get_selected_entry(self):
        try:
            entry_index = int(self.selected_library)
        except (TypeError, ValueError):
            return None

        if entry_index < 0 or entry_index >= len(_download_library_entries):
            return None

        return _download_library_entries[entry_index]

    def invoke(self, context, event):
        try:
            library_count = _refresh_download_library_entries()
        except Exception as error:
            print(f"Failed to retrieve the RE Asset Library directory: {error}")
            self.report({"ERROR"}, "Could not retrieve the online Asset Library directory.")
            return {"CANCELLED"}

        if library_count == 0:
            self.report({"ERROR"}, "No downloadable RE Asset Libraries were found.")
            return {"CANCELLED"}

        self.selected_library = "0"
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "selected_library")

        entry = self._get_selected_entry()

        if entry is None:
            return

        layout.separator()

        information = layout.column(align=True)
        information.label(text=f"Game: {entry['gameName']}")
        information.label(text=f"Published: {entry.get('timestamp', 'Unknown')}")
        information.label(text=f"Download size: {formatByteSize(int(entry['compressedSize']))}")
        information.label(text=f"Installed size: {formatByteSize(int(entry['uncompressedSize']))}")

        release_description = str(entry.get("releaseDescription", "")).strip()

        if release_description:
            release_box = layout.box()
            release_box.label(text="Release notes:")

            for line in release_description.splitlines():
                release_box.label(text=line)

    def execute(self, context):
        entry = self._get_selected_entry()

        if entry is None:
            self.report({"ERROR"}, "No valid Asset Library was selected.")
            return {"CANCELLED"}

        try:
            expected_crc = int(entry["CRC"])
            compressed_size = int(entry["compressedSize"])

            if compressed_size <= 0:
                raise ValueError("Invalid download size")
        except (TypeError, ValueError) as error:
            print(f"Invalid RE Asset Library directory entry: {error}")
            self.report({"ERROR"}, "The selected library has invalid download information.")
            return {"CANCELLED"}

        game_name = str(entry["gameName"])
        display_name = str(entry["displayName"])
        file_id = str(entry["URL"])
        safe_game_name = re.sub(r"[^A-Za-z0-9_.-]", "_", game_name) or "library"

        package_path = None
        window_manager = context.window_manager
        window_manager.progress_begin(0, 100)

        try:
            with tempfile.NamedTemporaryFile(prefix=f"REME_{safe_game_name}_", suffix=".reassetlib", delete=False) as temporary_file:
                package_path = Path(temporary_file.name)

            print(f"Downloading {display_name} to {package_path}")

            for chunk_index, chunk_size in download_file_from_google_drive(file_id=file_id, destination=str(package_path)):
                download_size = (chunk_index + 1) * chunk_size
                progress = min((download_size / compressed_size) * 100, 100)
                window_manager.progress_update(progress)

            if not package_path.is_file() or package_path.stat().st_size == 0:
                raise OSError("The downloaded package is empty or missing")

            actual_crc = getFileCRC(package_path)

            if actual_crc != expected_crc:
                raise ValueError(f"CRC check failed: expected {expected_crc}, got {actual_crc}")

            print(f"CRC check passed for {display_name}")

            result = bpy.ops.re_asset.importlibrary(filepath=str(package_path))

            if "FINISHED" not in result:
                raise RuntimeError("The downloaded package could not be installed")

            self.report({"INFO"}, f"Downloaded {display_name}, Asset Library initialization started.")
            return {"FINISHED"}
        except Exception as error:
            print(f"RE Asset Library download failed: {error}")
            self.report({"ERROR"}, "Failed to download or install the Asset Library. See system console.")
            return {"CANCELLED"}
        finally:
            window_manager.progress_end()

            if package_path is not None:
                try:
                    package_path.unlink(missing_ok=True)
                except OSError as error:
                    print(f"Could not remove temporary package {package_path}: {error}")

class WM_OT_ImportREAssetLibrary(Operator, ImportHelper):
    bl_idname = "re_asset.importlibrary"
    bl_label = "Import RE Asset Library"
    bl_description = "Install a RE Asset Library from a .reassetlib package"
    bl_options = {"INTERNAL"}

    filename_ext = ".reassetlib"

    filter_glob: StringProperty(
        default="*.reassetlib",
        options={"HIDDEN"}
    )

    def execute(self, context):
        package_path = Path(bpy.path.abspath(self.filepath))

        if not package_path.is_file():
            self.report({"ERROR"}, f"Package does not exist: {package_path}")
            return {"CANCELLED"}

        if package_path.suffix.casefold() != ".reassetlib":
            self.report({"ERROR"}, "The selected file is not a .reassetlib package.")
            return {"CANCELLED"}

        try:
            library_root = _get_library_root()
            game_name, library_directory = (_extract_library_package(package_path, library_root))

            resources_root = Path(__file__).resolve().parent / "Resources"
            source_blend = (resources_root / "Blend" / "libraryBase.blend")
            initialize_script = (resources_root / "Scripts" / "initializeLibrary.py")

            game_info_path = (library_directory / f"GameInfo_{game_name}.json")
            catalog_path = (library_directory / f"REAssetCatalog_{game_name}.tsv")
            output_blend = (library_directory / f"REAssetLibrary_{game_name}.blend")

            required_files = (source_blend, initialize_script, game_info_path, catalog_path)
            missing_files = [path for path in required_files if not path.is_file()]

            if missing_files:
                missing_names = ",".join(path.name for path in missing_files)
                raise ValueError(f"Required library files are missing: {missing_names}")

            if not output_blend.exists():
                shutil.copy2(source_blend, output_blend)

            library_name = f"{RE_ASSET_LIBRARY_PREFIX}{game_name}"
            library = _find_asset_library(library_name)
            libraries = context.preferences.filepaths.asset_libraries

            if library is None:
                library = libraries.new(name=library_name, directory=str(library_directory))
            else:
                library.path = str(library_directory)

            bpy.ops.wm.save_userpref()

            _start_library_initialization(output_blend)
            self.report({"INFO"}, f"Started initializing the {game_name} Asset Library in background Blender.")
            return {"FINISHED"}
        except (
            OSError,
            ValueError,
            zipfile.BadZipFile
        ) as error:
            print(f"RE Asset Browser package installation failed: {error}")
            self.report({"ERROR"}, "Failed to install the RE Asset Library. See system console.")
            return {"CANCELLED"}

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
    WM_OT_ImportREAssetLibrary,
    WM_OT_DownloadREAssetLibrary,
    WM_OT_DetectREAssetLibraries,
    WM_OT_OpenREAssetLibraryFolder
)