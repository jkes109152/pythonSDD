"""Convert the seven local STL sources into canonical, optional OBJ assets.

The converter intentionally has no Ursina dependency.  It applies the fixed
manifest transform, centers the canonical geometry and compensates for
Ursina's OBJ X reflection before atomically replacing one output file.  A
failed asset never removes another asset's output.
"""

from __future__ import annotations

import argparse
import os
import re
import struct
import sys
from dataclasses import dataclass
from math import isfinite, sqrt
from pathlib import Path
from typing import Iterable, Sequence

try:
    from air_defense.asset_manifest import (
        ASSET_MANIFEST,
        AssetSpec,
        apply_source_to_canonical,
        canonical_to_obj_vertex,
        loader_compensation,
    )
except ModuleNotFoundError:  # Direct ``python tools/...`` from the repo root.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from air_defense.asset_manifest import (  # type: ignore[no-redef]
        ASSET_MANIFEST,
        AssetSpec,
        apply_source_to_canonical,
        canonical_to_obj_vertex,
        loader_compensation,
    )


Vector3 = tuple[float, float, float]
_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|[-+]?(?:nan|inf)"
_VERTEX_RE = re.compile(rf"^\s*vertex\s+({_FLOAT})\s+({_FLOAT})\s+({_FLOAT})\s*$", re.IGNORECASE)
_DEGENERATE_AREA_SQUARED = 1e-18


@dataclass(frozen=True)
class STLFacet:
    vertices: tuple[Vector3, Vector3, Vector3]


@dataclass(frozen=True)
class ObjGeometry:
    vertices: tuple[Vector3, ...]
    normals: tuple[Vector3, ...]
    faces: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class AssetConversionResult:
    asset_id: str
    source_path: Path
    output_path: Path
    status: str
    vertex_count: int = 0
    triangle_count: int = 0
    error: str | None = None


def _vector_subtract(first: Vector3, second: Vector3) -> Vector3:
    return tuple(left - right for left, right in zip(first, second))  # type: ignore[return-value]


def _cross(first: Vector3, second: Vector3) -> Vector3:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _normal(vector: Vector3) -> Vector3:
    length = sqrt(sum(component * component for component in vector))
    if length <= 1e-12 or not isfinite(length):
        raise ValueError("triangle normal is degenerate")
    return tuple(component / length for component in vector)  # type: ignore[return-value]


def _facet_is_valid(facet: STLFacet) -> bool:
    if not all(isfinite(value) for vertex in facet.vertices for value in vertex):
        return False
    edge_a = _vector_subtract(facet.vertices[1], facet.vertices[0])
    edge_b = _vector_subtract(facet.vertices[2], facet.vertices[0])
    area_vector = _cross(edge_a, edge_b)
    return sum(value * value for value in area_vector) > _DEGENERATE_AREA_SQUARED


def _read_binary_stl(data: bytes) -> list[STLFacet] | None:
    if len(data) < 84:
        return None
    try:
        count = struct.unpack_from("<I", data, 80)[0]
    except struct.error:
        return None
    expected_size = 84 + count * 50
    if count == 0 or expected_size != len(data):
        return None
    facets: list[STLFacet] = []
    offset = 84
    try:
        for _ in range(count):
            values = struct.unpack_from("<12f", data, offset)
            facets.append(
                STLFacet(
                    (
                        (values[3], values[4], values[5]),
                        (values[6], values[7], values[8]),
                        (values[9], values[10], values[11]),
                    )
                )
            )
            offset += 50
    except struct.error as exc:
        raise ValueError("binary STL facet data is truncated") from exc
    return facets


def _read_ascii_stl(data: bytes) -> list[STLFacet]:
    text = data.decode("utf-8-sig", errors="replace")
    vertices: list[Vector3] = []
    for line in text.splitlines():
        match = _VERTEX_RE.match(line)
        if match is None:
            continue
        vertices.append(tuple(float(value) for value in match.groups()))  # type: ignore[arg-type]
    if not vertices:
        raise ValueError("STL contains no vertex records")
    if len(vertices) % 3:
        raise ValueError("ASCII STL has an incomplete facet")
    return [
        STLFacet((vertices[index], vertices[index + 1], vertices[index + 2]))
        for index in range(0, len(vertices), 3)
    ]


def parse_stl(data: bytes) -> tuple[STLFacet, ...]:
    """Parse binary STL first when its exact record size is unambiguous."""

    binary = _read_binary_stl(data)
    facets = binary if binary is not None else _read_ascii_stl(data)
    if not facets:
        raise ValueError("STL contains no facets")
    return tuple(facets)


