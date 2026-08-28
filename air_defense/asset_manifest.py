"""Engine-independent manifest and runtime policy for optional 3D assets.

The STL files are intentionally local-only inputs.  This module contains the
stable names, signed-permutation transforms, colors and fallback contract used
by both the converter and the Ursina scene adapter; it does not import Ursina.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Iterable, Optional


Vector3 = tuple[float, float, float]
Matrix3 = tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]
CANONICAL_UP_AXIS = "+Y"
CANONICAL_FORWARD_AXIS = "+Z"


def matrix_determinant(matrix: Matrix3) -> int:
    """Return the determinant of a 3x3 integer transform."""

    a, b, c = matrix
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


def _validate_matrix(matrix: Matrix3) -> Matrix3:
    if len(matrix) != 3 or any(len(row) != 3 for row in matrix):
        raise ValueError("source_to_canonical must be a 3x3 matrix")
    if any(value not in (-1, 0, 1) for row in matrix for value in row):
        raise ValueError("source_to_canonical must be signed-permutation")
    if any(sum(abs(value) for value in row) != 1 for row in matrix):
        raise ValueError("each transform row must contain one signed axis")
    if any(
        sum(abs(matrix[row][column]) for row in range(3)) != 1
        for column in range(3)
    ):
        raise ValueError("each transform column must contain one signed axis")
    if matrix_determinant(matrix) != 1:
        raise ValueError("source_to_canonical must preserve handedness")
    return matrix


def apply_source_to_canonical(source: Vector3, matrix: Matrix3) -> Vector3:
    """Apply one manifest transform to a source-space point or normal."""

    _validate_matrix(matrix)
    return tuple(
        float(sum(component * axis for component, axis in zip(matrix_row, source)))
        for matrix_row in matrix
    )  # type: ignore[return-value]


def loader_compensation(vector: Vector3) -> Vector3:
    """Compensate for Ursina 8.3.0's OBJ X reflection at conversion time."""

    return (-float(vector[0]), float(vector[1]), float(vector[2]))


# Public callable matching the L(x, y, z) notation in the asset contract.
LOADER_X_COMPENSATION = loader_compensation


@dataclass(frozen=True)
class AssetSpec:
    """One fixed local source-to-runtime mapping."""

    asset_id: str
    source_file: str
    output_file: str
    game_roles: tuple[str, ...]
    source_up: str
    source_forward: str
    source_to_canonical: Matrix3
    runtime_tint: Vector3
    fallback_model: str
    target_extent: Vector3
    anchor: str
    visual_scale_multiplier: float = 1.0
    aim_collider_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if not self.asset_id or Path(self.source_file).name != self.source_file:
            raise ValueError("asset source_file must be a stable local filename")
        if Path(self.output_file).name != self.output_file:
            raise ValueError("asset output_file must be a stable generated filename")
        _validate_matrix(self.source_to_canonical)
        if len(self.runtime_tint) != 3 or not all(isfinite(value) for value in self.runtime_tint):
            raise ValueError("runtime_tint must contain three finite values")
        if len(self.target_extent) != 3 or not all(
            isfinite(value) and value > 0.0 for value in self.target_extent
        ):
            raise ValueError("target_extent must contain three positive finite values")
        if self.anchor not in {"center", "ground"}:
            raise ValueError("anchor must be center or ground")
        if not isfinite(self.visual_scale_multiplier) or self.visual_scale_multiplier <= 0.0:
            raise ValueError("visual_scale_multiplier must be a positive finite value")
        if not isfinite(self.aim_collider_multiplier) or self.aim_collider_multiplier <= 0.0:
            raise ValueError("aim_collider_multiplier must be a positive finite value")


@dataclass(frozen=True)
class RuntimeAssetChoice:
    """Transient per-entity model choice; never persisted to a save file."""

    asset_id: str
    model_path: Optional[Path]
    fallback_model: str
    fallback_used: bool
    runtime_tint: Vector3
    runtime_scale: float
    collider: str = "box"
    load_error: Optional[str] = None
    source_extent: Optional[Vector3] = None
    visual_scale_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if self.runtime_scale <= 0.0 or not isfinite(self.runtime_scale):
            raise ValueError("runtime_scale must be a positive finite value")
        if self.collider != "box":
            raise ValueError("optional assets must retain the simplified box collider")
        if self.fallback_used and self.model_path is not None:
            raise ValueError("fallback choices cannot expose a model path")
        if not self.fallback_used and self.model_path is None:
            raise ValueError("loaded choices require a model path")
        if not isfinite(self.visual_scale_multiplier) or self.visual_scale_multiplier <= 0.0:
            raise ValueError("visual_scale_multiplier must be a positive finite value")


