import re
import shutil
import zipfile
import subprocess
import tempfile
import json
from datetime import UTC, datetime
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
    getFileCRC,
    REToolListFileToREAssetCatalogAndGameInfo
)
from .library_catalog import (
    compare_file_versions,
    merge_catalog_files
)

RE_ASSET_LIBRARY_PREFIX = "RE Assets - "
UPDATE_CANDIDATE_DIRECTORY = ".update_candidate"

_download_library_entries = []
_active_packaging_processes = {}
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

def _load_json_object(file_path):
    file_path = Path(file_path)

    with file_path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)

    if not isinstance(value, dict):
        raise ValueError(f"{file_path.name} must contain a JSON object")

    return value

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

def _start_library_packaging(library_directory, game_name, output_directory, display_name, release_description, drive_file_id):
    library_directory = Path(library_directory)
    output_directory = Path(output_directory)
    packaging_script = Path(__file__).resolve().parent / "Resources" / "Scripts" / "packageLibrary.py"

    if not packaging_script.is_file():
        raise ValueError(f"Library packaging script is missing: {packaging_script}")

    output_directory.mkdir(parents=True, exist_ok=True)
    log_path = output_directory / f"package_{game_name}.log"

    command = [
        bpy.app.binary_path,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(packaging_script),
        "--",
        "--library-directory",
        str(library_directory),
        "--game-name",
        game_name,
        "--output-directory",
        str(output_directory),
        "--display-name",
        str(display_name),
        "--release-description",
        str(release_description),
        "--drive-file-id",
        str(drive_file_id)
    ]
    process_options = {}

    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        process_options["creationflags"] = subprocess.CREATE_NO_WINDOW

    log_stream = log_path.open("wb")

    try:
        process = subprocess.Popen(command, stdout=log_stream, stderr=subprocess.STDOUT, **process_options)
    except Exception:
        log_stream.close()
        raise

    return process, log_stream, log_path

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

class WM_OT_CreateREAssetLibrary(Operator, ImportHelper):
    bl_idname = "re_asset.create_library_from_list"
    bl_label = "Create RE Asset Library"
    bl_description = "Create a new RE Asset Library from an RETool list file"
    bl_options = {"INTERNAL"}

    filename_ext = ".list"

    filter_glob: StringProperty(
        default="*.list",
        options={"HIDDEN"}
    )

    game_name: StringProperty(
        name="Game Name",
        description="Short game identifier, such as SF6, RE9 or MHWilds",
        default=""
    )

    file_types: StringProperty(
        name="File Types",
        description="Comma separated file types to include. Only MESH drag importing is currently enabled in REME",
        default="mesh"
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "game_name")
        layout.prop(self, "file_types")

    def execute(self, context):
        list_path = Path(bpy.path.abspath(self.filepath))
        game_name = self.game_name.strip().upper()
        file_types = sorted({
            file_type.strip().lower()
            for file_type in self.file_types.split(",") if file_type.strip()
        })

        if not re.fullmatch(r"[A-Z0-9_]+", game_name):
            self.report({"ERROR"}, "Game Name may only contain letters, numbers and underscores.")
            return {"CANCELLED"}

        if not file_types:
            self.report({"ERROR"}, "At least one file type must be included.")
            return {"CANCELLED"}

        if not list_path.is_file():
            self.report({"ERROR"}, f"RETool list file does not exist: {list_path}")
            return {"CANCELLED"}

        if list_path.suffix.casefold() != ".list":
            self.report({"ERROR"}, "The selected file is not an RETool .list file.")
            return {"CANCELLED"}

        library_root = _get_library_root()
        library_directory = library_root / game_name

        if library_directory.exists():
            self.report({"ERROR"}, f"{game_name} already has a library folder. Use the library update workflow instead.")
            return {"CANCELLED"}

        resources_root = Path(__file__).resolve().parent / "Resources"
        source_blend = resources_root / "Blend" / "libraryBase.blend"
        initialize_script = (resources_root / "Scripts" / "initializeLibrary.py")

        missing_resources = [
            path
            for path in (source_blend, initialize_script) if not path.is_file()
        ]

        if missing_resources:
            missing_names = ", ".join(path.name for path in missing_resources)
            self.report({"ERROR"}, f"Required maintainer resources are missing: {missing_names}")
            return {"CANCELLED"}

        staging_directory = None

        try:
            library_root.mkdir(parents=True, exist_ok=True)
            staging_directory = Path(tempfile.mkdtemp(prefix=f".{game_name}_creating_", dir=library_root))

            catalog_name = f"REAssetCatalog_{game_name}.tsv"
            game_info_name = f"GameInfo_{game_name}.json"
            blend_name = f"REAssetLibrary_{game_name}.blend"
            thumbnail_name = f"REAssetLibrary_{game_name}_thumbnails"

            staging_catalog = staging_directory / catalog_name
            staging_game_info = staging_directory / game_info_name
            staging_blend = staging_directory / blend_name
            staging_thumbnails = staging_directory / thumbnail_name

            REToolListFileToREAssetCatalogAndGameInfo(str(list_path), str(staging_catalog), str(staging_game_info), file_types)

            if not staging_catalog.is_file():
                raise ValueError("Catalog generation produced no TSV file")

            if not staging_game_info.is_file():
                raise ValueError("Catalog generation produced no GameInfo file")

            shutil.copy2(source_blend, staging_blend)
            staging_thumbnails.mkdir()

            staging_directory.rename(library_directory)
            staging_directory = None

            output_blend = library_directory / blend_name
            library_name = f"{RE_ASSET_LIBRARY_PREFIX}{game_name}"
            library = _find_asset_library(library_name)
            libraries = context.preferences.filepaths.asset_libraries

            if library is None:
                library = libraries.new(name=library_name, directory=str(library_directory))
            else:
                library.path = str(library_directory)

            bpy.ops.wm.save_userpref()
            _start_library_initialization(output_blend)

            self.report({"INFO"}, f"Created the {game_name} Asset Library, background initialization started.")
            return {"FINISHED"}
        except Exception as error:
            print(f"RE Asset Library creation failed: {error}")
            self.report({"ERROR"}, "Failed to create the Asset Library. See system console.")
            return {"CANCELLED"}
        finally:
            if (staging_directory is not None and staging_directory.is_dir()):
                shutil.rmtree(staging_directory, ignore_errors=True)

