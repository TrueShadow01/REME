import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import zstandard as zstd

MODULE_PATH = Path(__file__).resolve().parents[1] / "modules" / "asset_browser" / "library_packaging.py"
SPEC = importlib.util.spec_from_file_location("library_packaging", MODULE_PATH)
library_packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(library_packaging)

class LibraryPackagingTests(unittest.TestCase):
    def _create_test_library(self, library_directory):
        game_name = "TEST"
        library_directory.mkdir(parents=True)

        catalog_path = library_directory / "REAssetCatalog_TEST.tsv"
        game_info_path = library_directory / "GameInfo_TEST.json"
        blend_path = library_directory / "REAssetLibrary_TEST.blend"
        thumbnail_directory = library_directory / "REAssetLibrary_TEST_thumbnails"

        catalog_path.write_text(
            "FilePath\tDisplay Name\tCategory "
            "(Forward Slash Separated)\\tTags (Comma Separated)"
            "\tPlatform Extension\tLanguage Extension\n"
            "Product/Model/test.mesh\tTest Mesh\tTests\t"
            "\tstm\t\n",
            encoding="utf-8"
        )
        game_info_path.write_text(
            json.dumps(
                {
                    "GameName": game_name,
                    "GameInfoVersion": 1,
                    "fileTypeWhiteList": ["mesh"],
                    "fileVersionDict": {"mesh": "1"}
                }
            ),
            encoding="utf-8"
        )
        blend_path.write_bytes(b"synthetic blend data")

        thumbnail_directory.mkdir()
        (thumbnail_directory / "preview.jp2").write_bytes(b"synthetic thumbnail")
        (thumbnail_directory / "ignored.png").write_bytes(b"not packaged")
        (library_directory / "MaterialCompendium_TEST.json").write_text("{}", encoding="utf-8")

        game_asset = library_directory / "natives" / "stm" / "test.mesh.1"
        game_asset.parent.mkdir(parents=True)
        game_asset.write_bytes(b"must not be packaged")

        return {
            "catalog": catalog_path,
            "blend": blend_path
        }

    def test_builds_compatible_package_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            library_directory = root / "library"
            output_directory = root / "output"
            paths = self._create_test_library(library_directory)

            result = library_packaging.build_library_package(library_directory, "test", output_directory, display_name="Test Game", release_description="Synthetic test package", drive_file_id="test-drive-file-id")

            package_path = Path(result["package_path"])
            metadata_path = Path(result["metadata_path"])
            directory_entry = result["directory_entry"]

            self.assertTrue(package_path.is_file())
            self.assertTrue(metadata_path.is_file())

            with zipfile.ZipFile(package_path, "r") as archive:
                archive_names = set(archive.namelist())

                expected_names = {
                    "TEST/GameInfo_TEST.json",
                    "TEST/REAssetCatalog_TEST.tsv",
                    "TEST/packedAssetCat_TEST.zst",
                    "TEST/packageInfo_TEST.json",
                    "TEST/MaterialCompendium_TEST.json",
                    (
                        "TEST/REAssetLibrary_TEST_thumbnails/"
                        "preview.jp2"
                    )
                }

                self.assertEqual(archive_names, expected_names)
                self.assertFalse(any(name.endswith(".blend") for name in archive_names))
                self.assertFalse(any("natives/" in name for name in archive_names))

                packed_catalog = archive.read("TEST/packedAssetCat_TEST.zst")
                unpacked_catalog = (
                    zstd.ZstdDecompressor().decompress(packed_catalog)
                )
                self.assertEqual(unpacked_catalog, paths["catalog"].read_bytes())

                package_info = json.loads(archive.read("TEST/packageInfo_TEST.json").decode("utf-8"))
                self.assertEqual(package_info["timestamp"], directory_entry["timestamp"])

                archive_size = sum(entry.file_size for entry in archive.infolist())

            expected_installed_size = paths["blend"].stat().st_size + archive_size

            self.assertEqual(directory_entry["displayName"], "Test Game")
            self.assertEqual(directory_entry["gameName"], "TEST")
            self.assertEqual(directory_entry["releaseDescription"], "Synthetic test package")
            self.assertEqual(directory_entry["URL"], "test-drive-file-id")
            self.assertEqual(directory_entry["compressedSize"], package_path.stat().st_size)
            self.assertEqual(directory_entry["uncompressedSize"], expected_installed_size)
            self.assertEqual(directory_entry["CRC"], library_packaging.get_file_crc(package_path))

            saved_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

            self.assertEqual(saved_metadata, directory_entry)

    def test_rejects_unsafe_game_name_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            output_directory = root / "output"

            with self.assertRaisesRegex(ValueError, "Game Name"):
                library_packaging.build_library_package(root, "../TEST", output_directory)

            self.assertFalse(output_directory.exists())

    def test_reports_missing_required_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)

            with self.assertRaisesRegex(ValueError, "Required library files are missing"):
                library_packaging.build_library_package(root / "library", "TEST", root / "output")


if __name__ == "__main__":
    unittest.main()