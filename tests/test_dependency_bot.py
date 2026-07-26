from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.dependency_bot import (
    build_lock,
    dependency_matrix,
    load_manifest,
    validate_oda_map_contract,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class DependencyBotTest(unittest.TestCase):
    def test_manifest_allows_only_declared_repository(self) -> None:
        manifest = load_manifest()
        matrix = dependency_matrix(
            "amnotyoung/oda-map-lab", sha="a" * 40, manifest=manifest
        )
        self.assertEqual(matrix["include"][0]["ref"], "a" * 40)
        with self.assertRaisesRegex(ValueError, "not allow-listed"):
            dependency_matrix("other/private-repo", manifest=manifest)

    def test_lock_requires_full_immutable_sha(self) -> None:
        with self.assertRaisesRegex(ValueError, "full commit SHA"):
            build_lock("amnotyoung/example", "abc123", "main", {})

    def test_oda_map_contract_matches_fields_consumed_by_skill(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "build_web_assets.py").write_text("# fixture\n")
            write_json(
                root / "web/public/generated/map-base.json",
                {
                    "schema_version": 2,
                    "features": [
                        {
                            "feature_id": "project:1",
                            "layer": "project",
                            "name": {"ko": "사업 · 프놈펜"},
                            "country": "캄보디아",
                            "details": {},
                        }
                    ],
                },
            )
            write_json(
                root / "web/public/generated/contributor-schema.json",
                {
                    "schema_version": 2,
                    "categories": [],
                    "required": ["name", "office", "author"],
                },
            )
            contract = validate_oda_map_contract(root)
            self.assertEqual(contract["map_schema_version"], 2)
            self.assertEqual(
                contract["contributor_required_fields"],
                ["author", "name", "office"],
            )


if __name__ == "__main__":
    unittest.main()
