#!/usr/bin/env python3
"""Validate allow-listed upstream contracts and update immutable lock files."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / ".github" / "dependencies.json"
ODA_MAP_REPOSITORY = "amnotyoung/oda-map-lab"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def require_file(root: Path, relative_path: str) -> Path:
    path = root / relative_path
    if not path.is_file():
        raise ValueError(f"Required dependency file is missing: {relative_path}")
    return path


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, Any]:
    manifest = read_json(path)
    dependencies = manifest.get("dependencies")
    if manifest.get("schema_version") != 1 or not isinstance(dependencies, dict):
        raise ValueError("Dependency manifest must use schema_version 1.")
    for repository, dependency in dependencies.items():
        if not re.fullmatch(r"[^/]+/[^/]+", repository):
            raise ValueError(f"Invalid dependency repository: {repository}")
        required = ("slug", "mode", "source_path", "lock_path")
        if dependency.get("mode") != "contract" or any(
            not dependency.get(key) for key in required
        ):
            raise ValueError(f"Invalid dependency configuration for {repository}")
    return manifest


def dependency_matrix(
    repository: str | None = None,
    sha: str = "",
    ref: str = "",
    manifest: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, str]]]:
    manifest = manifest or load_manifest()
    dependencies = manifest["dependencies"]
    selected = (
        [(repository, dependencies.get(repository))]
        if repository
        else list(dependencies.items())
    )
    if not selected or any(dependency is None for _, dependency in selected):
        raise ValueError(f"Dependency is not allow-listed: {repository}")
    return {
        "include": [
            {
                "repository": source_repository,
                "slug": dependency["slug"],
                "checkout_path": dependency["source_path"],
                "update_path": dependency["lock_path"],
                "ref": sha or ref or dependency.get("branch", "main"),
                "source_ref": ref or dependency.get("branch", "main"),
            }
            for source_repository, dependency in selected
        ]
    }


def validate_oda_map_contract(source_root: Path) -> dict[str, Any]:
    require_file(source_root, "build_web_assets.py")
    map_data = read_json(
        require_file(source_root, "web/public/generated/map-base.json")
    )
    contributor = read_json(
        require_file(
            source_root, "web/public/generated/contributor-schema.json"
        )
    )
    features = map_data.get("features")
    categories = contributor.get("categories")
    required = contributor.get("required")
    if map_data.get("schema_version") != 2 or not isinstance(features, list):
        raise ValueError(
            "ODA Map map-base contract must be schema_version 2 with features[]."
        )
    if not features:
        raise ValueError("ODA Map map-base contract must contain features.")
    feature_keys = {"feature_id", "layer", "name", "country", "details"}
    if any(not feature_keys.issubset(feature) for feature in features):
        raise ValueError("ODA Map features do not expose the fields used by the map skill.")
    if (
        contributor.get("schema_version") != 2
        or not isinstance(categories, list)
        or not isinstance(required, list)
    ):
        raise ValueError(
            "ODA Map contributor contract must be schema_version 2 with "
            "categories[] and required[]."
        )
    expected_required = {"name", "office", "author"}
    if not expected_required.issubset(required):
        missing = ", ".join(sorted(expected_required - set(required)))
        raise ValueError(f"ODA Map contributor contract is missing: {missing}")
    return {
        "contributor_required_fields": sorted(expected_required),
        "contributor_schema_version": contributor["schema_version"],
        "map_feature_count": len(features),
        "map_schema_version": map_data["schema_version"],
    }


def build_lock(
    repository: str, source_sha: str, source_ref: str, contract: dict[str, Any]
) -> dict[str, Any]:
    if not FULL_SHA.fullmatch(source_sha):
        raise ValueError(
            f"Dependency source SHA must be a full commit SHA: {source_sha}"
        )
    return {
        "schema_version": 1,
        "repository": repository,
        "source_ref": source_ref,
        "source_sha": source_sha,
        "contract": contract,
    }


def source_sha(source_root: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write_outputs(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def update_dependency(
    repository: str,
    source_dir: str,
    source_ref: str,
    expected_sha: str = "",
) -> dict[str, Any]:
    manifest = load_manifest()
    dependency = manifest["dependencies"].get(repository)
    if dependency is None:
        raise ValueError(f"Dependency is not allow-listed: {repository}")
    if repository != ODA_MAP_REPOSITORY:
        raise ValueError(f"No dependency contract validator for {repository}")
    source_root = (ROOT / source_dir).resolve()
    actual_sha = source_sha(source_root)
    if expected_sha and expected_sha != actual_sha:
        raise ValueError(
            f"Checked out SHA {actual_sha} does not match requested SHA {expected_sha}."
        )
    contract = validate_oda_map_contract(source_root)
    lock = build_lock(repository, actual_sha, source_ref, contract)
    lock_path = ROOT / dependency["lock_path"]
    content = json.dumps(lock, ensure_ascii=False, indent=2) + "\n"
    previous = lock_path.read_text(encoding="utf-8") if lock_path.exists() else ""
    changed = previous != content
    if changed:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_path.write_text(content, encoding="utf-8")
    short_sha = actual_sha[:12]
    outputs = {
        "branch": f"deps/{dependency['slug']}-{short_sha}",
        "changed": str(changed).lower(),
        "slug": dependency["slug"],
        "source_sha": actual_sha,
        "source_short_sha": short_sha,
        "update_path": dependency["lock_path"],
    }
    write_outputs(outputs)
    return {**outputs, "contract": contract}


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser()
    commands = top.add_subparsers(dest="command", required=True)
    matrix = commands.add_parser("matrix")
    matrix.add_argument("--repository")
    matrix.add_argument("--sha", default="")
    matrix.add_argument("--ref", default="")
    verify = commands.add_parser("verify")
    verify.add_argument("--repository", required=True)
    verify.add_argument("--source-dir", required=True)
    update = commands.add_parser("update")
    update.add_argument("--repository", required=True)
    update.add_argument("--source-dir", required=True)
    update.add_argument("--ref", default="main")
    update.add_argument("--sha", default="")
    return top


def main() -> None:
    args = parser().parse_args()
    if args.command == "matrix":
        result = dependency_matrix(args.repository, args.sha, args.ref)
    elif args.command == "verify":
        if args.repository != ODA_MAP_REPOSITORY:
            raise ValueError(f"No dependency contract validator for {args.repository}")
        result = validate_oda_map_contract((ROOT / args.source_dir).resolve())
    else:
        result = update_dependency(
            args.repository, args.source_dir, args.ref, args.sha
        )
    print(json.dumps(result, ensure_ascii=False, indent=None if args.command == "matrix" else 2))


if __name__ == "__main__":
    main()