def _canonical_facets(spec: AssetSpec, facets: Iterable[STLFacet]) -> list[STLFacet]:
    result: list[STLFacet] = []
    for facet in facets:
        if not _facet_is_valid(facet):
            continue
        transformed = tuple(
            apply_source_to_canonical(vertex, spec.source_to_canonical)
            for vertex in facet.vertices
        )
        canonical = STLFacet(transformed)  # type: ignore[arg-type]
        if _facet_is_valid(canonical):
            result.append(canonical)
    if not result:
        raise ValueError("STL has no finite, non-degenerate facets")
    return result


def _center_facets(facets: Sequence[STLFacet]) -> list[STLFacet]:
    vertices = [vertex for facet in facets for vertex in facet.vertices]
    center = tuple(
        (min(vertex[index] for vertex in vertices) + max(vertex[index] for vertex in vertices))
        / 2.0
        for index in range(3)
    )
    centered: list[STLFacet] = []
    for facet in facets:
        centered.append(
            STLFacet(
                tuple(
                    tuple(point[index] - center[index] for index in range(3))  # type: ignore[misc]
                    for point in facet.vertices
                )  # type: ignore[arg-type]
            )
        )
    return centered


def facets_to_obj(facets: Sequence[STLFacet]) -> ObjGeometry:
    """Build deterministic per-face vertices and recomputed normals."""

    vertices: list[Vector3] = []
    normals: list[Vector3] = []
    faces: list[tuple[int, int, int]] = []
    for facet in facets:
        normal = _normal(
            _cross(
                _vector_subtract(facet.vertices[1], facet.vertices[0]),
                _vector_subtract(facet.vertices[2], facet.vertices[0]),
            )
        )
        first = len(vertices) + 1
        vertices.extend(canonical_to_obj_vertex(vertex) for vertex in facet.vertices)
        normals.extend(loader_compensation(normal) for _ in range(3))
        # Vertices and normals are both written through the loader's X
        # reflection compensation.  The loader therefore returns the same
        # canonical vertex order; reversing the face here would make the
        # geometric winding disagree with the explicit normal.
        faces.append((first, first + 1, first + 2))
    return ObjGeometry(tuple(vertices), tuple(normals), tuple(faces))


def _parse_obj_index(token: str, vertex_count: int) -> int:
    try:
        value = int(token.split("/", 1)[0])
    except ValueError as exc:
        raise ValueError("OBJ face contains an invalid index") from exc
    if value == 0:
        raise ValueError("OBJ face index cannot be zero")
    resolved = value if value > 0 else vertex_count + value + 1
    if resolved < 1 or resolved > vertex_count:
        raise ValueError("OBJ face index is outside the vertex list")
    return resolved


def read_obj(path: str | Path) -> ObjGeometry:
    """Read the subset of OBJ emitted by this converter (and simple test OBJ)."""

    vertices: list[Vector3] = []
    normals: list[Vector3] = []
    faces: list[tuple[int, int, int]] = []
    for raw_line in Path(path).read_text(encoding="utf-8", errors="strict").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if fields[0] == "v":
            if len(fields) < 4:
                raise ValueError("OBJ vertex has fewer than three coordinates")
            point = tuple(float(value) for value in fields[1:4])
            if not all(isfinite(value) for value in point):
                raise ValueError("OBJ contains a non-finite vertex")
            vertices.append(point)  # type: ignore[arg-type]
        elif fields[0] == "vn":
            if len(fields) < 4:
                raise ValueError("OBJ normal has fewer than three coordinates")
            normal = tuple(float(value) for value in fields[1:4])
            if not all(isfinite(value) for value in normal):
                raise ValueError("OBJ contains a non-finite normal")
            normals.append(normal)  # type: ignore[arg-type]
        elif fields[0] == "f":
            if len(fields) != 4:
                raise ValueError("OBJ output must contain triangular faces")
            faces.append(tuple(_parse_obj_index(token, len(vertices)) for token in fields[1:4]))  # type: ignore[arg-type]
    if not vertices or not faces:
        raise ValueError("OBJ has no usable geometry")
    return ObjGeometry(tuple(vertices), tuple(normals), tuple(faces))


def decode_obj_canonical(path: str | Path) -> ObjGeometry:
    """Undo only the on-disk loader compensation for converter verification."""

    geometry = read_obj(path)
    return ObjGeometry(
        vertices=tuple(loader_compensation(vertex) for vertex in geometry.vertices),
        normals=tuple(loader_compensation(normal) for normal in geometry.normals),
        faces=geometry.faces,
    )


def _validate_obj_geometry(path: Path) -> ObjGeometry:
    geometry = decode_obj_canonical(path)
    if not geometry.vertices or not geometry.faces:
        raise ValueError("OBJ has no usable geometry")
    for face in geometry.faces:
        first, second, third = (geometry.vertices[index - 1] for index in face)
        if not _facet_is_valid(STLFacet((first, second, third))):
            raise ValueError("OBJ contains a degenerate triangle")
    return geometry


