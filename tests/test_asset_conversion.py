"""US1 tests for local STL conversion and isolated runtime asset choices."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from air_defense.asset_manifest import (
    ASSET_MANIFEST,
    LOADER_X_COMPENSATION,
    RuntimeAssetChoice,
    SOURCE_AXIS_TABLE,
    apply_source_to_canonical,
    canonical_to_obj_vertex,
    matrix_determinant,
    runtime_asset_choice,
)
from tools.convert_stl_assets import (
    convert_all,
    convert_asset,
    decode_obj_canonical,
    main,
    read_obj,
)
from tools.mark_asset_forward import (
    DIRECTION_LABELS,
    OUTPUT_DEFAULT,
    REPOSITORY_ROOT,
    SOURCE_ROOT_DEFAULT,
    _axis_matrix,
)


def _ascii_stl(name: str, vertices: tuple[tuple[float, float, float], ...]) -> bytes:
    a, b, c = vertices
    return (
        f"solid {name}\n"
        "  facet normal 0 0 0\n"
        "    outer loop\n"
        f"      vertex {a[0]} {a[1]} {a[2]}\n"
        f"      vertex {b[0]} {b[1]} {b[2]}\n"
        f"      vertex {c[0]} {c[1]} {c[2]}\n"
        "    endloop\n"
        "  endfacet\n"
        f"endsolid {name}\n"
    ).encode("ascii")


def _binary_stl(vertices: tuple[tuple[float, float, float], ...]) -> bytes:
    header = b"binary test".ljust(80, b" ")
    body = struct.pack("<3f", 0.0, 0.0, 0.0)
    body += b"".join(struct.pack("<3f", *vertex) for vertex in vertices)
    body += struct.pack("<H", 0)
    return header + struct.pack("<I", 1) + body


class AssetManifestTests(unittest.TestCase):
    def test_manifest_has_exact_seven_rotations_and_loader_compensation(self) -> None:
        expected = {
            "aircraft_normal": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
            "aircraft_manpower_support": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
            "aircraft_fast": ((0, -1, 0), (0, 0, 1), (-1, 0, 0)),
            "aircraft_boss": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
            "crew_normal": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
            "crew_boss": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
            "target_building": ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
        }
        expected_axes = {
            "aircraft_normal": ("+Z", "-Y"),
            "aircraft_manpower_support": ("+Z", "-Y"),
            "aircraft_fast": ("+Z", "-X"),
            "aircraft_boss": ("+Z", "-Y"),
            "crew_normal": ("+Z", "-Y"),
            "crew_boss": ("+Z", "-Y"),
            "target_building": ("+Z", "+Y"),
        }
        self.assertEqual(set(ASSET_MANIFEST), set(expected))
        for asset_id, matrix in expected.items():
            self.assertEqual(ASSET_MANIFEST[asset_id].source_to_canonical, matrix)
            self.assertEqual(matrix_determinant(matrix), 1)
            self.assertEqual(SOURCE_AXIS_TABLE[asset_id], expected_axes[asset_id])
            self.assertEqual(SOURCE_AXIS_TABLE[asset_id][0], ASSET_MANIFEST[asset_id].source_up)
            self.assertEqual(SOURCE_AXIS_TABLE[asset_id][1], ASSET_MANIFEST[asset_id].source_forward)
        self.assertEqual(LOADER_X_COMPENSATION((1.0, 2.0, 3.0)), (-1.0, 2.0, 3.0))

    def test_binary_and_ascii_stl_convert_to_valid_obj(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source_root = Path(root) / "source"
            output_root = Path(root) / "output"
            source_root.mkdir()
            vertices = ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0))
            (source_root / "普通飛行.stl").write_bytes(_binary_stl(vertices))
            result = convert_asset(
                ASSET_MANIFEST["aircraft_normal"],
                source_root=source_root,
                output_root=output_root,
            )
            self.assertEqual(result.status, "converted")
            self.assertEqual(result.vertex_count, 3)
            self.assertEqual(result.triangle_count, 1)
            self.assertEqual(read_obj(result.output_path).faces, ((1, 2, 3),))
            self.assertEqual(decode_obj_canonical(result.output_path).faces, ((1, 2, 3),))
            self.assertEqual(
                decode_obj_canonical(result.output_path).vertices[0],
                (-1.0, 0.0, 0.5),
            )

            (source_root / "魔王飛行.stl").write_bytes(_ascii_stl("boss", vertices))
            ascii_result = convert_asset(
                ASSET_MANIFEST["aircraft_boss"],
                source_root=source_root,
                output_root=output_root,
            )
            self.assertEqual(ascii_result.status, "converted")
            self.assertEqual(ascii_result.triangle_count, 1)

    def test_fixed_mapping_is_applied_before_loader_compensation(self) -> None:
        source = (2.0, 3.0, 5.0)
        canonical = apply_source_to_canonical(
            source,
            ASSET_MANIFEST["aircraft_normal"].source_to_canonical,
        )
        self.assertEqual(canonical, (2.0, 5.0, -3.0))
        self.assertEqual(canonical_to_obj_vertex(canonical), (-2.0, 5.0, -3.0))

    def test_nonfinite_and_degenerate_facets_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source_root = Path(root) / "source"
            output_root = Path(root) / "output"
            source_root.mkdir()
            valid = _ascii_stl(
                "mixed",
                ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            )
            invalid = (
                b"solid invalid\n"
                b"facet normal 0 0 0\nouter loop\n"
                b"vertex nan 0 0\nvertex 0 0 0\nvertex 0 0 0\n"
                b"endloop\nendfacet\n"
                b"facet normal 0 0 0\nouter loop\n"
                b"vertex 0 0 0\nvertex 0 0 0\nvertex 0 0 0\n"
                b"endloop\nendfacet\nendsolid invalid\n"
            )
            (source_root / "普通飛行.stl").write_bytes(valid[:-1] + invalid)
            result = convert_asset(
                ASSET_MANIFEST["aircraft_normal"],
                source_root=source_root,
                output_root=output_root,
            )
            self.assertEqual(result.status, "converted")
            self.assertEqual(result.triangle_count, 1)

            (source_root / "普通飛行.stl").write_bytes(invalid)
            failed = convert_asset(
                ASSET_MANIFEST["aircraft_normal"],
                source_root=source_root,
                output_root=output_root,
            )
            self.assertEqual(failed.status, "failed")
            self.assertTrue((output_root / "aircraft_normal.obj").is_file())

    def test_check_and_failure_isolation_use_all_exit_codes(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source_root = Path(root) / "source"
            output_root = Path(root) / "output"
            source_root.mkdir()
            (source_root / "普通飛行.stl").write_bytes(
                _ascii_stl("normal", ((0, 0, 0), (1, 0, 0), (0, 1, 0)))
            )
            results = convert_all(source_root=source_root, output_root=output_root)
            self.assertEqual(results["aircraft_normal"].status, "converted")
            self.assertEqual(results["aircraft_boss"].status, "failed")
            self.assertTrue((output_root / "aircraft_normal.obj").is_file())

            self.assertEqual(
                main(
                    [
                        "--source-root",
                        str(source_root),
                        "--output-root",
                        str(output_root),
                        "--check",
                    ]
                ),
                1,
            )
            self.assertEqual(main(["--definitely-invalid"]), 2)

    def test_repeated_conversion_is_deterministic_and_leaves_no_partial_files(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source_root = Path(root) / "source"
            output_root = Path(root) / "output"
            source_root.mkdir()
            (source_root / "普通飛行.stl").write_bytes(
                _ascii_stl("normal", ((0, 0, 0), (1, 0, 0), (0, 1, 0)))
            )

            first = convert_asset(
                ASSET_MANIFEST["aircraft_normal"],
                source_root=source_root,
                output_root=output_root,
            )
            first_bytes = first.output_path.read_bytes()
            second = convert_asset(
                ASSET_MANIFEST["aircraft_normal"],
                source_root=source_root,
                output_root=output_root,
            )

            self.assertEqual(second.status, "converted")
            self.assertEqual(second.output_path.read_bytes(), first_bytes)
            self.assertEqual(list(output_root.glob("*.tmp")), [])
            self.assertEqual(list(output_root.glob("*.part")), [])

    def test_successful_check_returns_zero_after_all_assets_exist(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source_root = Path(root) / "source"
            output_root = Path(root) / "output"
            source_root.mkdir()
            triangle = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
            for spec in ASSET_MANIFEST.values():
                (source_root / spec.source_file).write_bytes(
                    _ascii_stl(spec.asset_id, triangle)
                )

            results = convert_all(source_root=source_root, output_root=output_root)
            self.assertTrue(all(result.status == "converted" for result in results.values()))
            self.assertEqual(
                main(
                    [
                        "--source-root",
                        str(source_root),
                        "--output-root",
                        str(output_root),
                        "--check",
                    ]
                ),
                0,
            )

    def test_axis_calibration_matrix_maps_marked_axes_to_y_up_z_forward(self) -> None:
        self.assertEqual(
            _axis_matrix("+Y", "+Z"),
            [[-1, 0, 0], [0, 0, 1], [0, 1, 0]],
        )
        self.assertEqual(
            _axis_matrix("+X", "+Z"),
            [[0, 1, 0], [0, 0, 1], [1, 0, 0]],
        )
        self.assertIsNone(_axis_matrix("+Y", "+Y"))

    def test_axis_calibration_defaults_are_rooted_at_the_repository(self) -> None:
        self.assertEqual(REPOSITORY_ROOT, Path(__file__).resolve().parents[1])
        self.assertEqual(SOURCE_ROOT_DEFAULT, REPOSITORY_ROOT / "遊戲3d")
        self.assertEqual(
            OUTPUT_DEFAULT,
            REPOSITORY_ROOT / "assets/air_defense/models/asset_axis_calibration.json",
        )
        self.assertTrue(SOURCE_ROOT_DEFAULT.is_absolute())
        self.assertTrue(OUTPUT_DEFAULT.is_absolute())

    def test_axis_calibration_labels_use_cardinal_directions(self) -> None:
        self.assertEqual(
            DIRECTION_LABELS,
            {
                "+Z": "前",
                "-Z": "後",
                "+X": "右",
                "-X": "左",
                "+Y": "上",
                "-Y": "下",
            },
        )

    def test_scene_lighting_shader_contains_sun_highlight_inputs(self) -> None:
        from air_defense.lighting import lit_with_sun_specular_shader

        self.assertIn("sun_specular_color", lit_with_sun_specular_shader.fragment)
        self.assertIn("sun_specular_strength", lit_with_sun_specular_shader.fragment)
        self.assertIn("sun_specular_shininess", lit_with_sun_specular_shader.fragment)
        self.assertEqual(lit_with_sun_specular_shader.default_input["shadow_samples"], 2)


class RuntimeAssetChoiceTests(unittest.TestCase):
    def test_new_external_models_use_role_visual_scale(self) -> None:
        expected = {
            "aircraft_normal": 10.0,
            "aircraft_manpower_support": 10.0,
            "aircraft_fast": 10.0,
            "aircraft_boss": 10.0,
            "crew_normal": 5.0,
            "crew_boss": 5.0,
            "target_building": 10.0,
        }
        self.assertEqual(
            {asset_id: spec.visual_scale_multiplier for asset_id, spec in ASSET_MANIFEST.items()},
            expected,
        )

    def test_ground_people_aim_envelope_matches_their_visual_scale(self) -> None:
        self.assertEqual(ASSET_MANIFEST["crew_normal"].aim_collider_multiplier, 5.0)
        self.assertEqual(ASSET_MANIFEST["crew_boss"].aim_collider_multiplier, 5.0)
        self.assertEqual(
            ASSET_MANIFEST["crew_normal"].aim_collider_multiplier,
            ASSET_MANIFEST["crew_normal"].visual_scale_multiplier,
        )
        self.assertEqual(
            ASSET_MANIFEST["crew_boss"].aim_collider_multiplier,
            ASSET_MANIFEST["crew_boss"].visual_scale_multiplier,
        )
        self.assertEqual(ASSET_MANIFEST["aircraft_normal"].aim_collider_multiplier, 1.0)
        self.assertEqual(ASSET_MANIFEST["aircraft_boss"].aim_collider_multiplier, 1.0)
        self.assertEqual(ASSET_MANIFEST["target_building"].aim_collider_multiplier, 1.0)

    def test_ground_aim_box_matches_the_loaded_visual_mesh_size(self) -> None:
        from air_defense.scene import AirDefenseScene

        class FakeEntity:
            pass

        entity = FakeEntity()
        collider = Mock()
        choice = RuntimeAssetChoice(
            asset_id="crew_normal",
            model_path=Path("crew_normal.obj"),
            fallback_model="cube",
            fallback_used=False,
            runtime_tint=ASSET_MANIFEST["crew_normal"].runtime_tint,
            runtime_scale=0.5,
            source_extent=(10.0, 20.0, 30.0),
            visual_scale_multiplier=5.0,
        )
        with (
            patch("air_defense.scene.UrsinaEntity", FakeEntity),
            patch("air_defense.scene.BoxCollider", return_value=collider) as box,
        ):
            AirDefenseScene._preserve_asset_collider(
                entity,
                choice,
                aim_collider_multiplier=5.0,
            )

        box.assert_called_once_with(
            entity=entity,
            center=(0.0, 0.0, 0.0),
            size=(10.0, 20.0, 30.0),
        )
        self.assertEqual(entity.collider, collider)

    def test_loaded_box_reverses_the_external_visual_multiplier_for_baseline(self) -> None:
        from air_defense.scene import AirDefenseScene

        class FakeEntity:
            pass

        entity = FakeEntity()
        collider = Mock()
        choice = RuntimeAssetChoice(
            asset_id="aircraft_normal",
            model_path=Path("aircraft_normal.obj"),
            fallback_model="cube",
            fallback_used=False,
            runtime_tint=ASSET_MANIFEST["aircraft_normal"].runtime_tint,
            runtime_scale=0.25,
            source_extent=(10.0, 20.0, 30.0),
            visual_scale_multiplier=10.0,
        )
        with (
            patch("air_defense.scene.UrsinaEntity", FakeEntity),
            patch("air_defense.scene.BoxCollider", return_value=collider) as box,
        ):
            AirDefenseScene._preserve_asset_collider(
                entity,
                choice,
                aim_collider_multiplier=1.0,
            )

        box.assert_called_once_with(
            entity=entity,
            center=(0.0, 0.0, 0.0),
            size=(1.0, 2.0, 3.0),
        )
        self.assertEqual(entity.collider, collider)

    def test_loaded_aircraft_projection_radius_includes_mesh_extent(self) -> None:
        from types import SimpleNamespace

        from ursina import Vec3

        from air_defense.scene import AirDefenseScene

        choice = RuntimeAssetChoice(
            asset_id="aircraft_normal",
            model_path=Path("aircraft_normal.obj"),
            fallback_model="cube",
            fallback_used=False,
            runtime_tint=ASSET_MANIFEST["aircraft_normal"].runtime_tint,
            runtime_scale=0.5,
            source_extent=(10.0, 20.0, 30.0),
            visual_scale_multiplier=10.0,
        )
        entity = SimpleNamespace(
            world_position=(0.0, 0.0, 100.0),
            scale_x=0.5,
            scale_y=0.5,
            scale_z=0.5,
            runtime_asset_choice=choice,
        )
        scene = AirDefenseScene.__new__(AirDefenseScene)
        with patch(
            "air_defense.scene.camera",
            SimpleNamespace(world_position=Vec3(0.0, 0.0, 0.0), fov=60.0),
        ):
            radius = scene._projected_aircraft_radius(entity, 1280.0, 720.0)

        # The projection uses the external mesh extent rather than only the
        # normalized Entity scale.  Compare with the legacy-scale fallback so
        # this remains stable if the HUD's absolute clamp changes.
        baseline_entity = SimpleNamespace(
            world_position=(0.0, 0.0, 100.0),
            scale_x=0.5,
            scale_y=0.5,
            scale_z=0.5,
        )
        with patch(
            "air_defense.scene.camera",
            SimpleNamespace(world_position=Vec3(0.0, 0.0, 0.0), fov=60.0),
        ):
            baseline_radius = scene._projected_aircraft_radius(
                baseline_entity,
                1280.0,
                720.0,
            )
        self.assertGreater(radius, baseline_radius)

    def test_ground_aim_box_matches_the_fallback_visual_size(self) -> None:
        from air_defense.scene import AirDefenseScene

        class FakeEntity:
            pass

        entity = FakeEntity()
        collider = Mock()
        choice = RuntimeAssetChoice(
            asset_id="crew_normal",
            model_path=None,
            fallback_model="cube",
            fallback_used=True,
            runtime_tint=ASSET_MANIFEST["crew_normal"].runtime_tint,
            runtime_scale=1.0,
            visual_scale_multiplier=1.0,
            load_error="missing OBJ",
        )
        with (
            patch("air_defense.scene.UrsinaEntity", FakeEntity),
            patch("air_defense.scene.BoxCollider", return_value=collider) as box,
        ):
            AirDefenseScene._preserve_asset_collider(
                entity,
                choice,
                aim_collider_multiplier=5.0,
            )

        box.assert_called_once_with(
            entity=entity,
            center=(0.0, 0.0, 0.0),
            size=(1.0, 1.0, 1.0),
        )
        self.assertEqual(entity.collider, collider)

    def test_missing_or_invalid_one_asset_falls_back_without_affecting_another(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_root = Path(root) / "models"
            output_root.mkdir()
            normal_path = output_root / "aircraft_normal.obj"
            normal_path.write_text(
                "v 0 0 0\nv 1 0 0\nv 0 1 1\nf 1 2 3\n",
                encoding="utf-8",
            )
            normal = runtime_asset_choice("aircraft_normal", output_root)
            boss = runtime_asset_choice("aircraft_boss", output_root)
            self.assertFalse(normal.fallback_used)
            self.assertIsNotNone(normal.model_path)
            self.assertGreater(normal.runtime_scale, 0.0)
            self.assertTrue(boss.fallback_used)
            self.assertIsNone(boss.model_path)
            self.assertIn("missing", (boss.load_error or "").lower())

    def test_loaded_models_use_role_scale_multiplier_without_changing_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            output_root = Path(root)
            (output_root / "aircraft_normal.obj").write_text(
                "v 0 0 0\nv 1 0 0\nv 0 1 1\nf 1 2 3\n",
                encoding="utf-8",
            )
            loaded = runtime_asset_choice("aircraft_normal", output_root)
            missing = runtime_asset_choice("aircraft_boss", output_root)

        self.assertFalse(loaded.fallback_used)
        self.assertEqual(
            loaded.visual_scale_multiplier,
            ASSET_MANIFEST["aircraft_normal"].visual_scale_multiplier,
        )
        self.assertAlmostEqual(
            loaded.runtime_scale,
            0.45 * ASSET_MANIFEST["aircraft_normal"].visual_scale_multiplier,
        )
        self.assertEqual(missing.visual_scale_multiplier, 1.0)


if __name__ == "__main__":
    unittest.main()
