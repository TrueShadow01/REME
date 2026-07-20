import json
import os
import queue
import bpy
from bpy.app.handlers import persistent
from .asset.blender_re_asset import importREMeshAsset

_execution_queue = queue.Queue()

def _get_reme_preferences():
    addon_module = __package__.split(".modules.asset_browser", 1)[0]
    return bpy.context.preferences.addons[addon_module].preferences

def _show_error(lines):
    def draw(menu, _context):
        for line in lines:
            menu.layout.label(text=line)

    bpy.context.window_manager.popup_menu(draw, title="RE Asset Browser", icon="ERROR")

def _load_game_info(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)

def _find_extracted_asset(asset, game_info, preferences):
    game_name = asset.get("~GAME", "")
    asset_type = asset.get("assetType", "")
    relative_path = asset.get("assetPath", "")
    version = game_info.get("fileVersionDict", {}).get(f"{asset_type}_VERSION")

    if not relative_path or not version:
        return None
    
    relative_path = relative_path.replace("/", os.sep).replace("\\", os.sep)
    versioned_path = f"{relative_path}.{version}"

    for chunk_entry in preferences.chunkPathList_items:
        if chunk_entry.gameName != game_name:
            continue

        candidate = os.path.join(bpy.path.abspath(chunk_entry.path), versioned_path)

        print(f"RE Asset Browser - Checking: {candidate}")

        if os.path.isfile(candidate):
            return candidate
    
    return None

def _delete_placeholder(object_name):
    placeholder = bpy.data.objects.get(object_name)

    if placeholder is not None:
        bpy.data.objects.remove(placeholder, do_unlink=True)

def _drain_execution_queue():
    while not _execution_queue.empty():
        function = _execution_queue.get_nowait()
        function()
    
    return None

def _queue_placeholder_deletion(object_name):
    _execution_queue.put(lambda name=object_name: _delete_placeholder(name))

    if not bpy.app.timers.is_registered(_drain_execution_queue):
        bpy.app.timers.register(_drain_execution_queue, first_interval=0.0)

@persistent
def asset_browser_import_post(import_context):
    import_item = next((item for item in import_context.import_items if item.id is not None and item.id.get("~TYPE") == "RE_ASSET_LIBRARY_ASSET"), None)
    if import_item is None:
        return
    
    asset = import_item.id
    print(f"RE Asset Browser - Handling: {asset.name}")
    
    placeholder_name = asset.name
    game_name = asset.get("~GAME", "UNKNOWN")
    asset_type = asset.get("assetType", "UNKNOWN")

    try:
        library_file = bpy.path.abspath(import_item.source_library.filepath)
        library_directory = os.path.dirname(library_file)
        game_info_path = os.path.join(library_directory, f"GameInfo_{game_name}.json")

        if not os.path.isfile(game_info_path):
            _show_error([f"Game information was not found for {game_name}.", game_info_path])
            return
        
        preferences = _get_reme_preferences()
        game_info = _load_game_info(game_info_path)
        asset_path = _find_extracted_asset(asset, game_info, preferences)

        if asset_path is None:
            _show_error([f"{asset.name} was not found in the configured chunk paths", f"Add the {game_name} natives folder in REME preferences."])
            return
        
        if preferences.forceExtract:
            print("RE Asset Browser - Force Extract is not yet enabled in the integration runtime. Using extracted files.")
        
        if asset_type == "MESH":
            importREMeshAsset(asset, asset_path, preferences)
        else:
            _show_error([f"{asset_type} Asset Browser imports are not enabled yet.", "The first integration milestone supports MESH assets."])
    except Exception as error:
        print(f"RE Asset Browser import failed: {error}")
        _show_error(["The RE Asset Browser import failed.", "Open Window > Toggle System Console for details."])
    finally:
        _queue_placeholder_deletion(placeholder_name)

def register():
    handlers = bpy.app.handlers.blend_import_post

    if asset_browser_import_post not in handlers:
        handlers.append(asset_browser_import_post)

def unregister():
    handlers = bpy.app.handlers.blend_import_post

    if asset_browser_import_post in handlers:
        handlers.remove(asset_browser_import_post)
    
    if bpy.app.timers.is_registered(_drain_execution_queue):
        bpy.app.timers.unregister(_drain_execution_queue)
    
    while not _execution_queue.empty():
        _execution_queue.get_nowait()