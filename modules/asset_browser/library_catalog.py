import csv
from pathlib import Path

CATALOG_HEADER = (
    "File Path",
    "Display Name",
    "Category (Forward Slash Separated)",
    "Tags (Comma Separated)",
    "Platform Extension",
    "Language Extension"
)

def _asset_key(row):
    return (
        row[0].strip().replace("\\", "/").casefold(),
        row[4].strip().casefold(),
        row[5].strip().casefold()
    )

def _asset_reference(row):
    reference = row[0].strip().replace("\\", "/")

    if row[4].strip():
        reference += f".{row[4].strip()}"

    if row[5].strip():
        reference += f".{row[5].strip()}"

    return reference

def _index_rows(rows, source_name):
    indexed_rows = {}

    for row_number, row in enumerate(rows, start=2):
        key = _asset_key(row)

        if key in indexed_rows:
            raise ValueError(f"{source_name} contains duplicate asset {_asset_reference(row)} at row {row_number}")

        indexed_rows[key] = row

    return indexed_rows

def read_catalog(catalog_path):
    catalog_path = Path(catalog_path)
    rows = []

    with catalog_path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, delimiter="\t", quotechar='"')

        try:
            header = tuple(next(reader))
        except StopIteration:
            raise ValueError(f"{catalog_path.name} is empty")

        if header != CATALOG_HEADER:
            raise ValueError(f"{catalog_path.name} has an unsupported catalog header")

        for row_number, row in enumerate(reader, start=2):
            if not row or not any(column.strip() for column in row):
                continue

            if len(row) != len(CATALOG_HEADER):
                raise ValueError(f"{catalog_path.name} row {row_number} has {len(row)} columns, expected {len(CATALOG_HEADER)}")

            if not row[0].strip():
                raise ValueError(f"{catalog_path.name} row {row_number} has no asset path")

            rows.append(tuple(row))

    _index_rows(rows, catalog_path.name)
    return rows

def write_catalog(catalog_path, rows):
    catalog_path = Path(catalog_path)

    with catalog_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", quotechar='"', lineterminator="\n")
        writer.writerow(CATALOG_HEADER)
        writer.writerows(rows)

def merge_catalog_rows(existing_rows, generated_rows):
    existing_by_key = _index_rows(existing_rows, "Existing catalog")
    generated_by_key = _index_rows(generated_rows, "Generated catalog")

    merged_rows = []
    added_assets = []
    preserved_count = 0

    for generated_row in generated_rows:
        key = _asset_key(generated_row)
        existing_row = existing_by_key.get(key)

        if existing_row is None:
            merged_rows.append(generated_row)
            added_assets.append(_asset_reference(generated_row))
            continue

        merged_rows.append((
            generated_row[0],
            existing_row[1],
            existing_row[2],
            existing_row[3],
            generated_row[4],
            generated_row[5]
        ))
        preserved_count += 1

    removed_assets = [
        _asset_reference(existing_row) for key, existing_row in existing_by_key.items() if key not in generated_by_key
    ]

    report = {
        "existing_count": len(existing_rows),
        "generated_count": len(generated_rows),
        "merged_count": len(merged_rows),
        "preserved_count": preserved_count,
        "added_assets": added_assets,
        "removed_assets": removed_assets
    }

    return merged_rows, report

def merge_catalog_files(existing_path, generated_path, output_path):
    existing_rows = read_catalog(existing_path)
    generated_rows = read_catalog(generated_path)
    merged_rows, report = merge_catalog_rows(existing_rows, generated_rows)
    write_catalog(output_path, merged_rows)
    return report

def compare_file_versions(existing_game_info, generated_game_info):
    existing_versions = existing_game_info.get("fileVersionDict", {})
    generated_versions = generated_game_info.get("fileVersionDict", {})

    if not isinstance(existing_versions, dict):
        raise ValueError("Existing GameInfo has an invalid fileVersionDict")

    if not isinstance(generated_versions, dict):
        raise ValueError("Generated GameInfo has an invalid fileVersionDict")

    version_changes = {}

    for version_name in sorted(set(existing_versions) | set(generated_versions)):
        old_version = existing_versions.get(version_name)
        new_version = generated_versions.get(version_name)

        if old_version != new_version:
            version_changes[version_name] = {
                "old": old_version,
                "new": new_version
            }

    return version_changes