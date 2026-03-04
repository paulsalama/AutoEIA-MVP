#!/usr/bin/env python3
"""
AutoEIA Module SDK CLI
======================
Create, validate, and test AutoEIA analysis modules.

Usage:
    python autoeia.py list                            # list installed modules
    python autoeia.py new <name> [--category <cat>]  # scaffold a new module
    python autoeia.py validate <module_dir>           # check metadata.json only
    python autoeia.py test <module_dir> [--fixture]  # validate + run + check outputs
    python autoeia.py fetch <module_dir>              # download reference datasets
"""

import argparse
import importlib.util
import json
import re
import sys
import traceback
from pathlib import Path

# Ensure UTF-8 output on Windows (needed for emoji and box-drawing chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent
MODULES_DIR = ROOT / "modules"
SDK_DIR = ROOT / "sdk"

# ---------------------------------------------------------------------------
# Valid values (mirrors metadata_schema.json)
# ---------------------------------------------------------------------------

VALID_INPUT_TYPES = {
    "geojson", "number", "string", "text", "boolean",
    "array", "object", "enum", "multiselect", "obj",
}
VALID_OUTPUT_TYPES = {
    "geojson", "html", "text", "object", "number",
    "string", "array", "boolean",
}
VALID_CATEGORIES = {
    "shadows", "transportation", "environmental_justice",
    "air_quality", "noise", "hazardous_materials",
    "socioeconomic", "infrastructure", "natural_resources", "other",
}

# Default test fixture — midtown Manhattan polygon, valid for any NYC module
DEFAULT_FIXTURE = {
    "building_geojson": {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-73.9863, 40.7484],
                        [-73.9848, 40.7484],
                        [-73.9848, 40.7494],
                        [-73.9863, 40.7494],
                        [-73.9863, 40.7484],
                    ]],
                },
            }
        ],
    }
}


# ---------------------------------------------------------------------------
# Metadata validator (inline — no external dependencies)
# ---------------------------------------------------------------------------

def validate_metadata(module_dir: Path) -> tuple[bool, list, list]:
    """
    Validate metadata.json against the AutoEIA module spec.

    Returns:
        (ok, errors, warnings)
    """
    errors = []
    warnings = []

    meta_path = module_dir / "metadata.json"
    if not meta_path.exists():
        return False, [f"metadata.json not found in {module_dir}"], []

    try:
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
    except json.JSONDecodeError as e:
        return False, [f"metadata.json is not valid JSON: {e}"], []

    # Required top-level fields
    for field in ("name", "display_name", "description", "category", "jurisdiction", "inputs", "outputs"):
        if field not in meta:
            errors.append(f"Missing required field: '{field}'")

    if errors:
        return False, errors, warnings

    # name — snake_case
    if not re.match(r"^[a-z][a-z0-9_]*$", str(meta.get("name", ""))):
        errors.append(
            f"'name' must be snake_case, start with a letter, letters/digits/underscores only "
            f"(got '{meta['name']}')"
        )

    # category
    if meta.get("category") not in VALID_CATEGORIES:
        warnings.append(
            f"'category' value '{meta.get('category')}' is not a recognised category. "
            f"Valid: {', '.join(sorted(VALID_CATEGORIES))}"
        )

    # jurisdiction
    if not isinstance(meta.get("jurisdiction"), list) or not meta["jurisdiction"]:
        errors.append("'jurisdiction' must be a non-empty array of strings")

    # inputs
    if not isinstance(meta.get("inputs"), dict) or not meta["inputs"]:
        errors.append("'inputs' must be a non-empty object")
    else:
        for port_name, spec in meta["inputs"].items():
            if not isinstance(spec, dict):
                errors.append(f"Input '{port_name}' must be an object")
                continue
            if "type" not in spec:
                errors.append(f"Input '{port_name}': missing 'type'")
            elif spec["type"] not in VALID_INPUT_TYPES:
                errors.append(
                    f"Input '{port_name}': unknown type '{spec['type']}'. "
                    f"Valid: {', '.join(sorted(VALID_INPUT_TYPES))}"
                )
            if "description" not in spec:
                warnings.append(f"Input '{port_name}': no 'description' — add one for the UI tooltip")
            if spec.get("type") == "enum" and "enum" not in spec:
                errors.append(f"Input '{port_name}': type=enum requires an 'enum' list")
            if spec.get("type") == "multiselect" and "options" not in spec:
                errors.append(f"Input '{port_name}': type=multiselect requires an 'options' list")

    # outputs
    if not isinstance(meta.get("outputs"), dict) or not meta["outputs"]:
        errors.append("'outputs' must be a non-empty object")
    else:
        for port_name, spec in meta["outputs"].items():
            if not isinstance(spec, dict):
                errors.append(f"Output '{port_name}' must be an object")
                continue
            if "type" not in spec:
                errors.append(f"Output '{port_name}': missing 'type'")
            elif spec["type"] not in VALID_OUTPUT_TYPES:
                errors.append(
                    f"Output '{port_name}': unknown type '{spec['type']}'. "
                    f"Valid: {', '.join(sorted(VALID_OUTPUT_TYPES))}"
                )
            if "description" not in spec:
                warnings.append(f"Output '{port_name}': no 'description'")

    return len(errors) == 0, errors, warnings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _size_hint(val) -> str:
    """Return a brief size/content description for a returned value."""
    if val is None:
        return "None"
    if isinstance(val, str):
        return f"{len(val):,} chars"
    if isinstance(val, dict):
        if "features" in val:
            return f"{len(val.get('features', []))} features"
        return f"{len(val)} keys"
    if isinstance(val, list):
        return f"{len(val)} items"
    if isinstance(val, (int, float)):
        return str(round(val, 4))
    if isinstance(val, bool):
        return str(val)
    return type(val).__name__