_NEG_XZY: Matrix3 = ((-1, 0, 0), (0, 0, 1), (0, 1, 0))
# Calibrated from the saved local marker tool result: source +Z is up and
# source -Y is forward (aircraft nose/propeller or the person's face).
_SOURCE_Z_UP_NEG_Y_FORWARD: Matrix3 = ((1, 0, 0), (0, 0, 1), (0, -1, 0))
# Calibrated from the saved local marker tool result for the fast aircraft:
# source +Z is up and source -X is forward.
_SOURCE_Z_UP_NEG_X_FORWARD: Matrix3 = ((0, -1, 0), (0, 0, 1), (-1, 0, 0))

_RED_AIRCRAFT = (0.82, 0.25, 0.18)
_ORANGE_AIRCRAFT = (0.86, 0.55, 0.14)
_BLUE_AIRCRAFT = (0.28, 0.62, 0.92)
_PURPLE_BOSS = (0.62, 0.18, 0.68)
_RED_CREW = (0.72, 0.18, 0.16)
_PURPLE_CREW = (0.55, 0.12, 0.70)
_BLUE_GREY_BUILDING = (0.45, 0.55, 0.68)


_ASSET_SPECS: tuple[AssetSpec, ...] = (
    AssetSpec(
        "aircraft_normal",
        "普通飛行.stl",
        "aircraft_normal.obj",
        ("aircraft:normal",),
        "+Z",
        "-Y",
        _SOURCE_Z_UP_NEG_Y_FORWARD,
        _RED_AIRCRAFT,
        "cube",
        (1.6, 0.45, 2.8),
        "center",
        10.0,
    ),
    AssetSpec(
        "aircraft_manpower_support",
        "多人飛機.stl",
        "aircraft_manpower_support.obj",
        ("aircraft:manpower_support",),
        "+Z",
        "-Y",
        _SOURCE_Z_UP_NEG_Y_FORWARD,
        _ORANGE_AIRCRAFT,
        "cube",
        (1.6, 0.45, 2.8),
        "center",
        10.0,
    ),
    AssetSpec(
        "aircraft_fast",
        "速度飛行.stl",
        "aircraft_fast.obj",
        ("aircraft:fast",),
        "+Z",
        "-X",
        _SOURCE_Z_UP_NEG_X_FORWARD,
        _BLUE_AIRCRAFT,
        "cube",
        (1.6, 0.45, 2.8),
        "center",
        10.0,
    ),
    AssetSpec(
        "aircraft_boss",
        "魔王飛行.stl",
        "aircraft_boss.obj",
        ("aircraft:armored_boss",),
        "+Z",
        "-Y",
        _SOURCE_Z_UP_NEG_Y_FORWARD,
        _PURPLE_BOSS,
        "cube",
        (1.9, 0.60, 3.2),
        "center",
        10.0,
    ),
    AssetSpec(
        "crew_normal",
        "普通陸地.stl",
        "crew_normal.obj",
        ("crew:normal", "crew:manpower_support"),
        "+Z",
        "-Y",
        _SOURCE_Z_UP_NEG_Y_FORWARD,
        _RED_CREW,
        "cube",
        (0.65, 1.8, 0.65),
        "ground",
        5.0,
        5.0,
    ),
    AssetSpec(
        "crew_boss",
        "魔王陸地.stl",
        "crew_boss.obj",
        ("crew:boss",),
        "+Z",
        "-Y",
        _SOURCE_Z_UP_NEG_Y_FORWARD,
        _PURPLE_CREW,
        "cube",
        (0.9, 2.4, 0.9),
        "ground",
        5.0,
        5.0,
    ),
    AssetSpec(
        "target_building",
        "大樓.stl",
        "target_building.obj",
        ("target:building",),
        "+Z",
        "+Y",
        _NEG_XZY,
        _BLUE_GREY_BUILDING,
        "cube",
        (10.0, 12.0, 9.0),
        "ground",
        10.0,
    ),
)

ASSET_MANIFEST: dict[str, AssetSpec] = {spec.asset_id: spec for spec in _ASSET_SPECS}
ASSET_SPECS = _ASSET_SPECS
SOURCE_AXIS_TABLE: dict[str, tuple[str, str]] = {
    spec.asset_id: (spec.source_up, spec.source_forward) for spec in _ASSET_SPECS
}


def get_asset_spec(asset_id: str) -> AssetSpec:
    try:
        return ASSET_MANIFEST[str(asset_id)]
    except KeyError as exc:
        raise KeyError(f"unknown asset id: {asset_id}") from exc


def asset_for_aircraft_type(aircraft_type: object) -> AssetSpec:
    value = getattr(aircraft_type, "value", aircraft_type)
    return get_asset_spec(
        {
            "NORMAL": "aircraft_normal",
            "MANPOWER_SUPPORT": "aircraft_manpower_support",
            "FAST": "aircraft_fast",
            "ARMORED_BOSS": "aircraft_boss",
        }[str(value)]
    )


def asset_for_crew(*, is_boss: bool) -> AssetSpec:
    return get_asset_spec("crew_boss" if is_boss else "crew_normal")


