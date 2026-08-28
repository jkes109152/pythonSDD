"""Interactive source-axis marker for the local STL assets.

Run this tool before changing the asset manifest when a model's front or up
direction is ambiguous::

    python tools/mark_asset_forward.py

The viewer shows the untransformed STL with six labelled direction lines:
前(+Z), 後(-Z), 右(+X), 左(-X), 上(+Y) and 下(-Y).  Select the source
direction that points toward the aircraft nose/person face and the direction
that points upward.  The result is written to a local JSON file so it can be
inspected and used to update ``asset_manifest.py``.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from math import isfinite, sqrt
from pathlib import Path
from typing import Optional

from ursina import Entity, Mesh, Text, Ursina, application, camera, color, destroy, window
from ursina.prefabs.editor_camera import EditorCamera

try:
    from air_defense.asset_manifest import ASSET_SPECS
    from tools.convert_stl_assets import STLFacet, parse_stl
except ModuleNotFoundError:  # Direct invocation from outside the repository root.
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from air_defense.asset_manifest import ASSET_SPECS  # type: ignore[no-redef]
    from tools.convert_stl_assets import STLFacet, parse_stl  # type: ignore[no-redef]


AXIS_KEYS: dict[str, str] = {
    "1": "+X",
    "2": "-X",
    "3": "+Y",
    "4": "-Y",
    "5": "+Z",
    "6": "-Z",
}
AXIS_VECTORS: dict[str, tuple[float, float, float]] = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}
DIRECTION_LABELS: dict[str, str] = {
    "+Z": "前",
    "-Z": "後",
    "+X": "右",
    "-X": "左",
    "+Y": "上",
    "-Y": "下",
}
DIRECTION_COLORS: dict[str, tuple[int, int, int]] = {
    "+Z": (255, 205, 70),
    "-Z": (150, 105, 35),
    "+X": (245, 95, 95),
    "-X": (145, 55, 55),
    "+Y": (95, 245, 135),
    "-Y": (45, 135, 75),
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT_DEFAULT = REPOSITORY_ROOT / "遊戲3d"
OUTPUT_DEFAULT = REPOSITORY_ROOT / "assets/air_defense/models/asset_axis_calibration.json"


@dataclass
class MarkedAxes:
    source_forward: Optional[str] = None
    source_up: Optional[str] = None


def _cross(first: tuple[float, float, float], second: tuple[float, float, float]):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _subtract(first: tuple[float, float, float], second: tuple[float, float, float]):
    return tuple(left - right for left, right in zip(first, second))


def _unit(vector: tuple[float, float, float]):
    length = sqrt(sum(component * component for component in vector))
    if length <= 1e-12 or not isfinite(length):
        return (0.0, 1.0, 0.0)
    return tuple(component / length for component in vector)


def _axis_matrix(source_forward: Optional[str], source_up: Optional[str]):
    """Derive canonical rows from the marked source forward/up directions."""

    if source_forward not in AXIS_VECTORS or source_up not in AXIS_VECTORS:
        return None
    forward = AXIS_VECTORS[source_forward]
    up = AXIS_VECTORS[source_up]
    right = _cross(up, forward)
    if sum(abs(value) for value in right) != 1.0:
        return None
    return [
        [int(value) for value in right],
        [int(value) for value in up],
        [int(value) for value in forward],
    ]


def _source_mesh(facets: tuple[STLFacet, ...]) -> Mesh:
    """Build a centered, uniformly fitted mesh without applying any axis map."""

    points = [point for facet in facets for point in facet.vertices]
    center = tuple(
        (min(point[index] for point in points) + max(point[index] for point in points)) / 2.0
        for index in range(3)
    )
    extent = max(
        max(point[index] for point in points) - min(point[index] for point in points)
        for index in range(3)
    )
    if extent <= 1e-12 or not isfinite(extent):
        raise ValueError("模型包絡無法顯示")

    vertices: list[tuple[float, float, float]] = []
    normals: list[tuple[float, float, float]] = []
    triangles: list[tuple[int, int, int]] = []
    for facet in facets:
        fitted = tuple(
            tuple((point[index] - center[index]) * 6.0 / extent for index in range(3))
            for point in facet.vertices
        )
        normal = _unit(_cross(_subtract(fitted[1], fitted[0]), _subtract(fitted[2], fitted[0])))
        first = len(vertices)
        vertices.extend(fitted)
        normals.extend((normal, normal, normal))
        triangles.append((first, first + 1, first + 2))
    return Mesh(vertices=vertices, triangles=triangles, normals=normals, static=True)


def _axis_rotation(direction: str) -> tuple[float, float, float]:
    if direction == "+X":
        return (0.0, 90.0, 0.0)
    if direction == "-X":
        return (0.0, -90.0, 0.0)
    if direction == "+Y":
        return (-90.0, 0.0, 0.0)
    if direction == "-Y":
        return (90.0, 0.0, 0.0)
    if direction == "-Z":
        return (0.0, 180.0, 0.0)
    return (0.0, 0.0, 0.0)


class AxisCalibrationViewer:
    def __init__(self, source_root: Path, output_path: Path, start_asset: Optional[str] = None) -> None:
        self.source_root = source_root.resolve()
        self.output_path = output_path.resolve()
        self.specs = tuple(ASSET_SPECS)
        self.marked = self._read_existing()
        self.asset_index = 0
        if start_asset:
            for index, spec in enumerate(self.specs):
                if spec.asset_id == start_asset:
                    self.asset_index = index
                    break
        self.mode = "forward"
        self.model_entity: Optional[Entity] = None
        self.axis_root: Optional[Entity] = None
        self.forward_marker: Optional[Entity] = None
        self.up_marker: Optional[Entity] = None
        self.editor_camera = EditorCamera()
        camera.position = (0.0, 1.5, -10.0)
        camera.rotation = (8.0, 0.0, 0.0)
        window.title = "3D asset axis calibration"
        self.title = Text(parent=camera.ui, origin=(-0.5, 0), x=-0.86, y=0.45, scale=1.0)
        self.instructions = Text(parent=camera.ui, origin=(-0.5, 0), x=-0.86, y=0.39, scale=0.62)
        self.status = Text(parent=camera.ui, origin=(-0.5, 0), x=-0.86, y=0.32, scale=0.72, color=color.rgb32(255, 220, 120))
        self.message = Text(parent=camera.ui, origin=(-0.5, 0), x=-0.86, y=-0.43, scale=0.62, color=color.rgb32(120, 220, 255))
        self.help = Text(
            parent=camera.ui,
            origin=(-0.5, 0),
            x=-0.86,
            y=-0.49,
            scale=0.50,
            text="方向線：前(+Z) 後(-Z) 右(+X) 左(-X) 上(+Y) 下(-Y) | 黃箭頭:前方 青箭頭:上方 | 1:+X 2:-X 3:+Y 4:-Y 5:+Z 6:-Z | F/U | Enter:下一個 | N/P | R | Esc:儲存離開",
        )
        self.show_asset()

    @property
    def spec(self):
        return self.specs[self.asset_index]

    @property
    def current_mark(self) -> MarkedAxes:
        return self.marked.setdefault(self.spec.asset_id, MarkedAxes())

    def _read_existing(self) -> dict[str, MarkedAxes]:
        try:
            data = json.loads(self.output_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        result: dict[str, MarkedAxes] = {}
        for asset_id, raw in data.get("assets", {}).items():
            if not isinstance(raw, dict):
                continue
            result[str(asset_id)] = MarkedAxes(
                source_forward=raw.get("source_forward"),
                source_up=raw.get("source_up"),
            )
        return result

    def _write(self) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "canonical": {"up": "+Y", "forward": "+Z"},
            "assets": {
                spec.asset_id: {
                    "source_file": spec.source_file,
                    "source_forward": self.marked.get(spec.asset_id, MarkedAxes()).source_forward,
                    "source_up": self.marked.get(spec.asset_id, MarkedAxes()).source_up,
                    "source_to_canonical": _axis_matrix(
                        self.marked.get(spec.asset_id, MarkedAxes()).source_forward,
                        self.marked.get(spec.asset_id, MarkedAxes()).source_up,
                    ),
                }
                for spec in self.specs
            },
        }
        self.output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _clear_visuals(self) -> None:
        for entity in (self.model_entity, self.axis_root, self.forward_marker, self.up_marker):
            if entity is not None:
                destroy(entity)
        self.model_entity = None
        self.axis_root = None
        self.forward_marker = None
        self.up_marker = None

    def show_asset(self) -> None:
        self._clear_visuals()
        self.message.text = ""
        source_path = self.source_root / self.spec.source_file
        self.title.text = f"{self.asset_index + 1}/{len(self.specs)}  {self.spec.asset_id}  ({self.spec.source_file})"
        try:
            facets = parse_stl(source_path.read_bytes())
            self.model_entity = Entity(model=_source_mesh(facets), color=color.rgb32(180, 190, 205))
        except (OSError, ValueError, UnicodeError) as exc:
            self.message.text = f"無法顯示：{exc}"
        self._build_axes()
        self._refresh_text()

    def _build_axes(self) -> None:
        self.axis_root = Entity()
        axis_length = 6.2
        for direction in ("+Z", "-Z", "+X", "-X", "+Y", "-Y"):
            vector = AXIS_VECTORS[direction]
            rgb = DIRECTION_COLORS[direction]
            scale = (
                (axis_length, 0.025, 0.025)
                if vector[0]
                else (0.025, axis_length, 0.025)
                if vector[1]
                else (0.025, 0.025, axis_length)
            )
            Entity(
                parent=self.axis_root,
                model="cube",
                position=tuple(component * axis_length / 2.0 for component in vector),
                scale=scale,
                color=color.rgb32(*rgb),
            )
            Entity(
                parent=self.axis_root,
                model="cube",
                position=tuple(component * (axis_length - 0.35) for component in vector),
                scale=(0.16, 0.16, 0.70),
                rotation=_axis_rotation(direction),
                color=color.rgb32(*rgb),
            )
            Text(
                parent=self.axis_root,
                text=f"{DIRECTION_LABELS[direction]}\n{direction}",
                position=tuple(component * (axis_length * 0.63) for component in vector),
                origin=(0, 0),
                scale=0.55,
                billboard=True,
                color=color.rgb32(*rgb),
            )
        self._refresh_markers()

    def _make_marker(self, direction: Optional[str], tint):
        if direction not in AXIS_VECTORS:
            return None
        vector = AXIS_VECTORS[direction]
        root = Entity()
        rotation = _axis_rotation(direction)
        Entity(
            parent=root,
            model="cube",
            position=tuple(component * 1.65 for component in vector),
            scale=(0.12, 0.12, 3.3),
            rotation=rotation,
            color=tint,
        )
        Entity(
            parent=root,
            # ``cone`` is not shipped by every Ursina asset bundle; a short
            # cube tip keeps the direction marker visible on those installs.
            model="cube",
            position=tuple(component * 3.25 for component in vector),
            scale=(0.34, 0.34, 0.62),
            rotation=rotation,
            color=tint,
        )
        return root

    def _refresh_markers(self) -> None:
        for marker in (self.forward_marker, self.up_marker):
            if marker is not None:
                destroy(marker)
        self.forward_marker = self._make_marker(self.current_mark.source_forward, color.rgb32(255, 220, 70))
        self.up_marker = self._make_marker(self.current_mark.source_up, color.rgb32(80, 255, 230))

    def _refresh_text(self) -> None:
        mark = self.current_mark
        self.instructions.text = (
            "目前選擇前方；按 U 改選上方。飛機請選螺旋槳／機鼻側；人物請選有臉的一側。"
            "以青色箭頭標記人物腳到頭的向上方向。滑鼠可旋轉視角。"
            if self.mode == "forward"
            else "目前選擇上方；按 F 改選前方。人物請選腳到頭的方向；黃色箭頭是螺旋槳／臉部側。"
        )
        self.status.text = (
            f"前方: {mark.source_forward or '未選'}    上方: {mark.source_up or '未選'}    "
            f"模式: {'前方' if self.mode == 'forward' else '上方'}"
        )

    def _set_axis(self, direction: str) -> None:
        if self.mode == "forward":
            self.current_mark.source_forward = direction
        else:
            self.current_mark.source_up = direction
        self._write()
        self._refresh_markers()
        self._refresh_text()

    def _next(self, step: int = 1) -> None:
        self.asset_index = (self.asset_index + step) % len(self.specs)
        self.mode = "forward"
        self.show_asset()

    def _complete(self) -> bool:
        return all(
            self.marked.get(spec.asset_id, MarkedAxes()).source_forward in AXIS_VECTORS
            and self.marked.get(spec.asset_id, MarkedAxes()).source_up in AXIS_VECTORS
            for spec in self.specs
        )

    def input(self, key: str) -> None:
        if key in AXIS_KEYS:
            self._set_axis(AXIS_KEYS[key])
        elif key.lower() == "f":
            self.mode = "forward"
            self._refresh_text()
        elif key.lower() == "u":
            self.mode = "up"
            self._refresh_text()
        elif key.lower() == "n":
            self._next()
        elif key.lower() == "p":
            self._next(-1)
        elif key.lower() == "r":
            self.marked[self.spec.asset_id] = MarkedAxes()
            self._write()
            self._refresh_markers()
            self._refresh_text()
        elif key == "enter":
            if self.current_mark.source_forward not in AXIS_VECTORS or self.current_mark.source_up not in AXIS_VECTORS:
                self.message.text = "請先選擇前方與上方；前方與上方不可是同一軸。"
                return
            if self.current_mark.source_forward.lstrip("+-") == self.current_mark.source_up.lstrip("+-"):
                self.message.text = "前方與上方必須使用不同軸，請重新選擇。"
                return
            self._write()
            if self.asset_index + 1 >= len(self.specs):
                self.message.text = "已完成所有模型；結果已寫入校正 JSON。"
                if self._complete():
                    application.quit()
            else:
                self._next()
        elif key in {"escape", "q"}:
            self._write()
            application.quit()


_VIEWER: Optional[AxisCalibrationViewer] = None


def input(key: str) -> None:
    if _VIEWER is not None:
        _VIEWER.input(key)


def _configure_ui_font() -> None:
    """Prefer an installed Traditional Chinese font for the calibration UI."""

    candidates = (
        Path("C:/Windows/Fonts/NotoSansTC-VF.ttf"),
        Path("C:/Windows/Fonts/kaiu.ttf"),
        Path(application.internal_fonts_folder) / "OpenSans-Regular.ttf",
    )
    for candidate in candidates:
        if candidate.is_file():
            application.fonts_folder = candidate.parent
            Text.default_font = candidate.name
            return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT_DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--asset", help="從指定 asset_id 開始")
    args = parser.parse_args()

    global _VIEWER
    # Ursina 8.3.0 still builds the optional editor toolbar during window
    # construction.  The packaged install may not contain cog.png, so keep
    # the hidden container expected by its aspect-ratio callback and skip the
    # editor-only widgets just like the game application does.
    original_make_editor_gui = window.make_editor_gui

    def make_disabled_editor_gui() -> None:
        window.editor_ui = Entity(parent=camera.ui, eternal=True, enabled=False)

    window.make_editor_gui = make_disabled_editor_gui
    try:
        app = Ursina(
            title="3D asset axis calibration",
            fullscreen=False,
            development_mode=False,
            editor_ui_enabled=False,
        )
    finally:
        window.make_editor_gui = original_make_editor_gui
    _configure_ui_font()
    _VIEWER = AxisCalibrationViewer(args.source_root, args.output, args.asset)
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