def _format_float(value: float) -> str:
    if abs(value) < 5e-13:
        value = 0.0
    return f"{value:.9g}"


def _obj_text(asset_id: str, geometry: ObjGeometry) -> str:
    lines = [
        "# Generated locally by tools/convert_stl_assets.py; do not edit.",
        f"o {asset_id}",
    ]
    lines.extend(
        "v " + " ".join(_format_float(value) for value in vertex)
        for vertex in geometry.vertices
    )
    lines.extend(
        "vn " + " ".join(_format_float(value) for value in normal)
        for normal in geometry.normals
    )
    lines.extend(
        "f " + " ".join(f"{index}//{index}" for index in face)
        for face in geometry.faces
    )
    return "\n".join(lines) + "\n"


def _safe_child(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if root not in candidate.parents:
        raise ValueError("asset path escapes its configured root")
    return candidate


def _failure(spec: AssetSpec, source_path: Path, output_path: Path, error: object) -> AssetConversionResult:
    message = str(error).strip() or "asset conversion failed"
    return AssetConversionResult(
        asset_id=spec.asset_id,
        source_path=source_path,
        output_path=output_path,
        status="failed",
        error=message,
    )


def convert_asset(
    spec: AssetSpec,
    *,
    source_root: str | Path = Path("遊戲3d"),
    output_root: str | Path = Path("assets/air_defense/models"),
    check: bool = False,
) -> AssetConversionResult:
    """Convert or validate one manifest item without affecting other items."""

    source_root_path = Path(source_root)
    output_root_path = Path(output_root)
    try:
        source_path = _safe_child(source_root_path, spec.source_file)
        output_path = _safe_child(output_root_path, spec.output_file)
    except (OSError, ValueError) as exc:
        fallback_source = source_root_path / spec.source_file
        fallback_output = output_root_path / spec.output_file
        return _failure(spec, fallback_source, fallback_output, exc)

    try:
        source_data = source_path.read_bytes()
        source_facets = _canonical_facets(spec, parse_stl(source_data))
        if check:
            if not output_path.is_file():
                raise FileNotFoundError(f"missing OBJ: {spec.output_file}")
            geometry = _validate_obj_geometry(output_path)
            return AssetConversionResult(
                spec.asset_id,
                source_path,
                output_path,
                "skipped",
                len(geometry.vertices),
                len(geometry.faces),
            )

        centered_facets = _center_facets(source_facets)
        geometry = facets_to_obj(centered_facets)
        output_root_path.resolve().mkdir(parents=True, exist_ok=True)
        temporary_path = output_path.with_name(f".{output_path.name}.tmp")
        try:
            temporary_path.write_text(_obj_text(spec.asset_id, geometry), encoding="utf-8", newline="\n")
            validated = _validate_obj_geometry(temporary_path)
            os.replace(temporary_path, output_path)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        return AssetConversionResult(
            spec.asset_id,
            source_path,
            output_path,
            "converted",
            len(validated.vertices),
            len(validated.faces),
        )
    except (OSError, UnicodeError, ValueError, struct.error, OverflowError) as exc:
        return _failure(spec, source_path, output_path, exc)


def convert_all(
    *,
    source_root: str | Path = Path("遊戲3d"),
    output_root: str | Path = Path("assets/air_defense/models"),
    check: bool = False,
) -> dict[str, AssetConversionResult]:
    """Process every manifest item in stable order, even after failures."""

    return {
        asset_id: convert_asset(
            spec,
            source_root=source_root,
            output_root=output_root,
            check=check,
        )
        for asset_id, spec in ASSET_MANIFEST.items()
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert local air-defense STL assets to OBJ")
    parser.add_argument("--source-root", default="遊戲3d", help="directory containing the seven STL files")
    parser.add_argument(
        "--output-root",
        default="assets/air_defense/models",
        help="directory for generated OBJ files",
    )
    parser.add_argument("--check", action="store_true", help="validate sources and existing OBJ files without writing")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else 2
    results = convert_all(
        source_root=args.source_root,
        output_root=args.output_root,
        check=args.check,
    )
    for result in results.values():
        detail = f" error={result.error}" if result.error else ""
        print(
            f"{result.status:9} {result.asset_id:28} "
            f"vertices={result.vertex_count:<5} triangles={result.triangle_count:<5}{detail}"
        )
    return 0 if all(result.status in {"converted", "skipped"} for result in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AssetConversionResult",
    "ObjGeometry",
    "STLFacet",
    "convert_all",
    "convert_asset",
    "decode_obj_canonical",
    "facets_to_obj",
    "main",
    "parse_stl",
    "read_obj",
]
