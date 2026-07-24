import argparse
import importlib.util
import json
import sys
import traceback
from pathlib import Path

def _load_packaging_module():
    module_path = Path(__file__).resolve().parents[2] / "library_packaging.py"
    specification = importlib.util.spec_from_file_location("reme_library_packaging", module_path)

    if (specification is None or specification.loader is None):
        raise RuntimeError(f"Could not load packaging module: {module_path}")

    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module

def main(arguments=None):
    parser = argparse.ArgumentParser(description="Package an REME Asset Library")
    parser.add_argument("--library-directory", required=True)
    parser.add_argument("--game-name", required=True)
    parser.add_argument("--output-directory", required=True)
    parser.add_argument("--display-name", default="")
    parser.add_argument("--release-description", default="")
    parser.add_argument("--drive-file-id", default="")
    options = parser.parse_args(arguments)

    packaging = _load_packaging_module()
    result = packaging.build_library_package(options.library_directory, options.game_name, options.output_directory, display_name=options.display_name, release_description=options.release_description, drive_file_id=options.drive_file_id)

    print(f"Created Asset Library package: {result['package_path']}")
    print(f"Created directory metadata: {result['metadata_path']}")
    print(json.dumps(result["directory_entry"], indent=4, sort_keys=False))
    return 0

if __name__ == "__main__":
    try:
        separator_index = sys.argv.index("--")
        script_arguments = sys.argv[separator_index + 1:]
    except ValueError:
        script_arguments = sys.argv[1:]

    try:
        raise SystemExit(main(script_arguments))
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        raise SystemExit(1)