class WM_OT_PrepareREAssetLibraryUpdate(Operator, ImportHelper):
    bl_idname = "re_asset.prepare_library_update"
    bl_label = "Prepare RE Asset Library Update"
    bl_description = "Generate an update candidate from a new RETool list without modifying the active library"
    bl_options = {"INTERNAL"}

    filename_ext = ".list"

    filter_glob: StringProperty(
        default="*.list",
        options={"HIDDEN"}
    )

    game_name: StringProperty(
        name="Game Name",
        description="Existing library identifier, such as SF6, RE9 or MHWILDS",
        default=""
    )

    file_types: StringProperty(
        name="File Types",
        description="Comma separated file types to include. Leave blank to retain library's current whitelist",
        default=""
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "game_name")
        layout.prop(self, "file_types")

    def execute(self, context):
        list_path = Path(bpy.path.abspath(self.filepath))
        game_name = self.game_name.strip().upper()

        if not re.fullmatch(r"[A-Z0-9_]+", game_name):
            self.report({"ERROR"}, "Game Name may only contain letters, numbers and underscores.")
            return {"CANCELLED"}

        if not list_path.is_file():
            self.report({"ERROR"}, f"RETool list file does not exist: {list_path}")
            return {"CANCELLED"}

        if list_path.suffix.casefold() != ".list":
            self.report({"ERROR"}, "The selected file is not an RETool .list file.")
            return {"CANCELLED"}

        library_directory = _get_library_root() / game_name
        catalog_name = f"REAssetCatalog_{game_name}.tsv"
        game_info_name = f"GameInfo_{game_name}.json"

        existing_catalog = library_directory / catalog_name
        existing_game_info_path = library_directory / game_info_name
        candidate_directory = library_directory / UPDATE_CANDIDATE_DIRECTORY

        required_files = (
            existing_catalog,
            existing_game_info_path
        )

        missing_files = [path for path in required_files if not path.is_file()]

        if missing_files:
            missing_names = ", ".join(path.name for path in missing_files)
            self.report({"ERROR"}, f"Existing library files are missing: {missing_names}")
            return {"CANCELLED"}

        if candidate_directory.exists():
            self.report({"ERROR"}, "An update candidate already exists. Apply or discard it before preparing another.")
            return {"CANCELLED"}

        candidate_created = False
        preparation_succeeded = False

        try:
            existing_game_info = _load_json_object(existing_game_info_path)
            file_type_text = self.file_types.strip()

            if file_type_text:
                file_types = sorted({
                    file_type.strip().lower()
                    for file_type in file_type_text.split(",") if file_type.strip()
                })
            else:
                existing_file_types = existing_game_info.get("fileTypeWhiteList")

                if not isinstance(existing_file_types, list):
                    raise ValueError("Existing GameInfo has an invalid fileTypeWhiteList")

                file_types = sorted({
                    str(file_type).strip().lower()
                    for file_type in existing_file_types if str(file_type).strip()
                })

            if not file_types:
                raise ValueError("At least one file type must be included.")

            candidate_directory.mkdir()
            candidate_created = True

            generated_catalog = candidate_directory / f"Generated_{catalog_name}"
            candidate_catalog = candidate_directory / catalog_name
            candidate_game_info_path = candidate_directory / game_info_name
            report_path = candidate_directory / "update_report.json"

            REToolListFileToREAssetCatalogAndGameInfo(str(list_path), str(generated_catalog), str(candidate_game_info_path), file_types)

            if not generated_catalog.is_file():
                raise ValueError("Updated RETool list produced no catalog")

            if not candidate_game_info_path.is_file():
                raise ValueError("Updated RETool list produced no GameInfo")

            generated_game_info = _load_json_object(candidate_game_info_path)
            report = merge_catalog_files(existing_catalog, generated_catalog, candidate_catalog)

            report["game_name"] = game_name
            report["prepared_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            report["source_list"] = str(list_path)
            report["file_types"] = file_types
            report["version_changes"] = compare_file_versions(existing_game_info, generated_game_info)
            report["added_count"] = len(report["added_assets"])
            report["removed_count"] = len(report["removed_assets"])

            with report_path.open("w", encoding="utf-8") as stream:
                json.dump(report, stream, indent=4, sort_keys=False)

            preparation_succeeded = True

            print(f"Prepared {game_name} library update: {report['added_count']} added, {report['removed_count']} removed, {len(report['version_changes'])} version changes")
            print(f"Update candidate: {candidate_directory}")

            self.report({"INFO"}, f"Prepared {game_name} update: {report['added_count']} added, {report['removed_count']} removed.")
            return {"FINISHED"}
        except Exception as error:
            print(f"Failed to prepare the {game_name} Asset Library update: {error}")
            self.report({"ERROR"}, "Failed to prepare the library update. See system console.")
            return {"CANCELLED"}
        finally:
            if (candidate_created and not preparation_succeeded and candidate_directory.is_dir()):
                shutil.rmtree(candidate_directory, ignore_errors=True)

class WM_OT_ApplyREAssetLibraryUpdate(Operator):
    bl_idname = "re_asset.apply_library_update"
    bl_label = "Apply RE Asset Library Update"
    bl_description = "Apply a prepared update and rebuild the library"
    bl_options = {"INTERNAL"}

    game_name: StringProperty(
        name="Game Name",
        description="Library identifier, such as SF6, RE9 or MHWILDS",
        default=""
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "game_name")

        game_name = self.game_name.strip().upper()

        if re.fullmatch(r"[A-Z0-9_]+", game_name):
            report_path = _get_library_root() / game_name / UPDATE_CANDIDATE_DIRECTORY / "update_report.json"

            if report_path.is_file():
                try:
                    report = _load_json_object(report_path)
                    summary = layout.box()
                    summary.label(text=f"Added assets: {report.get('added_count', 0)}")
                    summary.label(text=f"Removed assets: {report.get('removed_count', 0)}")
                    summary.label(text=f"File version changes: {len(report.get('version_changes', {}))}")
                except (OSError, ValueError, json.JSONDecodeError):
                    layout.label(text="The update report is invalid.", icon="ERROR")

        warning = layout.box()
        warning.label(text="The library blend will be rebuilt.", icon="ERROR")
        warning.label(text="Save any catalog edits before applying.")
        warning.label(text="A rollback backup will be retained.")
    
    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def execute(self, context):
        game_name = self.game_name.strip().upper()

        if not re.fullmatch(r"[A-Z0-9_]+", game_name):
            self.report({"ERROR"}, "Game Name may only contain letters, numbers and underscores.")
            return {"CANCELLED"}

        library_root = _get_library_root()
        library_directory = library_root / game_name
        candidate_directory = library_directory / UPDATE_CANDIDATE_DIRECTORY

        catalog_name = f"REAssetCatalog_{game_name}.tsv"
        game_info_name = f"GameInfo_{game_name}.json"
        blend_name = f"REAssetLibrary_{game_name}.blend"

        active_catalog = library_directory / catalog_name
        active_game_info = library_directory / game_info_name
        active_blend = library_directory / blend_name

        candidate_catalog = candidate_directory / catalog_name
        candidate_game_info = candidate_directory / game_info_name
        candidate_report = candidate_directory / "update_report.json"

        resources_root = Path(__file__).resolve().parent() / "Resources"
        source_blend = resources_root / "Blend" / "libraryBase.blend"

        required_files = (
            active_catalog,
            active_game_info,
            active_blend,
            candidate_catalog,
            candidate_game_info,
            candidate_report,
            source_blend
        )

        missing_files = [path for path in required_files if not path.is_file()]

        if missing_files:
            missing_names = ", ".join(path.name for path in missing_files)
            self.report({"ERROR"}, f"Required update files are missing: {missing_names}")
            return {"CANCELLED"}

        try:
            report = _load_json_object(candidate_report)
            new_game_info = _load_json_object(candidate_game_info)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"Failed to validate update candidate: {error}")
            self.report({"ERROR"}, "The prepared update candidate is invalid.")
            return {"CANCELLED"}

        if str(report.get("game_name", "")).upper() != game_name:
            self.report({"ERROR"}, "The update report belongs to a different game.")
            return {"CANCELLED"}

        if str(new_game_info.get("GameName", "")).upper() != game_name:
            self.report({"ERROR"}, "The candidate GameInfo belongs to a different game.")
            return {"CANCELLED"}

        current_blend_path = bpy.path.abspath(bpy.context.blend_data.filepath)

        if current_blend_path:
            try:
                if (Path(current_blend_path).resolve() == active_blend.resolve()):
                    self.report({"ERROR"}, "Close the Asset Library blend before applying its update.")
                    return {"CANCELLED"}
            except OSError:
                pass

        backup_timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
        backup_directory = library_root / "_LibraryBackups" / game_name / backup_timestamp
        backup_catalog = backup_directory / catalog_name
        backup_game_info = backup_directory / game_info_name
        backup_blend = backup_directory / blend_name
        backup_report = backup_directory / "update_report.json"

        blend_moved = False
        initialization_started = False

        try:
            backup_directory.mkdir(parents=True)

            shutil.copy2(active_catalog, backup_catalog)
            shutil.copy2(active_game_info, backup_game_info)
            shutil.copy2(candidate_report, backup_report)

            active_blend.replace(backup_blend)
            blend_moved = True

            shutil.copy2(candidate_catalog, active_catalog)
            shutil.copy2(candidate_game_info, active_game_info)
            shutil.copy2(source_blend, active_blend)

            _start_library_initialization(active_blend)
            initialization_started = True

            try:
                shutil.rmtree(candidate_directory)
            except OSError as error:
                print(f"Could not remove update candidate {candidate_directory}: {error}")

            print(f"Applied {game_name} library update. Rollback backup: {backup_directory}")
            self.report({"INFO"}, f"Applied {game_name} update, background initialization started.")
            return {"FINISHED"}
        except Exception as error:
            print(f"Failed to apply the {game_name} Asset Library update: {error}")

            if not initialization_started:
                try:
                    if blend_moved and backup_blend.is_file():
                        if active_blend.exists():
                            active_blend.unlink()

                        backup_blend.replace(active_blend)

                    if backup_catalog.is_file():
                        shutil.copy2(backup_catalog, active_catalog)

                    if backup_game_info.is_file():
                        shutil.copy2(backup_game_info, active_game_info)

                    print("Restored the previous library files.")
                except OSError as rollback_error:
                    print(f"Library rollback failed: {rollback_error}")
            
            self.report({"ERROR"}, "Failed to apply the library update. See system console.")
            return {"CANCELLED"}

