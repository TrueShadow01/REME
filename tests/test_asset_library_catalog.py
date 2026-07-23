import importlib.util
import tempfile
import unittest
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    REPOSITORY_ROOT
    / "modules"
    / "asset_browser"
    / "library_catalog.py"
)

MODULE_SPEC = importlib.util.spec_from_file_location("reme_asset_library_catalog", MODULE_PATH)
library_catalog = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(library_catalog)

def catalog_row(path, display_name, category="", tags="", platform="", language=""):
    return(path, display_name, category, tags, platform,  language)

class CatalogMergeTests(unittest.TestCase):
    def test_preserves_curated_metadata_and_reports_changes(self):
        existing_rows = [
            catalog_row(
                "characters/hero.mesh",
                "Hero",
                "Characters/Hero",
                "playable,hero"
            ),
            catalog_row(
                "characters/removed.mesh",
                "Removed Character",
                "Characters",
                "removed"
            )
        ]
        generated_rows = [
            catalog_row(
                "characters/hero.mesh",
                "hero.mesh",
                "",
                "hero.mesh"
            ),
            catalog_row(
                "characters/new.mesh",
                "new.mesh",
                "",
                "new.mesh"
            )
        ]

        merged_rows, report = library_catalog.merge_catalog_rows(existing_rows, generated_rows)

        self.assertEqual(merged_rows[0], catalog_row(
            "characters/hero.mesh",
            "Hero",
            "Characters/Hero",
            "playable,hero"
        ))
        self.assertEqual(merged_rows[1], generated_rows[1])
        self.assertEqual(report["preserved_count"], 1)
        self.assertEqual(report["added_assets"], ["characters/new.mesh"])
        self.assertEqual(report["removed_assets"], ["characters/removed.mesh"])

    def test_platform_and_language_variants_remain_separate(self):
        existing_rows = [
            catalog_row(
                "characters/body.mesh",
                "Steam English",
                platform="stm",
                language="en"
            ),
            catalog_row(
                "characters/body.mesh",
                "GamePass English",
                platform="msg",
                language="en"
            )
        ]
        generated_rows = [
            catalog_row(
                "characters/body.mesh",
                "body.mesh",
                platform="msg",
                language="en"
            ),
            catalog_row(
                "characters/body.mesh",
                "body.mesh",
                platform="stm",
                language="en"
            )
        ]

        merged_rows, report = library_catalog.merge_catalog_rows(existing_rows, generated_rows)

        self.assertEqual(merged_rows[0][1], "GamePass English")
        self.assertEqual(merged_rows[1][1], "Steam English")
        self.assertEqual(report["preserved_count"], 2)
        self.assertEqual(report["added_assets"], [])
        self.assertEqual(report["removed_assets"], [])

    def test_duplicate_assets_are_rejected_case_insensitively(self):
        duplicate_rows = [
            catalog_row(
                "Characters\\Body.mesh",
                "Body",
                platform="STM",
                language="EN"
            ),
            catalog_row(
                "characters/body.mesh",
                "Duplicate",
                platform="stm",
                language="en"
            )
        ]

        with self.assertRaisesRegex(ValueError, "duplicate asset"):
            library_catalog.merge_catalog_rows([], duplicate_rows)

    def test_catalog_write_and_read_rount_trip(self):
        rows = [
            catalog_row(
                "characters/hero.mesh",
                "Hero",
                "Characters/Hero",
                "playable,hero"
            )
        ]

        with tempfile.TemporaryDirectory() as temporary_directory:
            catalog_path = (Path(temporary_directory) / "REAssetCatalog_TEST.tsv")
            library_catalog.write_catalog(catalog_path, rows)
            loaded_rows = library_catalog.read_catalog(catalog_path)

        self.assertEqual(loaded_rows, rows)

if __name__ == "__main__":
    unittest.main()