def _load_module_python(module_dir: Path, module_name: str):
    """Load the module's Python file via importlib. Returns (module, py_file, error)."""
    py_file = module_dir / f"{module_name}.py"
    if not py_file.exists():
        py_file = module_dir / "main.py"
    if not py_file.exists():
        return None, None, f"No Python file found. Expected '{module_name}.py' or 'main.py'"

    try:
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
        return mod, py_file, None
    except Exception as e:
        return None, py_file, f"Import error: {e}"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list():
    """List all installed modules."""
    if not MODULES_DIR.exists():
        print("No modules/ directory found.")
        return

    rows = []
    for module_path in sorted(MODULES_DIR.iterdir()):
        if not module_path.is_dir():
            continue
        meta_file = module_path / "metadata.json"
        if not meta_file.exists():
            continue
        try:
            with open(meta_file, encoding="utf-8") as f:
                meta = json.load(f)
            emoji = meta.get("emoji", "🔧")
            display = meta.get("display_name", module_path.name)
            cat = meta.get("category", "?")
            n_in = len(meta.get("inputs", {}))
            n_out = len(meta.get("outputs", {}))
            rows.append((emoji, display, cat, n_in, n_out))
        except Exception:
            rows.append(("✗", module_path.name, "error", 0, 0))

    if not rows:
        print("No modules installed.")
        return

    max_name = max(len(r[1]) for r in rows)
    max_cat = max(len(r[2]) for r in rows)
    print()
    print(f"  {'Module':<{max_name + 2}}  {'Category':<{max_cat + 2}}  Ports")
    print(f"  {'─' * (max_name + 2)}  {'─' * (max_cat + 2)}  ─────")
    for emoji, display, cat, n_in, n_out in rows:
        print(f"  {emoji}  {display:<{max_name}}  [{cat:<{max_cat}}]  {n_in} in → {n_out} out")
    print(f"\n  {len(rows)} module(s) installed.\n")