def _obj_geometry(path: Path) -> tuple[tuple[Vector3, ...], int]:
    vertices: list[Vector3] = []
    faces: list[tuple[int, int, int]] = []

    def resolve_index(raw_index: int) -> int:
        if raw_index == 0:
            raise ValueError("OBJ face index cannot be zero")
        resolved = raw_index if raw_index > 0 else len(vertices) + raw_index + 1
        if resolved < 1 or resolved > len(vertices):
            raise ValueError("OBJ face index is outside the vertex list")
        return resolved

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if line.startswith("v "):
            fields = line.split()
            if len(fields) < 4:
                raise ValueError("OBJ vertex has fewer than three coordinates")
            point = tuple(float(value) for value in fields[1:4])
            if not all(isfinite(value) for value in point):
                raise ValueError("OBJ contains a non-finite vertex")
            vertices.append(point)  # type: ignore[arg-type]
        elif line.startswith("f "):
            fields = line.split()[1:]
            if len(fields) < 3:
                raise ValueError("OBJ face has fewer than three vertices")
            for token in fields[:3]:
                try:
                    index = int(token.split("/", 1)[0])
                except ValueError as exc:
                    raise ValueError("OBJ face contains an invalid index") from exc
                index = resolve_index(index)
            faces.append(
                tuple(
                    resolve_index(int(token.split("/", 1)[0]))
                    for token in fields[:3]
                )  # type: ignore[arg-type]
            )
    if not vertices or not faces:
        raise ValueError("OBJ has no usable geometry")
    for face in faces:
        first, second, third = (vertices[index - 1] for index in face)
        edge_a = tuple(second[index] - first[index] for index in range(3))
        edge_b = tuple(third[index] - first[index] for index in range(3))
        cross = (
            edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
            edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
            edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
        )
        if sum(value * value for value in cross) <= 1e-18:
            raise ValueError("OBJ contains a degenerate triangle")
    return tuple(vertices), len(faces)


def _extent(vertices: Iterable[Vector3]) -> Vector3:
    points = tuple(vertices)
    if not points:
        raise ValueError("asset has no vertices")
    result = tuple(
        max(point[index] for point in points) - min(point[index] for point in points)
        for index in range(3)
    )
    if not all(isfinite(value) and value > 1e-9 for value in result):
        raise ValueError("asset has a zero or non-finite bounding axis")
    return result  # type: ignore[return-value]


def runtime_asset_choice(
    asset: str | AssetSpec,
    output_root: str | Path,
) -> RuntimeAssetChoice:
    """Select one valid OBJ or an isolated procedural fallback.

    The check is intentionally per asset ID.  A bad file cannot affect the
    color, scale or model choice of another object.
    """

    spec = get_asset_spec(asset) if isinstance(asset, str) else asset
    root = Path(output_root).resolve()
    candidate = (root / spec.output_file).resolve()
    try:
        if root not in candidate.parents or not candidate.is_file():
            raise FileNotFoundError(f"missing OBJ: {spec.output_file}")
        vertices, _ = _obj_geometry(candidate)
        source_extent = _extent(vertices)
        runtime_scale = min(
            target / source
            for target, source in zip(spec.target_extent, source_extent)
        ) * spec.visual_scale_multiplier
        if not isfinite(runtime_scale) or runtime_scale <= 0.0:
            raise ValueError("asset scale is not positive and finite")
        return RuntimeAssetChoice(
            asset_id=spec.asset_id,
            model_path=candidate,
            fallback_model=spec.fallback_model,
            fallback_used=False,
            runtime_tint=spec.runtime_tint,
            runtime_scale=runtime_scale,
            collider="box",
            source_extent=source_extent,
            visual_scale_multiplier=spec.visual_scale_multiplier,
        )
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        return RuntimeAssetChoice(
            asset_id=spec.asset_id,
            model_path=None,
            fallback_model=spec.fallback_model,
            fallback_used=True,
            runtime_tint=spec.runtime_tint,
            runtime_scale=1.0,
            collider="box",
            load_error=str(exc),
            visual_scale_multiplier=1.0,
        )


# Descriptive alias for scene and external callers.
build_runtime_asset_choice = runtime_asset_choice


def canonical_to_obj_vertex(vector: Vector3) -> Vector3:
    """Return the on-disk OBJ coordinate for a canonical point."""

    return loader_compensation(vector)


__all__ = [
    "ASSET_MANIFEST",
    "ASSET_SPECS",
    "AssetSpec",
    "CANONICAL_FORWARD_AXIS",
    "CANONICAL_UP_AXIS",
    "LOADER_X_COMPENSATION",
    "Matrix3",
    "RuntimeAssetChoice",
    "SOURCE_AXIS_TABLE",
    "Vector3",
    "apply_source_to_canonical",
    "asset_for_aircraft_type",
    "asset_for_crew",
    "build_runtime_asset_choice",
    "canonical_to_obj_vertex",
    "get_asset_spec",
    "loader_compensation",
    "matrix_determinant",
    "runtime_asset_choice",
]