class WM_OT_DiscardREAssetLibraryUpdate(Operator):
    bl_idname = "re_asset.discard_library_update"
    bl_label = "Discard RE Asset Library Update"
    bl_description = "Delete a prepared update candidate without changing the active library"
    bl_options = {"INTERNAL"}

    game_name: StringProperty(
        name="Game Name",
        description="Library identifier, such as SF6, RE9 or MHWILDS",
        default=""
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "game_name")

        warning = layout.box()
        warning.label(text="The prepared update candidate will be deleted.", icon="ERROR")
        warning.label(text="The active library and rollback backups will not be changed.")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=520)

    def execute(self, context):
        game_name = self.game_name.strip().upper()

        if not re.fullmatch(r"[A-Z0-9_]+", game_name):
            self.report({"ERROR"}, "Game Name may only contain letters, numbers and underscores.")
            return {"CANCELLED"}

        library_directory = _get_library_root() / game_name
        candidate_directory = library_directory / UPDATE_CANDIDATE_DIRECTORY

        if not candidate_directory.is_dir():
            self.report({"ERROR"}, f"No prepared update exists for {game_name}.")
            return {"CANCELLED"}

        try:
            expected_candidate = library_directory.resolve() / UPDATE_CANDIDATE_DIRECTORY
            resolved_candidate = candidate_directory.resolve()
        except OSError as error:
            print(f"Could not validate update candidate path: {error}")
            self.report({"ERROR"}, "Could not validate the update candidate path.")
            return {"CANCELLED"}

        if resolved_candidate != expected_candidate:
            self.report({"ERROR"}, "Refusing to remove an unexpected update candidate path.")
            return {"CANCELLED"}

        try:
            shutil.rmtree(candidate_directory)
        except OSError as error:
            print(f"Could not discard update candidate {candidate_directory}: {error}")
            self.report({"ERROR"}, "Could not discard the prepared update. See system console.")
            return {"CANCELLED"}

        print(f"Discarded the prepared {game_name} Asset Library update.")
        self.report({"INFO"}, f"Discarded the prepared {game_name} update.")
        return {"FINISHED"}

