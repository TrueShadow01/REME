# Author: NSA Cloud
import os
import struct

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    StringProperty,
)
from bpy.types import Operator

from ..blender_utils import showErrorMessageBox
from ..gen_functions import splitNativesPath
from .blender_re_mesh import solveRepeatedUVs
from .re_mesh_propertyGroups import ExporterNodePropertyGroup, MESH_UL_REExporterList


class WM_OT_DeleteLoose(Operator):
    bl_label = "Delete Loose Geometry"
    bl_idname = "re_mesh_cm.delete_loose"
    bl_description = "Deletes loose vertices and edges with no faces on selected meshes"

    def execute(self, context):
        if context.selected_objects != []:
            selection = context.selected_objects
        else:
            selection = bpy.context.scene.objects
        for selectedObj in selection:
            if selectedObj.type == "MESH":
                context.view_layer.objects.active = selectedObj
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                print(f"Deleted loose geometry on {selectedObj.name}")
                bpy.ops.mesh.delete_loose()
                bpy.ops.object.mode_set(mode="OBJECT")
        if context.selected_objects == []:
            self.report({"INFO"}, "Deleted loose geometry on all objects")
        else:
            self.report({"INFO"}, "Deleted loose geometry on selected objects")
        return {"FINISHED"}


class WM_OT_RenameMeshToREFormat(Operator):
    bl_label = "Rename Meshes"
    bl_idname = "re_mesh_cm.rename_meshes"
    bl_description = "Renames selected meshes to RE mesh naming scheme (Example: Group_0_Sub_0__Shirts_Mat)"

    def execute(self, context):
        groupIndexDict = dict()
        if context.selected_objects != []:
            selection = context.selected_objects
        else:
            selection = bpy.context.scene.objects
        for selectedObj in selection:
            if selectedObj.type == "MESH":
                if "Group_" in selectedObj.name:
                    try:
                        groupID = int(selectedObj.name.split("Group_")[1].split("_")[0])
                    except:
                        pass
                else:
                    print(
                        "Could not parse group ID in {selectedObj.name}, setting to 0"
                    )
                    groupID = 0
                if groupID not in groupIndexDict:
                    groupIndexDict[groupID] = 0
                if len(selectedObj.data.materials) > 0:
                    materialName = (
                        selectedObj.data.materials[0].name.split(".", 1)[0].strip()
                    )
                else:
                    materialName = "NO_MATERIAL"
                selectedObj.name = f"Group_{str(groupID)}_Sub_{str(groupIndexDict[groupID])}__{materialName}"
                groupIndexDict[groupID] += 1

        if context.selected_objects == []:
            self.report({"INFO"}, "Renamed all objects to RE Mesh format")
        else:
            self.report({"INFO"}, "Renamed selected objects to RE Mesh format")
        return {"FINISHED"}


# Weights


class WM_OT_RemoveZeroWeightVertexGroups(Operator):
    """Remove all vertex groups that have no weight assigned to them"""

    bl_label = "Remove Empty Vertex Groups"
    bl_idname = "re_mesh_cm.remove_zero_weight_vertex_groups"

    def execute(self, context):
        if context.selected_objects != []:
            selection = context.selected_objects
        else:
            selection = bpy.context.scene.objects
        for obj in selection:
            emptyGroupList = []
            for vertexGroup in obj.vertex_groups:
                if not any(
                    vertexGroup.index in [g.group for g in v.groups]
                    for v in obj.data.vertices
                ):
                    emptyGroupList.append(vertexGroup)
            for group in emptyGroupList:
                obj.vertex_groups.remove(group)
        if context.selected_objects == []:
            self.report({"INFO"}, "Removed empty vertex groups on all objects.")
        else:
            self.report({"INFO"}, "Removed empty vertex groups on selected objects.")
        return {"FINISHED"}