def cmd_validate(module_dir: Path) -> bool:
    """Validate metadata.json only. Returns True if valid."""
    ok, errors, warnings = validate_metadata(module_dir)

    for w in warnings:
        print(f"  ⚠  {w}")
    for e in errors:
        print(f"  ✗  {e}")

    if ok:
        with open(module_dir / "metadata.json", encoding="utf-8") as f:
            meta = json.load(f)
        n_in = len(meta.get("inputs", {}))
        n_out = len(meta.get("outputs", {}))
        print(f"  ✓  metadata.json is valid  ({n_in} input{'s' if n_in != 1 else ''}, "
              f"{n_out} output{'s' if n_out != 1 else ''})")

    return ok


def cmd_test(module_dir: Path, fixture_path: Path = None) -> bool:
    """Full validation + execution test."""
    print(f"\n  Testing: {module_dir.name}")
    print("  " + "─" * 50)

    # Step 1: validate metadata
    print("  [1/4] Validating metadata.json...")
    ok, errors, warnings = validate_metadata(module_dir)
    for w in warnings:
        print(f"         ⚠  {w}")
    for e in errors:
        print(f"         ✗  {e}")
    if not ok:
        print("  ✗  Metadata validation failed — fix errors above before testing further.\n")
        return False

    with open(module_dir / "metadata.json", encoding="utf-8") as f:
        meta = json.load(f)
    print(f"         ✓  metadata.json valid")

    # Step 2: find Python file
    print("  [2/4] Locating Python file...")
    module_name = meta["name"]
    py_file = module_dir / f"{module_name}.py"
    if not py_file.exists():
        py_file = module_dir / "main.py"
    if not py_file.exists():
        print(f"         ✗  No Python file found. Expected '{module_name}.py' or 'main.py'")
        return False
    print(f"         ✓  {py_file.name}")

    # Step 3: load module
    print("  [3/4] Loading module...")
    mod, _, err = _load_module_python(module_dir, module_name)
    if err:
        print(f"         ✗  {err}")
        return False
    if not hasattr(mod, "execute"):
        if hasattr(mod, "run"):
            print("         ⚠  No execute() found — using run() (consider renaming to execute)")
            mod.execute = mod.run
        else:
            print("         ✗  No execute() or run() function found")
            return False
    print("         ✓  execute() found")

    # Step 4: run with fixture
    print("  [4/4] Running with test fixture...")

    # Determine fixture source
    inputs = None
    if fixture_path and fixture_path.exists():
        with open(fixture_path, encoding="utf-8") as f:
            raw = json.load(f)
        # Auto-wrap bare GeoJSON FeatureCollections as {"building_geojson": ...}
        if isinstance(raw, dict) and raw.get("type") == "FeatureCollection":
            inputs = {"building_geojson": raw}
            print(f"         Using: {fixture_path}  (wrapped as building_geojson)")
        else:
            inputs = raw
            print(f"         Using: {fixture_path}")
    else:
        local_fixture = module_dir / "test_fixture.json"
        if local_fixture.exists():
            with open(local_fixture, encoding="utf-8") as f:
                inputs = json.load(f)
            print(f"         Using: test_fixture.json")
        else:
            print(f"         ⚠  No test_fixture.json in module directory.")
            print(f"            Create {module_dir / 'test_fixture.json'} to enable execution testing.")
            print(f"            Or pass --fixture <path> to use an existing GeoJSON.\n")
            print(f"  ✓  Structure checks passed (execution skipped — no fixture)\n")
            return True

    # Execute
    try:
        result = mod.execute(inputs)
    except Exception as e:
        print(f"         ✗  execute() raised an exception: {e}")
        traceback.print_exc(file=sys.stdout)
        return False

    if not isinstance(result, dict):
        print(f"         ✗  execute() must return a dict, got {type(result).__name__}")
        return False

    # Check declared outputs
    print()
    declared = set(meta["outputs"].keys())
    returned = set(result.keys())
    missing = declared - returned
    extra = returned - declared

    all_ok = True
    print("  Output check:")
    for key in sorted(declared):
        if key in result:
            val = result[key]
            expected_type = meta["outputs"][key]["type"]
            hint = _size_hint(val)
            print(f"    ✓  {key:<30}  [{expected_type}]  {hint}")
        else:
            print(f"    ✗  {key:<30}  MISSING — declared in metadata.json but not returned")
            all_ok = False

    if extra:
        print()
        for key in sorted(extra):
            print(f"    ⚠  {key:<30}  returned but not declared in outputs — consider adding to metadata.json")

    print()
    if all_ok:
        print(f"  ✅  All checks passed — {module_dir.name} is ready\n")
    else:
        print(f"  ✗  {len(missing)} declared output(s) missing from execute() return value\n")

    return all_ok