class WM_OT_PackageREAssetLibrary(Operator):
    bl_idname = "re_asset.package_library"
    bl_label = "Package RE Asset Library"
    bl_description = "Create a distributable .reassetlib package and directory metadata"
    bl_options = {"INTERNAL"}

    _packaging_process = None
    _packaging_log_stream = None
    _packaging_log_path = None
    _packaging_timer = None
    _packaging_output_directory = None
    _packaging_game_name = None

    game_name: StringProperty(
        name="Game Name",
        description="Library identifier, such as SF6, RE9 or MHWILDS",
        default=""
    )

    display_name: StringProperty(
        name="Display Name",
        description="Public library name, such as Street Fighter 6 or Resident Evil 9",
        default=""
    )

    release_description: StringProperty(
        name="Release Description",
        description="Description of the game version and library changes",
        default=""
    )

    drive_file_id: StringProperty(
        name="Google Drive File ID",
        description="Optional Google Drive File ID. Leave blank until the package has been uploaded",
        default=""
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "game_name")
        layout.prop(self, "display_name")
        layout.prop(self, "release_description")
        layout.prop(self, "drive_file_id")

        information = layout.box()
        information.label(text="Wait for background library initialization to finish before packaging.", icon="INFO")
        information.label(text="Packages are saved under _Packages inside the Asset Library Path.")
        information.label(text="Packaging runs in the background, Blender remains usable.")

        if not self.drive_file_id.strip():
            information.label(text="The directory entry URL will be blank until a Drive File ID is supplied.")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=600)

    def _finish_background_packaging(self, context):
        process = self._packaging_process
        game_name = self._packaging_game_name

        if self._packaging_timer is not None:
            context.window_manager.event_timer_remove(self._packaging_timer)
            self._packaging_timer = None

        if self._packaging_log_stream is not None:
            self._packaging_log_stream.close()
            self._packaging_log_stream = None

        if (game_name and _active_packaging_processes.get(game_name) is process):
            _active_packaging_processes.pop(game_name, None)

        self._packaging_process = None

    def modal(self, context, event):
        if event.type != "TIMER":
            return {"PASS_THROUGH"}

        process = self._packaging_process

        if process is None:
            self._finish_background_packaging(context)
            self.report({"ERROR"}, "The background packaging process was lost.")
            return {"CANCELLED"}

        return_code = process.poll()
        if return_code is None:
            return {"PASS_THROUGH"}

        game_name = self._packaging_game_name
        output_directory = self._packaging_output_directory
        log_path = self._packaging_log_path

        self._finish_background_packaging(context)

        if return_code != 0:
            print(f"Background packaging failed for {game_name}. Log: {log_path}")

            try:
                log_output = log_path.read_text(encoding="utf-8", errors="replace").strip()

                if log_output:
                    print(log_output)
            except OSError as error:
                print(f"Could not read packaging log: {error}")

            self.report({"ERROR"}, f"Failed to package {game_name}. See packaging log.")
            return {"CANCELLED"}

        package_path = output_directory / f"{game_name}.reassetlib"
        metadata_path = output_directory / f"REAssetLib_entry_{game_name}.json"

        try:
            if not package_path.is_file():
                raise ValueError(f"Package was not created: {package_path}")

            directory_entry = _load_json_object(metadata_path)
        except (OSError, ValueError) as error:
            print(f"Background packaging output is invalid: {error}")
            self.report({"ERROR"}, "Packaging finished without valid output files.")
            return {"CANCELLED"}

        print(f"Created Asset Library package: {package_path}")
        print(f"Created directory metadata: {metadata_path}")
        print(json.dumps(directory_entry, indent=4, sort_keys=False))

        try:
            openFolder(str(output_directory))
        except Exception as error:
            print(f"Could not open packaging output folder: {error}")

        self.report({"INFO"}, f"Packaged {game_name} Asset Library.")
        return {"FINISHED"}

    def execute(self, context):
        game_name = self.game_name.strip().upper()
        drive_file_id = self.drive_file_id.strip()

        if not re.fullmatch(r"[A-Z0-9_]+", game_name):
            self.report({"ERROR"}, "Game Name may only contain letters, numbers and underscores.")
            return {"CANCELLED"}

        if (drive_file_id and not re.fullmatch(r"[A-Za-z0-9_-]+", drive_file_id)):
            self.report({"ERROR"}, "Enter only the Google Drive File ID, not its full URL.")
            return {"CANCELLED"}

        existing_process = _active_packaging_processes.get(game_name)
        if existing_process is not None:
            if existing_process.poll() is None:
                self.report({"ERROR"}, f"{game_name} is already being packaged.")
                return {"CANCELLED"}

            _active_packaging_processes.pop(game_name, None)

        library_root = _get_library_root()
        library_directory = library_root / game_name
        candidate_directory = library_directory / UPDATE_CANDIDATE_DIRECTORY
        output_directory = library_root / "_Packages" / game_name

        if candidate_directory.exists():
            self.report({"ERROR"}, "Apply or discard the prepared update before packaging.")
            return {"CANCELLED"}

        try:
            process, log_stream, log_path = _start_library_packaging(library_directory, game_name, output_directory, self.display_name, self.release_description, drive_file_id)
        except Exception as error:
            print(f"Failed to start background packaging for {game_name}: {error}")
            self.report({"ERROR"}, "Could not start background packaging. See system console.")
            return {"CANCELLED"}

        self._packaging_process = process
        self._packaging_log_stream = log_stream
        self._packaging_log_path = log_path
        self._packaging_output_directory = output_directory
        self._packaging_game_name = game_name

        _active_packaging_processes[game_name] = process

        self._packaging_timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window_manager.modal_handler_add(self)

        print(f"Started background packaging for {game_name}. Log: {log_path}")
        self.report({"INFO"}, f"Started packaging {game_name} in the background.")
        return {"RUNNING_MODAL"}

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
    WM_OT_CreateREAssetLibrary,
    WM_OT_PrepareREAssetLibraryUpdate,
    WM_OT_ApplyREAssetLibraryUpdate,
    WM_OT_DiscardREAssetLibraryUpdate,
    WM_OT_PackageREAssetLibrary,
    WM_OT_ImportREAssetLibrary,
    WM_OT_DownloadREAssetLibrary,
    WM_OT_DetectREAssetLibraries,
    WM_OT_OpenREAssetLibraryFolder
)