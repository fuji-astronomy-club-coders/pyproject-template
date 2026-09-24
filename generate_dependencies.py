"""Generate dependencies.txt from Python imports and pyproject.toml."""

from __future__ import annotations  # noqa:I001

import argparse
import ast
import importlib.metadata
import keyword
from pathlib import Path
import re
import sys

REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")

IGNORED_DIRS = {
    ".git",
    ".github",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "site-packages",
}

# Python標準ライブラリ。
# sys.stdlib_module_names が利用できるPythonでは自動取得する。
STDLIB_MODULES = set(getattr(sys, "stdlib_module_names", ()))

# よくある import 名と distribution 名の差異。
IMPORT_TO_DISTRIBUTION = {
    "PIL": "Pillow",
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
}


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Analyze Python imports and generate dependencies.txt."
    )

    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="Project root directory.",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output file. Defaults to <root>/dependencies.txt.",
    )

    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include imports from tests/.",
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="Only validate dependencies.txt. Do not modify it.",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print discovered imports.",
    )

    return parser.parse_args()


def normalize_distribution_name(name: str) -> str:
    """Normalize package distribution name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def extract_requirement_name(requirement: str) -> str | None:
    """Extract package requirement name from requirement string."""
    match = REQUIREMENT_NAME_RE.match(requirement)

    if not match:
        return None

    return match.group(1)


def load_project_dependencies(pyproject: Path) -> list[str]:
    """Load dependencies from pyproject.toml."""
    import tomllib

    with pyproject.open("rb") as fp:
        data = tomllib.load(fp)

    project = data.get("project", {})

    dependencies = list(project.get("dependencies", []))

    optional = project.get("optional-dependencies", {})
    dependencies.extend(optional.get("dev", []))

    return dependencies


def find_python_files(
    root: Path,
    include_tests: bool,
) -> list[Path]:
    """Find Python files under the given root directory."""
    files: list[Path] = []

    for path in root.rglob("*.py"):
        relative_parts = path.relative_to(root).parts

        if any(part in IGNORED_DIRS for part in relative_parts):
            continue

        if not include_tests and "tests" in relative_parts:
            continue

        files.append(path)

    return sorted(files)


def extract_imports(path: Path) -> set[str]:
    """Extract top-level imported package names from a Python file."""
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8-sig")

    tree = ast.parse(source, filename=str(path))

    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])

        elif isinstance(node, ast.ImportFrom):
            if node.level != 0:
                continue

            if node.module:
                imports.add(node.module.split(".")[0])

    return imports


def find_local_modules(root: Path) -> set[str]:
    """Find local Python module and package names."""
    modules: set[str] = set()

    for path in root.rglob("*.py"):
        relative = path.relative_to(root)

        if any(part in IGNORED_DIRS for part in relative.parts):
            continue

        if path.name == "__init__.py":
            if len(relative.parts) > 1:
                modules.add(relative.parts[-2])
        else:
            modules.add(path.stem)

    return modules


def build_import_distribution_map() -> dict[str, set[str]]:
    """Build a mapping from import names to distribution package names."""
    mapping: dict[str, set[str]] = {}

    distributions = importlib.metadata.packages_distributions()

    for import_name, distributions_for_import in distributions.items():
        mapping.setdefault(import_name, set()).update(distributions_for_import)

    return mapping


def resolve_distribution(
    import_name: str,
    import_distribution_map: dict[str, set[str]],
) -> str | None:
    """Resolve import name to corresponding distribution package name."""
    explicit = IMPORT_TO_DISTRIBUTION.get(import_name)

    if explicit:
        return explicit

    distributions = import_distribution_map.get(import_name)

    if not distributions:
        return None

    # 通常は1つ。
    # 複数ある場合は名前順で決定的に選択する。
    return sorted(distributions)[0]


def get_installed_version(distribution: str) -> str | None:
    """Get installed version of a distribution package."""
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None


def main() -> int:
    """Execute the dependency analysis and write or check dependencies.txt."""
    args = parse_args()

    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "dependencies.txt"

    pyproject = root / "pyproject.toml"

    if not pyproject.exists():
        print(
            f"ERROR: pyproject.toml not found: {pyproject}",
            file=sys.stderr,
        )
        return 1

    print(f"Project root: {root}")

    declared_requirements = load_project_dependencies(pyproject)

    python_files = find_python_files(
        root,
        include_tests=args.include_tests,
    )

    print(f"Python files: {len(python_files)}")

    imports: set[str] = set()

    for path in python_files:
        file_imports = extract_imports(path)
        imports.update(file_imports)

        if args.verbose and file_imports:
            relative = path.relative_to(root)
            print(f"\n{relative}")
            for name in sorted(file_imports):
                print(f"  {name}")

    local_modules = find_local_modules(root)

    external_imports = {
        name
        for name in imports
        if name not in STDLIB_MODULES and name not in local_modules and not keyword.iskeyword(name)
    }

    import_distribution_map = build_import_distribution_map()

    discovered_distributions: dict[str, str] = {}
    unresolved_imports: set[str] = set()

    for import_name in sorted(external_imports):
        distribution = resolve_distribution(
            import_name,
            import_distribution_map,
        )

        if distribution is None:
            unresolved_imports.add(import_name)
            continue

        version = get_installed_version(distribution)

        if version is None:
            unresolved_imports.add(import_name)
            continue

        discovered_distributions[normalize_distribution_name(distribution)] = (
            f"{distribution}=={version}"
        )

    if unresolved_imports:
        print("\nWARNING: Could not resolve imports:")

        for name in sorted(unresolved_imports):
            print(f"  {name}")

    # pyproject.tomlを正とする。
    # import解析で発見したdistributionが宣言済みなら、
    # そのRequirementを採用する。
    declared_by_name: dict[str, str] = {}

    for requirement in declared_requirements:
        name = extract_requirement_name(requirement)

        if name:
            declared_by_name[normalize_distribution_name(name)] = requirement.strip()

    requirements: dict[str, str] = {}

    # まずpyproject.tomlの定義を入れる。
    for normalized_name, requirement in declared_by_name.items():
        requirements[normalized_name] = requirement

    # import解析で発見した未宣言dependencyを追加。
    for normalized_name, pinned_requirement in discovered_distributions.items():
        if normalized_name not in requirements:
            requirements[normalized_name] = pinned_requirement

    lines = [
        "# This file is generated by generate_dependencies.py.",
        "# Do not edit manually.",
        "",
    ]

    for requirement in sorted(
        requirements.values(),
        key=lambda value: normalize_distribution_name(extract_requirement_name(value) or value),
    ):
        lines.append(requirement)

    content = "\n".join(lines) + "\n"

    if args.check:
        if not output.exists():
            print(f"ERROR: {output} does not exist.")
            return 1

        current = output.read_text(encoding="utf-8")

        if current != content:
            print(
                f"ERROR: {output} is out of date.",
                file=sys.stderr,
            )
            print(
                "Run: python generate_dependencies.py",
                file=sys.stderr,
            )
            return 1

        print(f"OK: {output} is up to date.")
        return 0

    output.write_text(content, encoding="utf-8")

    print(f"\nGenerated: {output}")
    print(f"Dependencies: {len(requirements)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
