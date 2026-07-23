import json
import re
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from zlib import crc32

import zstandard as zstd

OPTIONAL_LIBRARY_FILES = (
    "MaterialCompendium_{game_name}.json",
    "CRCCompendium_{game_name}.json",
    "PakSizeInfo_{game_name}.json"
)

def get_file_crc(file_path):
    file_path = Path(file_path)
    crc_value = 0

    with file_path.open("rb") as stream:
        while chunk := stream.read(10 * 1024 * 1024):
            crc_value = crc32(chunk, crc_value)

    return crc_value

def _validate_game_name(game_name):
    game_name = str(game_name).strip().upper()

    if not re.fullmatch(r"[A-Z0-9_]+", game_name):
        raise ValueError("Game Name may only contain letters, numbers and underscores")

    return game_name

def _write_json_atomically(file_path, value):
    file_path = Path(file_path)
    temporary_path = None

    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp", delete=False) as stream:
            temporary_path = Path(stream.name)
            json.dump(value, stream, indent=4, sort_keys=False)
            stream.write("\n")

        temporary_path.replace(file_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

def build_library_package(library_directory, game_name, output_directory, display_name="", release_description="", drive_file_id=""):
    library_directory = Path(library_directory)
    output_directory = Path(output_directory)
    game_name = _validate_game_name(game_name)

    catalog_path = library_directory / f"REAssetCatalog_{game_name}.tsv"
    game_info_path = library_directory / f"GameInfo_{game_name}.json"
    blend_path = library_directory / f"REAssetLibrary_{game_name}.blend"
    thumbnail_directory = library_directory / f"REAssetLibrary_{game_name}_thumbnails"

    required_files = (
        catalog_path,
        game_info_path,
        blend_path
    )

    missing_files = [path.name for path in required_files if not path.is_file()]

    if missing_files:
        raise ValueError("Required library files are missing: " + ", ".join(missing_files))

    if not thumbnail_directory.is_dir():
        raise ValueError(f"Thumbnail directory is missing: {thumbnail_directory.name}")

    output_directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
    packed_catalog_data = zstd.ZstdCompressor().compress(catalog_path.read_bytes())
    package_info_data = (
        json.dumps({"timestamp": timestamp}, indent=4, sort_keys=False) + "\n"
    ).encode("utf-8")

    archive_files = [
        (
            game_info_path,
            f"{game_name}/GameInfo_{game_name}.json"
        ),
        (
            catalog_path,
            f"{game_name}/REAssetCatalog_{game_name}.tsv"
        )
    ]

    for file_template in OPTIONAL_LIBRARY_FILES:
        optional_path = library_directory / file_template.format(game_name=game_name)

        if optional_path.is_file():
            archive_files.append((optional_path, f"{game_name}/{optional_path.name}"))

    thumbnail_files = sorted(
        (
            path for path in thumbnail_directory.rglob("*")
            if path.is_file() and path.suffix.casefold() == ".jp2"
        ),
        key=lambda path: path.as_posix().casefold()
    )

    thumbnail_archive_root = f"{game_name}/REAssetLibrary_{game_name}_thumbnails"

    for thumbnail_path in thumbnail_files:
        relative_thumbnail = thumbnail_path.relative_to(thumbnail_directory).as_posix()
        archive_files.append((thumbnail_path, f"{thumbnail_archive_root}/{relative_thumbnail}"))

    uncompressed_size = blend_path.stat().st_size
    uncompressed_size += len(packed_catalog_data)
    uncompressed_size += len(package_info_data)
    uncompressed_size += sum(source_path.stat().st_size for source_path, _archive_name in archive_files)

    package_path = output_directory / f"{game_name}.reassetlib"
    temporary_package_path = None

    try:
        with tempfile.NamedTemporaryFile(dir=output_directory, prefix=f".{game_name}.", suffix=".reassetlib.tmp", delete=False) as temporary_file:
            temporary_package_path = Path(temporary_file.name)

        with zipfile.ZipFile(temporary_package_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for source_path, archive_name in archive_files:
                archive.write(source_path, arcname=archive_name)

            archive.writestr(f"{game_name}/packedAssetCat_{game_name}.zst", packed_catalog_data)
            archive.writestr(f"{game_name}/packageInfo_{game_name}.json", package_info_data)

        temporary_package_path.replace(package_path)
    finally:
        if (temporary_package_path is not None and temporary_package_path.exists()):
            temporary_package_path.unlink()

    directory_entry = {
        "displayName": str(display_name).strip() or game_name,
        "gameName": game_name,
        "releaseDescription": str(release_description).strip(),
        "timestamp": timestamp,
        "CRC": get_file_crc(package_path),
        "compressedSize": package_path.stat().st_size,
        "uncompressedSize": uncompressed_size,
        "URL": str(drive_file_id).strip()
    }

    metadata_path = output_directory / f"REAssetLib_entry_{game_name}.json"
    _write_json_atomically(metadata_path, directory_entry)

    return {
        "package_path": package_path,
        "metadata_path": metadata_path,
        "directory_entry": directory_entry
    }