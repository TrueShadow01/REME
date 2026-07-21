"""
RE Asset Browser integration for REME.

Adapted from NSACloud/RE-Asset-Library
Source commit: 4d04bde69693b2eb613fb0b9625a2dc3282f74d5
"""
import bpy
from .library_manager import CLASSES
from .runtime import (
    register as register_runtime,
    unregister as unregister_runtime,
)

def register():
    for class_entry in CLASSES:
        bpy.utils.register_class(class_entry)
    
    register_runtime()

def unregister():
    unregister_runtime()

    for class_entry in reversed(CLASSES):
        bpy.utils.unregister_class(class_entry)

__all__ = ("register", "unregister")