def cmd_new(name: str, category: str = "other"):
    """Scaffold a new module directory."""
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        print(f"✗  Module name must be snake_case (letters, digits, underscores; start with a letter).")
        print(f"   Got: '{name}'")
        sys.exit(1)

    module_dir = MODULES_DIR / name
    if module_dir.exists():
        print(f"✗  Directory already exists: {module_dir}")
        print(f"   Choose a different name or delete the existing directory first.")
        sys.exit(1)

    module_dir.mkdir(parents=True)
    display_name = name.replace("_", " ").title()

    # metadata.json
    metadata = {
        "name": name,
        "display_name": display_name,
        "emoji": "🔧",
        "description": (
            f"TODO: Describe what {display_name} analyzes and which regulatory framework "
            "it implements (e.g. 'CEQR Technical Manual Chapter 8 — Shadow Analysis')."
        ),
        "category": category,
        "jurisdiction": ["NYC"],
        "inputs": {
            "building_geojson": {
                "type": "geojson",
                "description": "Project site boundary or building footprint (GeoJSON FeatureCollection).",
                "optional": False,
            }
        },
        "outputs": {
            "visualization": {
                "type": "html",
                "description": "Interactive map or chart showing analysis results.",
            },
            "summary_report": {
                "type": "text",
                "description": "Narrative analysis report in plain text or Markdown.",
            },
        },
    }
    with open(module_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    # Python module
    py_content = f'''\
"""
{display_name}
{"=" * len(display_name)}
TODO: Describe what this module analyzes.

Regulatory basis:
  - TODO: cite the relevant regulation or technical manual section
    e.g. "CEQR Technical Manual Chapter 8 — Shadow Analysis (2024 Edition)"

Inputs  (declared in metadata.json):
  - building_geojson : GeoJSON FeatureCollection of the project footprint

Outputs (declared in metadata.json):
  - visualization   : HTML string (e.g. a Folium interactive map)
  - summary_report  : Plain-text or Markdown report
"""

import json


def execute(inputs: dict) -> dict:
    """
    AutoEIA platform entry point.

    The workflow engine calls this function with a merged dict of:
      - inputs configured by the user in the node panel
      - all outputs from upstream nodes (so you can consume e.g.
        'shadow_polygons' from a preceding shadow module)

    Args:
        inputs: dict whose keys match this module\'s metadata.json inputs
                (plus any keys passed from upstream nodes).

    Returns:
        dict whose keys match this module\'s metadata.json outputs.
        Every key declared in metadata.json outputs MUST be present.

    Raises:
        ValueError: for missing required inputs or invalid data.
    """
    building_geojson = inputs.get("building_geojson")
    if not building_geojson:
        raise ValueError("building_geojson is required")
    if isinstance(building_geojson, str):
        building_geojson = json.loads(building_geojson)

    # ---------------------------------------------------------------
    # TODO: Implement your analysis here
    # See modules/shadow-tier-3/ for a full production example.
    # ---------------------------------------------------------------

    return {{
        "visualization": "<p>TODO: return an HTML string (e.g. a Folium map via m._repr_html_())</p>",
        "summary_report": "TODO: return analysis narrative as plain text or Markdown.",
    }}
'''
    with open(module_dir / f"{name}.py", "w", encoding="utf-8") as f:
        f.write(py_content)

    # test_fixture.json
    with open(module_dir / "test_fixture.json", "w", encoding="utf-8") as f:
        json.dump(DEFAULT_FIXTURE, f, indent=2)

    print(f"""
  ✓  Created module: {module_dir}

  {module_dir}/
  ├── metadata.json      ← declare inputs, outputs, category, description
  ├── {name}.py{"─" * max(0, 16 - len(name))} ← implement execute(inputs) -> dict
  └── test_fixture.json  ← sample inputs for `autoeia test`

  Next steps:
    1. Edit metadata.json  — update description, add/remove input & output ports
    2. Edit {name}.py — implement execute() with your analysis logic
    3. Test:  python autoeia.py test {module_dir}

  Module guide: sdk/MODULE_GUIDE.md
""")


def cmd_fetch(module_dir: Path) -> bool:
    """Run fetch_data.py for a module (download reference datasets)."""
    fetch_file = module_dir / "fetch_data.py"
    if not fetch_file.exists():
        print(f"  ⚠  {module_dir.name}: no fetch_data.py — no reference datasets to download.")
        return True

    print(f"\n  Fetching data for: {module_dir.name}")
    print("  " + "─" * 50)

    module_name = f"_autoeia_fetch_{module_dir.name}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, fetch_file)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"  ✗  Failed to load fetch_data.py: {e}")
        traceback.print_exc(file=sys.stdout)
        return False

    if not hasattr(mod, "fetch"):
        print(f"  ✗  fetch_data.py must expose a fetch() function with no required arguments.")
        print(f"     Add:  fetch = your_fetch_function  at the bottom of fetch_data.py")
        return False

    try:
        mod.fetch()
        return True
    except Exception as e:
        print(f"  ✗  fetch() raised an exception: {e}")
        traceback.print_exc(file=sys.stdout)
        return False


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="autoeia",
        description="AutoEIA Module SDK — create, validate, and test analysis modules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python autoeia.py list
  python autoeia.py new wind_analysis --category air_quality
  python autoeia.py validate modules/shadow-tier-3
  python autoeia.py test modules/shadow-tier-3 --fixture datasets/example_building_midtown.geojson
  python autoeia.py test modules/dac
  python autoeia.py fetch modules/dac
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="List all installed modules")

    # validate
    p_val = sub.add_parser("validate", help="Validate a module's metadata.json (no execution)")
    p_val.add_argument("module_dir", help="Path to module directory (e.g. modules/shadow-tier-3)")

    # test
    p_test = sub.add_parser(
        "test",
        help="Validate metadata, load module, run with fixture, check outputs",
    )
    p_test.add_argument("module_dir", help="Path to module directory")
    p_test.add_argument(
        "--fixture",
        help="Path to a JSON fixture file (overrides test_fixture.json in module directory)",
        default=None,
    )

    # fetch
    p_fetch = sub.add_parser("fetch", help="Download reference datasets for a module (runs fetch_data.py)")
    p_fetch.add_argument("module_dir", help="Path to module directory (e.g. modules/dac)")

    # new
    p_new = sub.add_parser("new", help="Scaffold a new module from template")
    p_new.add_argument("name", help="Module name in snake_case (e.g. wind_analysis)")
    p_new.add_argument(
        "--category",
        default="other",
        choices=sorted(VALID_CATEGORIES),
        help="Module category (default: other)",
    )

    args = parser.parse_args()

    if args.command == "list":
        cmd_list()

    elif args.command == "validate":
        module_dir = Path(args.module_dir)
        ok = cmd_validate(module_dir)
        sys.exit(0 if ok else 1)

    elif args.command == "test":
        module_dir = Path(args.module_dir)
        fixture = Path(args.fixture) if args.fixture else None
        ok = cmd_test(module_dir, fixture)
        sys.exit(0 if ok else 1)

    elif args.command == "fetch":
        module_dir = Path(args.module_dir)
        ok = cmd_fetch(module_dir)
        sys.exit(0 if ok else 1)

    elif args.command == "new":
        cmd_new(args.name, args.category)


if __name__ == "__main__":
    main()