class WM_OT_LimitTotalNormalizeAll(Operator):
    """Limits the amount of bones influences per vertex and normalizes the weights of all vertex groups for all selected meshes"""

    bl_label = "Limit Total and Normalize All"
    bl_idname = "re_mesh_cm.limit_total_normalize"
    maxWeights: EnumProperty(
        name="Weight Limit",
        description="Apply Data to attribute.",
        items=[
            ("4", "4 Weights", "Safest option but potentially lower weight quality"),
            ("6", "6 Weights (SF6)", "Maximum amount of weights for SF6"),
            ("8", "8 Weights", "Note that certain materials may not support 8 weights"),
            (
                "12",
                "12 Weights (MH Wilds or Newer)",
                "This is only supported in MH Wilds (and newer potentially)\nNote that some materials may not support 12 weights",
            ),
        ],
        default="4",
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        weightLimit = int(self.maxWeights)
        if context.selected_objects != []:
            selection = context.selected_objects
        else:
            selection = bpy.context.scene.objects
        for selectedObj in selection:
            if selectedObj.type == "MESH":
                context.view_layer.objects.active = selectedObj
                bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
                try:
                    bpy.ops.object.vertex_group_limit_total(limit=weightLimit)
                    bpy.ops.object.vertex_group_normalize_all(lock_active=False)
                except:
                    pass
                print(
                    f"Limited total weights to {weightLimit} and normalized {selectedObj.name}"
                )
                bpy.ops.object.mode_set(mode="OBJECT")
        if context.selected_objects == []:
            self.report(
                {"INFO"},
                f"Limited total weights to {weightLimit} and normalized on all objects",
            )
        else:
            self.report(
                {"INFO"},
                f"Limited total weights to {weightLimit} and normalized on selected objects",
            )
        return {"FINISHED"}


class WM_OT_CreateMeshCollection(Operator):
    bl_label = "Create Mesh Collection"
    bl_idname = "re_mesh_cm.create_mesh_collection"
    bl_description = "Creates a collection for RE Engine meshes"
    bl_options = {"UNDO"}
    collectionName: bpy.props.StringProperty(
        name="Mesh Name",
        description="The name of the newly created mesh collection",
        default="newMesh",
    )
    lodCount: bpy.props.IntProperty(
        name="LOD Amount",
        description="The amount of lower quality model levels to switch between.\nLeave this at 1 unless you have a set of lower quality models",
        default=1,
        min=1,
        max=8,
    )

    def execute(self, context):
        if self.collectionName.strip() != "":
            collection = bpy.data.collections.new(self.collectionName + ".mesh")
            bpy.context.scene["REMeshLastImportedCollection"] = collection.name
            bpy.context.scene.collection.children.link(collection)
            collection.color_tag = "COLOR_01"
            collection["~TYPE"] = "RE_MESH_COLLECTION"
            bpy.context.scene.re_mdf_toolpanel.meshCollection = collection
            if self.lodCount > 1:
                for i in range(self.lodCount):
                    lodCollection = bpy.data.collections.new(
                        f"Main Mesh LOD{str(i)} - {collection.name}"
                    )
                    lodCollection["LOD Distance"] = 0.167932 * (i + 1)
                    collection.children.link(lodCollection)
            self.report({"INFO"}, "Created new RE mesh collection.")
            return {"FINISHED"}
        else:
            self.report({"ERROR"}, "Invalid mesh collection name.")
            return {"CANCELLED"}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


EXPORTER_WINDOW_SIZE = 800
SPLIT_FACTOR = 0.4


def update_checkAllItems(self, context):
    if self.checkAllItems:
        for item in self.itemList_items:
            item.enabled = True
        self.checkAllItems = False


def update_uncheckAllItems(self, context):
    if self.uncheckAllItems:
        for item in self.itemList_items:
            item.enabled = False
        self.uncheckAllItems = False


COLLECTION_TYPES = frozenset(
    [
        "RE_MESH_COLLECTION",
        "RE_MDF_COLLECTION",
        "RE_CHAIN_COLLECTION",
        "RE_CLSP_COLLECTION",
        "RE_SFUR_COLLECTION",
    ]
)


def checkForChildRECollectionsRecursive(
    collection,
):  # For checking if a collection should be included in the export list
    if collection.get("~TYPE") in COLLECTION_TYPES:
        return True
    else:
        for child in collection.children:
            if checkForChildRECollectionsRecursive(child):
                return True
    return False


def determineExportPath(modDirectory, exportType, assetPath, scene):
    filePath = ""
    fileVersion = ""
    if exportType == "MESH":
        if "REMeshLastExportedMeshVersion" in scene:
            fileVersion = "." + str(scene["REMeshLastExportedMeshVersion"])
        elif "REMeshLastImportedMeshVersion" in scene:
            fileVersion = "." + str(scene["REMeshLastImportedMeshVersion"])

    elif exportType == "MDF":
        if "REMeshLastExportedMDFVersion" in scene:
            fileVersion = "." + str(scene["REMeshLastExportedMDFVersion"])
        elif "REMeshLastImportedMDFVersion" in scene:
            fileVersion = "." + str(scene["REMeshLastImportedMDFVersion"])

    elif exportType == "FBXSKEL":
        if "REMeshLastExportedFBXSkelVersion" in scene:
            fileVersion = "." + str(scene["REMeshLastExportedFBXSkelVersion"])
        elif "REMeshLastImportedFBXSkelVersion" in scene:
            fileVersion = "." + str(scene["REMeshLastImportedFBXSkelVersion"])

    elif exportType == "SFUR":
        if "REMeshLastExportedSFURVersion" in scene:
            fileVersion = "." + str(scene["REMeshLastExportedSFURVersion"])
        elif "REMeshLastImportedSFURVersion" in scene:
            fileVersion = "." + str(scene["REMeshLastImportedSFURVersion"])

    elif exportType == "CHAIN":
        if "REChainLastExportedChainVersion" in scene:
            fileVersion = "." + str(scene["REChainLastExportedChainVersion"])
        elif "REChainLastImportedChainVersion" in scene:
            fileVersion = "." + str(scene["REChainLastImportedChainVersion"])

    elif exportType == "CHAIN2":
        if "REChainLastExportedChain2Version" in scene:
            fileVersion = "." + str(scene["REChainLastExportedChain2Version"])
        elif "REChainLastImportedChain2Version" in scene:
            fileVersion = "." + str(scene["REChainLastImportedChain2Version"])

    elif exportType == "CLSP":
        if "REChainLastExportedCLSPVersion" in scene:
            fileVersion = "." + str(scene["REChainLastExportedCLSPVersion"])
        elif "REChainLastImportedChain2Version" in scene:
            fileVersion = "." + str(scene["REChainLastImportedCLSPVersion"])
    filePath = os.path.join(modDirectory, assetPath + fileVersion)
    return filePath


def populateCollectionList(itemList, collection, recursionLevel, parentName):

    item = itemList.add()
    item.name = collection.name
    if collection.color_tag == "NONE":
        item.icon = "OUTLINER_COLLECTION"
    else:
        item.icon = f"COLLECTION_{collection.color_tag}"
    item.hierarchyLevel = recursionLevel
    item.parentName = parentName

    recursionLevel += 1
    if collection.get("~TYPE") not in COLLECTION_TYPES:
        for child in collection.children:
            if checkForChildRECollectionsRecursive(child):
                item.hasChild = True
                populateCollectionList(
                    itemList, child, recursionLevel, parentName=collection.name
                )
    else:
        item.invalid = True  # Will be set to valid once a usable path is entered
        if "BatchExport_enabled" in collection:
            item.enabled = bool(collection["BatchExport_enabled"])
        if "BatchExport_path" in collection:
            item.path = collection["BatchExport_path"]
            # print(f"Batch Export: Loaded previous values for {item.name}")

        if collection["~TYPE"] == "RE_MESH_COLLECTION":
            item.exportType = "MESH"

            if "BatchExport_exportAllLODs" in collection:
                try:
                    item.exportAllLODs = collection["BatchExport_exportAllLODs"]
                    item.preserveSharpEdges = collection[
                        "BatchExport_preserveSharpEdges"
                    ]
                    item.rotate90 = collection["BatchExport_rotate90"]
                    if "BatchExport_exportBlendShapes" in collection:
                        item.exportBlendShapes = collection[
                            "BatchExport_exportBlendShapes"
                        ]
                    item.useBlenderMaterialName = collection[
                        "BatchExport_useBlenderMaterialName"
                    ]
                    item.preserveBoneMatrices = collection[
                        "BatchExport_preserveBoneMatrices"
                    ]
                    item.exportBoundingBoxes = collection[
                        "BatchExport_exportBoundingBoxes"
                    ]
                except Exception as err:
                    print(f"Failed to load default values for {item.name} - {str(err)}")

        elif collection["~TYPE"] == "RE_MDF_COLLECTION":
            item.exportType = "MDF"
        elif collection["~TYPE"] == "RE_CHAIN_COLLECTION":
            if ".chain2" in item.name:
                item.exportType = "CHAIN2"
            else:
                item.exportType = "CHAIN"
        elif collection["~TYPE"] == "RE_CLSP_COLLECTION":
            item.exportType = "CLSP"
        elif collection["~TYPE"] == "RE_SFUR_COLLECTION":
            item.exportType = "SFUR"

        if item.path == "":
            if bpy.context.scene.re_mdf_toolpanel.modDirectory != "":
                try:
                    split = splitNativesPath(
                        bpy.context.scene.re_mdf_toolpanel.modDirectory
                    )
                    if split is not None:
                        assetPath = collection.get("~ASSETPATH", None)
                        if assetPath is not None:
                            item.path = determineExportPath(
                                split[0],
                                item.exportType,
                                assetPath.replace("/", os.sep),
                                bpy.context.scene,
                            )
                except Exception as err:
                    print(
                        f"Batch Export: Cannot auto determine path for {item.name}: {str(err)}"
                    )


class WM_OT_REBatchExporter(Operator):
    bl_label = "RE Batch Exporter"
    bl_idname = "re_mesh_cm.batch_exporter"
    bl_description = "Export all selected RE Engine files quickly"
    bl_options = {"INTERNAL"}

    itemList_items: bpy.props.CollectionProperty(type=ExporterNodePropertyGroup)
    itemList_index: bpy.props.IntProperty(name="")

    checkAllItems: bpy.props.BoolProperty(
        name="Check All Items",
        description="Select all files to be exported",
        default=False,
        update=update_checkAllItems,
    )
    uncheckAllItems: bpy.props.BoolProperty(
        name="Uncheck All Items",
        description="Deselect all files to be exported",
        default=False,
        update=update_uncheckAllItems,
    )

    skipPrompt: bpy.props.BoolProperty(  # Not exposed to user
        name="Skip Conversion Prompt", description="", default=False
    )

    def execute(self, context):
        print("Batch export started.")

        # Save which files are enabled
        for item in self.itemList_items:
            if item.exportType != "":
                if item.exportType == "FBXSKEL":
                    bpy.data.objects[item.name]["BatchExport_enabled"] = item.enabled
                else:
                    bpy.data.collections[item.name]["BatchExport_enabled"] = (
                        item.enabled
                    )

        exportItemList = [
            item
            for item in self.itemList_items
            if not item.hasChild and item.enabled and item.exportType != ""
        ]
        failCount = 0
        for index, exportItem in enumerate(exportItemList):
            if exportItem.invalid:
                print(
                    f"Skipping {exportItem.name} ({index + 1}/{len(exportItemList)}) due to an invalid export path: {exportItem.path}"
                )
                failCount += 1
                continue

            print(
                f"Exporting File: {exportItem.name} ({index + 1}/{len(exportItemList)})"
            )
            os.makedirs(os.path.split(exportItem.path)[0], exist_ok=True)
            if exportItem.exportType == "MESH":
                try:
                    bpy.ops.re_mesh_cm.exportfile(
                        filepath=exportItem.path,
                        targetCollection=exportItem.name,
                        exportAllLODs=exportItem.exportAllLODs,
                        exportBlendShapes=exportItem.exportBlendShapes,
                        autoSolveRepeatedUVs=exportItem.autoSolveRepeatedUVs,
                        preserveSharpEdges=exportItem.preserveSharpEdges,
                        rotate90=exportItem.rotate90,
                        useBlenderMaterialName=exportItem.useBlenderMaterialName,
                        preserveBoneMatrices=exportItem.preserveBoneMatrices,
                        exportBoundingBoxes=exportItem.exportBoundingBoxes,
                    )
                except Exception as err:
                    print(f"Mesh Export Failed: {str(err)}")
                    failCount += 1
            elif exportItem.exportType == "MDF":
                try:
                    bpy.ops.re_mdf.exportfile(
                        filepath=exportItem.path,
                        targetCollection=exportItem.name,
                    )
                except Exception as err:
                    print(f"MDF Export Failed: {str(err)}")
                    failCount += 1
            elif exportItem.exportType == "FBXSKEL":
                try:
                    bpy.ops.re_fbxskel.exportfile(
                        filepath=exportItem.path,
                        targetArmature=exportItem.name,
                    )
                except Exception as err:
                    print(f"FBXSkel Export Failed: {str(err)}")
                    failCount += 1
            elif exportItem.exportType == "CHAIN":
                if hasattr(bpy.types, "OBJECT_PT_chain_object_mode_panel"):
                    try:
                        bpy.ops.re_chain.exportfile(
                            filepath=exportItem.path,
                            targetCollection=exportItem.name,
                        )
                    except Exception as err:
                        print(f"Chain Export Failed: {str(err)}")
                        failCount += 1
                else:
                    print(
                        "RE Chain Editor is not installed. Skipping batch export entry."
                    )
                    failCount += 1
            elif exportItem.exportType == "CHAIN2":
                if hasattr(bpy.types, "OBJECT_PT_chain_object_mode_panel"):
                    try:
                        bpy.ops.re_chain2.exportfile(
                            filepath=exportItem.path,
                            targetCollection=exportItem.name,
                        )
                    except Exception as err:
                        print(f"Chain2 Export Failed: {str(err)}")
                        failCount += 1
                else:
                    print(
                        "RE Chain Editor is not installed. Skipping batch export entry."
                    )
                    failCount += 1
            elif exportItem.exportType == "CLSP":
                if hasattr(bpy.types, "OBJECT_PT_chain_object_mode_panel"):
                    try:
                        bpy.ops.re_clsp.exportfile(
                            filepath=exportItem.path,
                            targetCollection=exportItem.name,
                        )
                    except Exception as err:
                        print(f"Chain Export Failed: {str(err)}")
                        failCount += 1
                else:
                    print(
                        "RE Chain Editor is not installed. Skipping batch export entry."
                    )
                    failCount += 1
            elif exportItem.exportType == "SFUR":
                try:
                    bpy.ops.re_sfur.exportfile(
                        filepath=exportItem.path,
                        targetCollection=exportItem.name,
                    )
                except Exception as err:
                    print(f"SFUR Export Failed: {str(err)}")
                    failCount += 1
            else:
                print(f"Unsupported File Type ({exportItem.exportType}), skipping")
                failCount += 1
        if failCount != 0:
            showErrorMessageBox(
                f"{failCount}/{len(exportItemList)} files failed to export.\nSee console for details. (Window > Toggle System Console)"
            )
        else:
            self.report({"INFO"}, "Batch export finished successfully.")
        return {"FINISHED"}

    def invoke(self, context, event):
        region = bpy.context.region
        centerX = region.width // 2
        centerY = region.height

        # currentX = event.mouse_region_X
        # currentY = event.mouse_region_Y

        parentDict = {None: None}
        for collection in bpy.data.collections:
            parentDict[collection] = None

        for collection in bpy.data.collections:
            for child in collection.children:
                parentDict[child] = collection
        collectionRoots = set()
        for collection in bpy.data.collections:
            if collection.get("~TYPE") in COLLECTION_TYPES:
                parentCol = parentDict[collection]
                # print(f"Found supported collection: {collection.name},Parent:{parentDict[collection]}")

                while parentDict[parentCol] is not None:
                    parentCol = parentDict[parentCol]
                else:
                    # print(f"Root collection:{parentCol.name}")
                    if parentCol is None:
                        collectionRoots.add(collection)
                    else:
                        collectionRoots.add(parentCol)

        # Populate list
        self.itemList_items.clear()
        for collection in collectionRoots:
            populateCollectionList(
                self.itemList_items, collection, recursionLevel=0, parentName=""
            )
        # print(f"Item Count: {len(self.itemList_items)}")
        # Add fbxskel armatures for export
        for armatureObj in [
            obj
            for obj in bpy.data.objects
            if obj.type == "ARMATURE"
            and (".fbxskel" in obj.name.lower() or (".skeleton" in obj.name.lower()))
        ]:
            item = self.itemList_items.add()
            item.name = armatureObj.name
            item.icon = "ARMATURE_DATA"
            item.exportType = "FBXSKEL"
            item.invalid = True
            if "BatchExport_enabled" in armatureObj:
                item.enabled = bool(armatureObj["BatchExport_enabled"])
            if "BatchExport_path" in armatureObj:
                item.path = armatureObj["BatchExport_path"]
            if item.path == "":
                if bpy.context.scene.re_mdf_toolpanel.modDirectory != "":
                    try:
                        split = splitNativesPath(
                            bpy.context.scene.re_mdf_toolpanel.modDirectory
                        )
                        if split is not None:
                            assetPath = armatureObj.get("~ASSETPATH", None)
                            if assetPath is not None:
                                item.path = determineExportPath(
                                    split[0],
                                    item.exportType,
                                    assetPath.replace("/", os.sep),
                                    bpy.context.scene,
                                )
                    except Exception as err:
                        print(
                            f"Batch Export: Cannot auto determine path for {item.name}: {str(err)}"
                        )
        if self.skipPrompt:
            return self.execute(context)
        else:
            # Move cursor to center so extract window is at the center of the window
            context.window.cursor_warp(centerX, centerY)

            return context.window_manager.invoke_props_dialog(
                self, width=EXPORTER_WINDOW_SIZE, confirm_text="Batch Export Files"
            )

    def draw(self, context):
        layout = self.layout
        rowCount = 13
        uifontscale = 9 * context.preferences.view.ui_scale
        row = layout.row().separator()
        split = layout.split(
            factor=SPLIT_FACTOR
        )  # Indent list slightly to make it more clear it's a part of a sub panel
        col1 = split.column()
        split2 = col1.split()
        col1sub1 = split2.column()
        col1sub1.alignment = "LEFT"
        col1sub1.label(
            text=f"Files ({sum(1 for item in self.itemList_items if (not item.hasChild and item.enabled))} selected)"
        )
        col1sub2 = col1.column()
        row = split2.row()
        row.alignment = "RIGHT"
        row.prop(self, "checkAllItems", icon="CHECKMARK", icon_only=True)
        row.prop(self, "uncheckAllItems", icon="X", icon_only=True)
        col1.template_list(
            listtype_name="MESH_UL_REExporterList",
            list_id="itemList",
            dataptr=self,
            propname="itemList_items",
            active_dataptr=self,
            active_propname="itemList_index",
            rows=rowCount,
            type="DEFAULT",
        )
        col2 = split.column()
        col2.label(text="Export Settings")
        box = col2.box()
        if self.itemList_index != -1:
            item = self.itemList_items[self.itemList_index]
            if not item.hasChild and item.exportType != "":
                box.label(text=f"Type: {item.exportType}")
                box.label(text="Export Path")

                box.prop(item, "path")
                if item.invalid:
                    row = box.row()
                    row.alert = True
                    row.label(
                        text="Path is empty or missing the file version number on the end. ",
                        icon="ERROR",
                    )
                if item.exportType == "MESH":
                    box.prop(item, "exportAllLODs")
                    box.prop(item, "exportBlendShapes")
                    box.prop(item, "autoSolveRepeatedUVs")
                    box.prop(item, "preserveSharpEdges")
                    box.prop(item, "rotate90")
                    box.prop(item, "useBlenderMaterialName")
                    box.prop(item, "preserveBoneMatrices")
                    box.prop(item, "exportBoundingBoxes")
            else:
                box.label(
                    text=f"Select a file from the list to configure export settings."
                )


class WM_OT_SolveRepeatedUVs(Operator):
    bl_label = "Solve Repeated UVs"
    bl_idname = "re_mesh_cm.solve_repeated_uvs"
    bl_description = "Splits connected UV islands"

    def execute(self, context):

        if context.selected_objects != []:
            selection = context.selected_objects
        else:
            selection = bpy.context.scene.objects

        solveRepeatedUVs(selection)

        if context.selected_objects == []:
            self.report({"INFO"}, "Solved repeated UVs on all objects.")
        else:
            self.report({"INFO"}, "Solved repeated UVs on selected objects.")
        return {"FINISHED"}


class WM_OT_QuickBatchExport(Operator):
    bl_label = "Quick Batch Export"
    bl_idname = "re_mesh_cm.quick_batch_export"
    bl_description = "Single click batch export. Works the same as RE Batch Export but there is no prompt to configure settings.\nThe previous settings of RE Batch Export are used."

    def execute(self, context):
        bpy.ops.re_mesh_cm.batch_exporter()
        return {"FINISHED"}


def _findStreamingCompanion(filepath):
    # Mirror of readREMesh: streaming file lives at the parallel natives\STM\streaming\... path,
    # or a sibling "streaming" folder for loose files.
    paths = splitNativesPath(filepath)
    if paths is not None:
        candidate = os.path.join(paths[0], "streaming", paths[1])
        if os.path.isfile(candidate):
            return candidate
    folder, name = os.path.split(filepath)
    candidate = os.path.join(folder, "streaming", name)
    if os.path.isfile(candidate):
        return candidate
    return None


def dumpMeshStructure(filepath):
    # Debug: parse a MH Wilds .mesh (base + streaming companion) and print its full structure:
    # header offsets, streamingInfo, per-streaming-entry buffer sizes + blend-delta tail, and the
    # blend shape structs. Pure struct parsing (Wilds / >= ONI2 header layout).
    P = print
    P("=" * 70)
    P(f"[DUMP] {filepath}")
    try:
        d = open(filepath, "rb").read()
    except Exception as err:
        P(f"[DUMP] failed to open: {err}")
        return
    if len(d) < 16 or struct.unpack_from("<I", d, 0)[0] != 1213416781:
        P("[DUMP] not a .mesh file (bad magic)")
        return

    def u8(o):
        return d[o]

    def u16(o):
        return struct.unpack_from("<H", d, o)[0]

    def s16(o):
        return struct.unpack_from("<h", d, o)[0]

    def u32(o):
        return struct.unpack_from("<I", d, o)[0]

    def u64(o):
        return struct.unpack_from("<Q", d, o)[0]

    def f32(o):
        return struct.unpack_from("<f", d, o)[0]

    def pad16(x):
        return x + (-x % 16)

    version = u32(4)
    P(f"[DUMP] version={version} baseFileSize(decl/actual)={u32(8)}/{len(d)} nameCount={s16(20)} contentFlag={bin(u16(22))}")
    if version < 240704828:
        P("[DUMP] Pre-Wilds header layout not supported by this debug parser; aborting.")
        return

    # File header offsets (Wilds / >= ONI2 branch)
    flds = [
        "verticesOffset", "meshGroupOffset", "shadowMeshGroupOffset",
        "occlusionMeshGroupOffset", "normalRecalcOffset", "blendShapesOffset",
        "meshOffset", "sf6unkn1", "floatsOffset", "aabbOffset", "skeletonOffset",
        "materialNameRemapOffset", "boneNameRemapOffset", "blendShapeNameOffset",
        "nameOffsetsOffset", "streamingInfoOffset", "sf6unkn4",
    ]
    H = {n: u64(40 + i * 8) for i, n in enumerate(flds)}
    for n in flds:
        if H[n]:
            P(f"[DUMP]   {n} = {H[n]}")

    strmPath = _findStreamingCompanion(filepath)
    strmSize = os.path.getsize(strmPath) if strmPath else None
    P(f"[DUMP] streaming companion: {strmPath} (size={strmSize})")

    # Streaming info
    entryCount = 0
    streamInfo = []
    if H["streamingInfoOffset"]:
        sio = H["streamingInfoOffset"]
        entryCount = u32(sio)
        entryOff = u64(sio + 8)
        P(f"[DUMP] STREAMING INFO: entryCount={entryCount}")
        for i in range(entryCount):
            bs = u32(entryOff + i * 8)
            bl = u32(entryOff + i * 8 + 4)
            streamInfo.append((bs, bl))
            P(f"[DUMP]   streamInfo[{i}] bufferStart={bs} bufferLength={bl}")

    # Mesh buffer header (SF6+)
    mo = H["meshOffset"]
    if mo:
        vbo = u64(mo + 8)
        totalBufferSize = u32(mo + 24)
        vertexBufferSize = u32(mo + 28)
        mainVEC = u16(mo + 32)
        VEC = u16(mo + 34)
        streamingVEO = u64(mo + 64)
        P(f"[DUMP] MESH BUFFER HEADER: vertexBufferSize(base inline)={vertexBufferSize} totalBufferSize={totalBufferSize} mainVEC={mainVEC} VEC={VEC} streamingVertexElementOffset={streamingVEO}")
        P(f"[DUMP]   meshBufferHeader rawHeader(u32x20)={[u32(mo + k * 4) for k in range(20)]}")
        # Base vertex element declarations (at the header's vertexElementOffset = first u64).
        baseVEO = u64(mo)
        baseElems = [(u16(baseVEO + j * 8), u16(baseVEO + j * 8 + 2), u32(baseVEO + j * 8 + 4)) for j in range(mainVEC)]
        P(f"[DUMP]   base vertexElements (typing,stride,offset)={baseElems}")

        # Streaming buffer header entries (at meshOffset + 80), 64 bytes each
        eo = mo + 80
        elemBlock = pad16(8 * mainVEC)
        for i in range(entryCount):
            b = eo + i * 64
            tot = u32(b + 8)
            vbl = u32(b + 12)
            unpad = u32(b + 20)
            # Parse this entry's vertex elements to find where the blend-delta tail begins.
            veBase = streamingVEO + i * elemBlock
            elems = []
            for j in range(mainVEC):
                eb = veBase + j * 8
                elems.append((u16(eb), u16(eb + 2), u32(eb + 4)))  # typing, stride, posStartOffset
            vertCount = 0
            endOfElements = 0
            if len(elems) >= 2 and elems[0][1]:
                vertCount = (elems[1][2] - elems[0][2]) // elems[0][1]
                last = elems[-1]
                endOfElements = last[2] + vertCount * last[1]
            blendTail = vbl - endOfElements
            P(f"[DUMP]   entry[{i}] totalBufferSize={tot} vertexBufferLength={vbl} unpaddedBufferSize={unpad} vertCount={vertCount} endOfElements={endOfElements} BLEND_TAIL={blendTail} faces={tot - vbl}")
            raw = [u32(b + k * 4) for k in range(16)]
            P(f"[DUMP]     rawHeader(u32x16)={raw}")
            P(f"[DUMP]     vertexElements (typing,stride,offset)={elems}")

    # LOD / mesh-group structure: which submesh reads from which vertex buffer (vbi) and where.
    mgo = H["meshGroupOffset"]
    if mgo:
        lodGroupCount = u8(mgo)
        materialCount = u8(mgo + 1)
        totalMeshCount = u16(mgo + 4)
        lodOffListStart = mgo + 8 + 16 + 32 + 8  # after counts + sphere(16) + bbox(32) + offsetOffset(8)
        lodOffs = [u64(lodOffListStart + i * 8) for i in range(lodGroupCount)]
        P(f"[DUMP] LOD STRUCTURE: lodGroupCount={lodGroupCount} materialCount={materialCount} totalMeshCount={totalMeshCount}")
        for li, lo in enumerate(lodOffs):
            mgCount = u8(lo)
            distance = f32(lo + 4)
            mgOffs = [u64(lo + 16 + i * 8) for i in range(mgCount)]
            P(f"[DUMP]   LOD[{li}] meshGroupCount={mgCount} distance={round(distance, 4)}")
            for mgoff in mgOffs:
                visconID = u8(mgoff)
                meshCount = u8(mgoff + 1)
                for si in range(meshCount):
                    sb = mgoff + 16 + si * 32
                    P(f"[DUMP]     grp{visconID} sub{si}: mat={u8(sb)} vbi={u8(sb + 2)} vertStart={u32(sb + 16)} faceStart={u32(sb + 12)} faceCount={u32(sb + 8)} streamingOffsetBytes={u32(sb + 20)}")

    # Blend shape structs
    bso = H["blendShapesOffset"]
    if bso:
        count = u64(bso)
        # version >= ONI2: zero, mainOffset, hash
        listStart = bso + 32
        offs = [u64(listStart + i * 8) for i in range(count)]
        P(f"[DUMP] BLEND SHAPE HEADER: count(LODs)={count}")
        for li, off in enumerate(offs):
            targetCount = u16(off)
            typing = u16(off + 2)
            unknFlag = u32(off + 4)
            dataOff = u64(off + 16)
            aabbOff = u64(off + 24)
            blendSOff = u64(off + 32)
            blendSSOff = u64(off + 40)
            P(f"[DUMP]   BlendShapeData[{li}] targetCount={targetCount} typing={typing} unknFlag={unknFlag} blendSOff={blendSOff} blendSSOff={blendSSOff}")
            totalShapes = 0
            for ti in range(targetCount):
                t = dataOff + ti * 16
                ssIdx = u16(t)
                bsNum = u16(t + 2)
                totalShapes += bsNum
                subCnt = u8(t + 6)
                subOff = u64(t + 8)
                subs = []
                for j in range(subCnt):
                    so = subOff + j * 16
                    subs.append((u32(so), u32(so + 4), u32(so + 8)))  # startIndex, vertOffset, vertCount
                a = aabbOff + ti * 32
                aabbMax = (round(f32(a + 16), 5), round(f32(a + 20), 5), round(f32(a + 24), 5))
                # Resolve each shape's name: blendShapeNameOffset is a u16 list (per shape occurrence,
                # indexed by global blendSSIndex) into the name-offset table, which holds u64 string offsets.
                names = []
                bsno = H["blendShapeNameOffset"]
                noo = H["nameOffsetsOffset"]
                if bsno and noo:
                    for k in range(bsNum):
                        nameIdx = u16(bsno + (ssIdx + k) * 2)
                        sOff = u64(noo + nameIdx * 8)
                        end = d.index(b"\x00", sOff)
                        names.append(d[sOff:end].decode("utf-8", "replace"))
                P(f"[DUMP]     target[{ti}] blendSSIndex={ssIdx} blendShapeNum={bsNum} subMeshEntries={subs} aabbMax={aabbMax}")
                P(f"[DUMP]       names={names}")
            # blendS (3 ints) immediately followed by blendSSList (one int per shape across all targets).
            if blendSOff:
                blendS = [struct.unpack_from("<i", d, blendSOff + k * 4)[0] for k in range(3)]
                P(f"[DUMP]     blendS={blendS}")
            if blendSSOff:
                ssList = [struct.unpack_from("<i", d, blendSSOff + k * 4)[0] for k in range(totalShapes)]
                P(f"[DUMP]     blendSSList={ssList}")

    # NormalRecalc header (base file) + sample of the per-vertex / per-face index data, which lives in
    # the streaming tail of entry[0] (right after the declared geometry, before the blend deltas).
    nro = H["normalRecalcOffset"]
    if nro:
        nrBlockCount = u32(nro)
        nrDataOffset = u64(nro + 4)
        nrNext = s16(nro + 12)
        nrNull = s16(nro + 14)
        nrVertexOffset = u32(nro + 16)
        nrFaceOffset = u64(nro + 20)
        P(f"[DUMP] NORMAL RECALC HEADER: blockCount={nrBlockCount} dataOffset={nrDataOffset} nextOffset={nrNext} null={nrNull} vertexOffset={nrVertexOffset} faceOffset={nrFaceOffset}")
        try:
            cbytes = open(strmPath, "rb").read() if strmPath else None
        except Exception:
            cbytes = None
        if cbytes is not None and entryCount and mo:
            # entry[0] geometry ends at endOfElements within the companion buffer (bufferStart=0).
            b0 = eo  # streamingBufferHeaderList entry[0]
            vbl0 = u32(b0 + 12)
            veBase0 = streamingVEO
            e0 = [(u16(veBase0 + j * 8), u16(veBase0 + j * 8 + 2), u32(veBase0 + j * 8 + 4)) for j in range(mainVEC)]
            vc0 = (e0[1][2] - e0[0][2]) // e0[0][1] if e0[0][1] else 0
            eoe0 = e0[-1][2] + vc0 * e0[-1][1]
            base0 = streamInfo[0][0]  # bufferStart in companion
            def nrEntry(o):
                return (struct.unpack_from("<H", cbytes, o)[0], cbytes[o + 2], cbytes[o + 3])
            vStart = base0 + eoe0
            P(f"[DUMP]   entry[0] geom ends at companion offset {eoe0}; vertCount={vc0}; first vertex-data entries (index,left,right):")
            P("[DUMP]     " + " ".join(str(nrEntry(vStart + k * 4)) for k in range(min(12, vc0))))
            # Face data begins after vertexCount*4 (padded to 16).
            fStart = vStart + pad16(vc0 * 4)
            P(f"[DUMP]   face-data begins at companion offset {fStart - base0}; first entries (index,left,right):")
            P("[DUMP]     " + " ".join(str(nrEntry(fStart + k * 4)) for k in range(12)))

    # Blend delta SAMPLE: decode the actual packed deltas of entry[0]'s first target, to check whether
    # the original file's deltas are real or zero (and whether our 11/10/11 decode matches). deltaStart
    # is streamingBufferHeader word9 (u32 at meshOffset+80+36); deltas live in the companion at it.
    if bso and mo and entryCount and strmPath:
        try:
            cb = open(strmPath, "rb").read()
        except Exception:
            cb = None
        if cb is not None:
            block0 = u64(bso + 32)
            tc0 = u16(block0)
            dataOff0 = u64(block0 + 16)
            aabbOff0 = u64(block0 + 24)
            bsnoB = H["blendShapeNameOffset"]
            nooB = H["nameOffsetsOffset"]
            deltaStart = u32(eo + 36)  # entry[0] word9
            dBase = streamInfo[0][0] + deltaStart
            SENTINEL = 0x7FEFFBFF
            P(f"[DUMP] BLEND DELTA SAMPLE (block0, deltaStart={deltaStart}): per-shape nonzero counts over a sample")
            # Walk every target/shape. A shape's deltas start at deltaStart + (target's first-subEntry
            # vertOffset + shapeIndex*regionVerts) packed u32; report how many sampled verts are real
            # (not the 0x7FEFFBFF zero-sentinel) so we can see which shapes actually carry deformation.
            for ti in range(tc0):
                t = dataOff0 + ti * 16
                ssIdx = u16(t)
                bsNum = u16(t + 2)
                subCnt = u8(t + 6)
                subOff = u64(t + 8)
                regionVerts = sum(u32(subOff + j * 16 + 8) for j in range(subCnt))
                baseVertOff = u32(subOff + 4)  # first subEntry vertOffset = target's delta base
                ax, ay, az = f32(aabbOff0 + ti * 32 + 16), f32(aabbOff0 + ti * 32 + 20), f32(aabbOff0 + ti * 32 + 24)
                for s in range(bsNum):
                    shapeOff = dBase + (baseVertOff + s * regionVerts) * 4
                    sampleN = min(regionVerts, 4000)
                    raws = [struct.unpack_from("<I", cb, shapeOff + k * 4)[0] for k in range(sampleN)]
                    nonSentinel = sum(1 for v in raws if v != SENTINEL)
                    maxMag = max(
                        ax * abs(2 * (v & 0x7FF) / 2047 - 1)
                        + ay * abs(2 * ((v >> 11) & 0x3FF) / 1023 - 1)
                        + az * abs(2 * ((v >> 21) & 0x7FF) / 2047 - 1)
                        for v in raws
                    )
                    nm = ""
                    if bsnoB and nooB:
                        nameIdx = u16(bsnoB + (ssIdx + s) * 2)
                        so = u64(nooB + nameIdx * 8)
                        nm = d[so : d.index(b"\x00", so)].decode("utf-8", "replace")
                    P(f"[DUMP]   target{ti} shape{s} '{nm}': non-sentinel={nonSentinel}/{sampleN} maxAbsSum={round(maxMag, 5)}")
    P("=" * 70)


# Debug: when nonzero, the patch also shifts every LOD0 vertex position in the streaming file up by
# this many units (Y). A diagnostic to tell whether the game actually reads the MOD's streaming file:
# if the armor visibly moves in-game, the streaming is being read (so a blend that doesn't show is a
# cache/other issue); if it doesn't move, the game is ignoring the mod's streaming (packaging problem).
_DEBUG_BOTCH_STREAM_GEOMETRY = 0.0


def patchStreamingBlendDeltas(obj, meshPath):
    # Step 1 of the blend workflow: keep the original base file AND streaming file intact, and overwrite
    # ONLY the LOD0 blend-delta slice in the streaming companion with the (edited) shape-key deltas,
    # re-encoded in the original's exact target/subEntry layout + AABBs (captured at import as the
    # object's re_wilds_blend_meta). This sidesteps regenerating the streamed structure entirely.
    import json
    import numpy as np

    metaRaw = obj.get("re_wilds_blend_meta")
    if not metaRaw:
        return False, "Active object has no captured Wilds blend metadata (re-import the original first)."
    meta = json.loads(metaRaw)
    sk = obj.data.shape_keys
    if sk is None or len(sk.key_blocks) < 2:
        return False, "Active object has no shape keys."

    d = bytearray(open(meshPath, "rb").read())  # mutable: we patch the per-target AABBs in place
    if len(d) < 16 or struct.unpack_from("<I", d, 0)[0] != 1213416781:
        return False, "Selected file is not a .mesh."

    def u32(o):
        return struct.unpack_from("<I", d, o)[0]

    def u64(o):
        return struct.unpack_from("<Q", d, o)[0]

    meshOffset = u64(40 + 6 * 8)
    sio = u64(40 + 15 * 8)
    blendShapesOffset = u64(40 + 5 * 8)
    if not meshOffset or not sio or not blendShapesOffset:
        return False, "Selected mesh has no streaming info / blend block (not a streamed blend mesh)."
    entryOff = u64(sio + 8)
    bufferStart0 = u32(entryOff)
    word9 = u32(meshOffset + 80 + 36)  # entry[0] blend delta start, relative to its buffer
    deltaAbs = bufferStart0 + word9  # absolute offset of LOD0 deltas in the companion
    block0 = u64(blendShapesOffset + 32)
    aabbOffset = u64(block0 + 24)  # per-target AABB array in the base file's blend block

    strmPath = _findStreamingCompanion(meshPath)
    if strmPath is None:
        return False, "Streaming companion not found next to the .mesh (copy the original streaming file in)."
    companion = bytearray(open(strmPath, "rb").read())

    basis = sk.key_blocks[0]
    nVerts = len(basis.data)
    basisCo = np.empty(nVerts * 3, dtype=np.float32)
    basis.data.foreach_get("co", basisCo)
    basisCo = basisCo.reshape(-1, 3)
    blendRot = np.array(obj.matrix_world.to_3x3(), dtype=np.float32)

    chunks = []
    missing = []
    for ti, t in enumerate(meta["targets"]):
        # Game-space deltas for every shape in this target.
        shapeDeltas = []
        for name in t["names"]:
            kb = sk.key_blocks.get(name)
            if kb is None:
                missing.append(name)
                shapeDeltas.append(np.zeros((nVerts, 3)))
            else:
                skCo = np.empty(nVerts * 3, dtype=np.float32)
                kb.data.foreach_get("co", skCo)
                shapeDeltas.append((skCo.reshape(-1, 3) - basisCo) @ blendRot.T)
        # Recompute a symmetric AABB that actually covers the (edited) deltas across this target's
        # region, so large edits aren't clamped to the original range. Patch it into the base file.
        maxAbs = np.full(3, 1e-6)
        for gd in shapeDeltas:
            for sStart, _sVOff, sCnt in t["subEntries"]:
                seg = gd[sStart : sStart + sCnt]
                if len(seg):
                    maxAbs = np.maximum(maxAbs, np.max(np.abs(seg), axis=0))
        ao = aabbOffset + ti * 32
        struct.pack_into("<4f", d, ao + 0, -maxAbs[0], -maxAbs[1], -maxAbs[2], 0.0)
        struct.pack_into("<4f", d, ao + 16, maxAbs[0], maxAbs[1], maxAbs[2], 0.0)
        mn = -maxAbs
        rng = 2.0 * maxAbs
        rng[rng == 0] = 1.0
        print(
            f"[BSPATCH]   target{ti} ({len(t['names'])} shape(s): {t['names']}): "
            f"newAABBmax={[round(float(v),5) for v in maxAbs]}"
        )
        for gd in shapeDeltas:
            for sStart, _sVOff, sCnt in t["subEntries"]:
                seg = np.asarray(gd[sStart : sStart + sCnt], dtype=np.float64)
                if len(seg) < sCnt:
                    seg = np.vstack([seg, np.zeros((sCnt - len(seg), 3))])
                norm = (seg - mn) / rng
                xi = np.clip(np.round(norm[:, 0] * 2047), 0, 2047).astype(np.uint32)
                yi = np.clip(np.round(norm[:, 1] * 1023), 0, 1023).astype(np.uint32)
                zi = np.clip(np.round(norm[:, 2] * 2047), 0, 2047).astype(np.uint32)
                chunks.append((xi | (yi << 11) | (zi << 21)).astype("<u4"))

    blendDeltaBytes = np.concatenate(chunks).astype("<u4").tobytes() if chunks else b""
    if deltaAbs + len(blendDeltaBytes) > len(companion):
        return False, (
            f"Delta region overflows the companion ({deltaAbs}+{len(blendDeltaBytes)} > {len(companion)}); "
            "geometry/shape mismatch with the original."
        )
    companion[deltaAbs : deltaAbs + len(blendDeltaBytes)] = blendDeltaBytes

    if _DEBUG_BOTCH_STREAM_GEOMETRY:
        # Diagnostic: shift every LOD0 vertex position (Y) in the streaming file. entry[0] vertex
        # elements live at the base's streamingVertexElementOffset; positions are the first element.
        sveo = u64(meshOffset + 64)
        e0Stride = struct.unpack_from("<H", d, sveo + 2)[0]
        e0Off = struct.unpack_from("<I", d, sveo + 4)[0]
        e1Off = struct.unpack_from("<I", d, sveo + 8 + 4)[0]
        vc0 = (e1Off - e0Off) // e0Stride if e0Stride else 0
        posBase = bufferStart0 + e0Off
        for vi in range(vc0):
            po = posBase + vi * e0Stride
            y = struct.unpack_from("<f", companion, po + 4)[0]
            struct.pack_into("<f", companion, po + 4, y + _DEBUG_BOTCH_STREAM_GEOMETRY)
        print(f"[BSPATCH]   DEBUG botched {vc0} LOD0 positions by +{_DEBUG_BOTCH_STREAM_GEOMETRY} in Y")

    open(strmPath, "wb").write(companion)
    open(meshPath, "wb").write(d)  # base file: only the per-target AABB floats changed
    msg = (
        f"Patched {len(blendDeltaBytes)} bytes of LOD0 deltas into {os.path.basename(strmPath)} (offset "
        f"{deltaAbs}) and recomputed {len(meta['targets'])} target AABBs in the base file."
    )
    if missing:
        msg += f" Missing shape keys (left as zero): {missing}"
    print("[BSPATCH] " + msg)
    return True, msg


def botchStreamingGeometryOnly(meshPath, shiftY):
    # Incremental streaming experiment (base file left COMPLETELY untouched). Reads the base only to
    # locate the LOD0 streaming entry's vertex positions, then shifts every LOD0 vertex up by shiftY
    # (meters) in the STREAMING COMPANION and rewrites ONLY that file. Pair with the VANILLA base (which
    # genuinely references the streaming entries) and PAK both: if the armor visibly moves in-game, the
    # engine IS reading the mod's streaming companion — the earlier "streaming never loads" result was
    # confounded by shipping an inline re-export base (streamEntryCount=0) that never requested streaming.
    d = open(meshPath, "rb").read()  # READ ONLY: the base file is never written back
    if len(d) < 16 or struct.unpack_from("<I", d, 0)[0] != 1213416781:
        return False, "Selected file is not a .mesh."

    def u16(o):
        return struct.unpack_from("<H", d, o)[0]

    def u32(o):
        return struct.unpack_from("<I", d, o)[0]

    def u64(o):
        return struct.unpack_from("<Q", d, o)[0]

    meshOffset = u64(40 + 6 * 8)
    sio = u64(40 + 15 * 8)
    if not meshOffset or not sio:
        return False, "Selected mesh has no streaming info (not a streamed mesh — nothing to botch)."
    entryOff = u64(sio + 8)
    bufferStart0 = u32(entryOff)

    strmPath = _findStreamingCompanion(meshPath)
    if strmPath is None:
        return False, "Streaming companion not found next to the .mesh (copy the original streaming file in)."
    companion = bytearray(open(strmPath, "rb").read())

    # entry[0] vertex elements: stride + offset of the first (position) element vs. the second element.
    sveo = u64(meshOffset + 64)
    e0Stride = u16(sveo + 2)
    e0Off = u32(sveo + 4)
    e1Off = u32(sveo + 8 + 4)
    vc0 = (e1Off - e0Off) // e0Stride if e0Stride else 0
    if vc0 <= 0:
        return False, f"Could not determine LOD0 vertex count (stride={e0Stride}, e0Off={e0Off}, e1Off={e1Off})."
    posBase = bufferStart0 + e0Off
    if posBase + (vc0 - 1) * e0Stride + 8 > len(companion):
        return False, (
            f"Position region overflows the companion (posBase={posBase}, vc0={vc0}, stride={e0Stride}, "
            f"companion={len(companion)}); base/streaming mismatch."
        )
    for vi in range(vc0):
        po = posBase + vi * e0Stride
        y = struct.unpack_from("<f", companion, po + 4)[0]
        struct.pack_into("<f", companion, po + 4, y + shiftY)

    open(strmPath, "wb").write(companion)  # ONLY the streaming companion is written
    msg = (
        f"Shifted {vc0} LOD0 vertices by +{shiftY} in Y in {os.path.basename(strmPath)} "
        f"(posBase={posBase}, stride={e0Stride}). Base file left untouched. PAK base + this streaming "
        f"file and check in-game whether the armor moves."
    )
    print("[STRMBOTCH] " + msg)
    return True, msg


class WM_OT_PatchWildsBlendDeltas(Operator):
    bl_label = "Patch Wilds Blend Deltas Into Streaming (Debug)"
    bl_idname = "re_mesh_cm.patch_wilds_blend_deltas"
    bl_description = (
        "Overwrite only the LOD0 blend-delta slice in a streamed mesh's streaming companion with the "
        "active object's (edited) shape-key deltas, keeping the base file and the rest of the streaming "
        "file intact. Select the mod-folder .mesh whose adjacent streaming companion should be patched"
    )

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.mesh*", options={"HIDDEN"})

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != "MESH":
            self.report({"ERROR"}, "Make the imported mesh object (with shape keys) the active object first")
            return {"CANCELLED"}
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({"ERROR"}, "No valid .mesh selected")
            return {"CANCELLED"}
        ok, msg = patchStreamingBlendDeltas(obj, self.filepath)
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class WM_OT_BotchStreamingGeometry(Operator):
    bl_label = "Botch Streaming Geometry (base untouched, Debug)"
    bl_idname = "re_mesh_cm.botch_streaming_geometry"
    bl_description = (
        "Streaming-only test: shift every LOD0 vertex up by 'Shift Y' meters in the streaming companion "
        "while leaving the base .mesh COMPLETELY untouched. Select the VANILLA base .mesh (with its "
        "original streaming companion alongside), PAK both, and check in-game: if the armor moves, the "
        "engine reads the mod's streaming file (blend-via-streaming is viable); if not, streamed data "
        "truly can't be overridden by a mod"
    )

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.mesh*", options={"HIDDEN"})
    shiftY: FloatProperty(
        name="Shift Y",
        description="How far (meters) to shift every LOD0 vertex upward in the streaming file",
        default=0.5,
    )

    def execute(self, context):
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({"ERROR"}, "No valid .mesh selected")
            return {"CANCELLED"}
        ok, msg = botchStreamingGeometryOnly(self.filepath, self.shiftY)
        self.report({"INFO"} if ok else {"ERROR"}, msg)
        return {"FINISHED"} if ok else {"CANCELLED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}


class WM_OT_DumpMeshStructure(Operator):
    bl_label = "Dump RE Mesh Structure (Debug)"
    bl_idname = "re_mesh_cm.dump_mesh_structure"
    bl_description = (
        "Parse a .mesh file (base + streaming companion) and print its full structure to the "
        "system console. Used to compare original vs exported meshes while developing streaming export"
    )

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.mesh*", options={"HIDDEN"})

    def execute(self, context):
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({"ERROR"}, "No valid .mesh file selected")
            return {"CANCELLED"}
        dumpMeshStructure(self.filepath)
        self.report({"INFO"}, "Dumped mesh structure to system console (Window > Toggle System Console)")
        return {"FINISHED"}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}
