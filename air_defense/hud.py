"""Ursina HUD and menu adapter."""

from __future__ import annotations

from typing import Callable, Optional

from ursina import Button, Entity, Text, camera, color, window
from ursina.models.procedural.circle import Circle
from ursina.models.procedural.quad import Quad

from . import config
from .rules import (
    CityStatusView,
    PlayerStatusView,
    WaveStatusView,
    WeaponCooldownView,
    build_city_status_view,
    build_player_status_view,
    lock_status_label,
    reticle_position_for_progress,
)
from .state import (
    AircraftType,
    FailureReason,
    GamePhase,
    LockState,
    SessionStats,
    WeaponKind,
)


def _rgb(values: tuple[float, float, float]):
    return color.rgb(*values)


# The default Ursina font is Latin-only.  Use the installed Traditional
# Chinese font for every HUD label so glyphs are real characters rather than
# missing-glyph boxes or invisible fallback nodes.
Text.default_font = config.HUD_FONT


class GameHUD:
    """Owns screen-space labels and the color-plus-text lock contract."""

    def __init__(self) -> None:
        self.root = Entity(parent=camera.ui)
        self.gameplay_root = Entity(parent=self.root, enabled=False)
        self.menu_root = Entity(parent=self.root, enabled=False)
        self.game_over_root = Entity(parent=self.root, enabled=False)
        self.victory_root = Entity(parent=self.root, enabled=False)

        self.lock_frame = self._make_reticle(self.gameplay_root)
        self.lock_ring = self._make_tracking_ring(self.gameplay_root)
        self.lock_reticle = self._make_crosshair(self.gameplay_root, 0.032)
        self.sniper_crosshair = self._make_crosshair(self.gameplay_root, 0.07)
        self.pistol_reticle = self._make_crosshair(self.gameplay_root, 0.035)
        self.scope_overlay = self._make_scope_overlay(self.gameplay_root)
        self.lock_frame.enabled = False
        self.lock_ring.enabled = False
        self.lock_reticle.enabled = False
        self.sniper_crosshair.enabled = False
        self.pistol_reticle.enabled = False
        self.lock_label = self._text(
            parent=self.gameplay_root,
            text="未鎖定",
            origin=(0, 0),
            y=-0.12,
            scale=0.9,
            color=_rgb(config.WHITE_RGB),
        )
        self.lock_percent_text = self._text(
            self.gameplay_root,
            "鎖定 0%",
            x=0,
            y=-0.155,
            origin=(0, 0),
            scale=0.68,
            color=_rgb(config.WHITE_RGB),
        )
        self.lock_bar_background = Entity(
            parent=self.gameplay_root,
            model="quad",
            x=0,
            y=-0.19,
            scale=(config.AA_LOCK_PROGRESS_BAR_WIDTH, config.AA_LOCK_PROGRESS_BAR_HEIGHT),
            color=color.rgba32(255, 255, 255, 0),
        )
        self.lock_bar_fill = Entity(
            parent=self.gameplay_root,
            model="quad",
            x=-config.AA_LOCK_PROGRESS_BAR_WIDTH / 2.0,
            y=-0.19,
            scale=(0.0, config.AA_LOCK_PROGRESS_BAR_HEIGHT),
            origin=(-0.5, 0),
            color=_rgb(config.RED_RGB),
        )
        self.cooldown_bar_background = Entity(
            parent=self.gameplay_root,
            model="quad",
            x=0,
            y=config.HUD_CD_BAR_Y,
            scale=(config.HUD_CD_BAR_WIDTH, config.HUD_CD_BAR_HEIGHT),
            color=color.rgba32(255, 255, 255, 0),
        )
        self.cooldown_bar_fill = Entity(
            parent=self.gameplay_root,
            model="quad",
            x=-config.HUD_CD_BAR_WIDTH / 2.0,
            y=config.HUD_CD_BAR_Y,
            scale=(0.0, config.HUD_CD_BAR_HEIGHT),
            origin=(-0.5, 0),
            color=_rgb(config.GREEN_RGB),
        )
        self.cooldown_text = self._text(
            self.gameplay_root,
            "",
            x=0,
            y=config.HUD_CD_BAR_Y - 0.025,
            origin=(0, 0),
            scale=0.52,
            color=_rgb(config.WHITE_RGB),
        )
        self.lock_percent_text.enabled = False
        self.lock_bar_background.enabled = False
        self.lock_bar_fill.enabled = False
        self.cooldown_bar_background.enabled = False
        self.cooldown_bar_fill.enabled = False
        self.cooldown_text.enabled = False
        self.health_text = self._text(self.gameplay_root, "生命值: 100", x=-0.86, y=0.45)
        self.city_text = self._text(self.gameplay_root, "城市耐久: 100", x=-0.86, y=0.405, scale=0.82)
        self.wave_text = self._text(self.gameplay_root, "第 1 波", x=0.72, y=0.39, scale=0.9)
        self.progress_text = self._text(self.gameplay_root, "敵機 -- / --", x=0.72, y=0.345, scale=0.78)
        self.aircraft_type_text = self._text(self.gameplay_root, "敵機: --", x=0.72, y=0.305, scale=0.75)
        self.boss_health_text = self._text(
            self.gameplay_root,
            "",
            x=0,
            y=0.27,
            origin=(0, 0),
            scale=1.0,
            color=_rgb(config.ORANGE_RGB),
        )
        self.stats_text = self._text(
            self.gameplay_root,
            "",
            x=0,
            y=0.46,
            origin=(0, 0),
            scale=0.58,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.fps_text = self._text(
            self.gameplay_root,
            "",
            x=0,
            y=0.425,
            origin=(0, 0),
            scale=0.54,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.weapon_text = self._text(
            self.gameplay_root,
            "武器: 空手",
            x=-0.68,
            y=-0.43,
            scale=0.72,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.inventory_slots = self._build_inventory()
        self.warning_text = self._text(
            self.gameplay_root,
            "",
            x=0,
            y=0.34,
            origin=(0, 0),
            scale=1.15,
            color=_rgb(config.YELLOW_RGB),
        )
        self.prompt_text = self._text(
            self.gameplay_root,
            "",
            x=0,
            y=-0.27,
            origin=(0, 0),
            scale=0.9,
            color=_rgb(config.CYAN_RGB),
        )
        self.scope_text = self._text(
            self.gameplay_root,
            "",
            x=0,
            y=-0.13,
            origin=(0, 0),
            scale=0.8,
            color=_rgb(config.GREEN_RGB),
        )
        self.hit_text = self._text(
            self.gameplay_root,
            "",
            x=0,
            y=0.25,
            origin=(0, 0),
            scale=0.9,
            color=_rgb(config.GREEN_RGB),
        )

        self._build_status_cards()

        self._build_menu()
        self._build_game_over()
        self._build_victory()

    def _build_status_cards(self) -> None:
        """Build the two responsive status cards from procedural primitives."""

        width = config.HUD_STATUS_CARD_WIDTH
        height = config.HUD_STATUS_CARD_HEIGHT
        card_model = Quad(
            radius=0.08,
            segments=8,
            aspect=width / height,
        )

        def panel(parent: Entity) -> Entity:
            Entity(
                parent=parent,
                model=card_model,
                x=0.008,
                y=-0.008,
                scale=(width + 0.018, height + 0.018),
                z=0.04,
                color=color.rgba32(0, 0, 0, 0),
            )
            border = Entity(
                parent=parent,
                model=card_model,
                scale=(width + config.HUD_STATUS_CARD_BORDER, height + config.HUD_STATUS_CARD_BORDER),
                z=0.03,
                color=color.rgba32(255, 255, 255, 150),
            )
            body = Entity(
                parent=parent,
                model=card_model,
                scale=(width, height),
                z=0.02,
                color=color.rgba32(255, 255, 255, 0),
            )
            return body

        self.player_card = Entity(
            parent=self.gameplay_root,
            x=0,
            y=0,
        )
        self.player_card_background = panel(self.player_card)
        self.player_card_icon = self._text(
            parent=self.player_card,
            text="♥",
            origin=(0, 0),
            x=-0.15,
            y=0.095,
            scale=1.5,
            color=_rgb(config.RED_RGB),
        )
        self.player_card_value = self._text(
            parent=self.player_card,
            text="100 / 100",
            origin=(-0.5, 0),
            x=-0.10,
            y=0.091,
            scale=0.90,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.player_bar_background = Entity(
            parent=self.player_card,
            model="quad",
            x=-0.10,
            y=0.052,
            origin=(-0.5, 0),
            scale=(config.HUD_CARD_BAR_WIDTH, config.HUD_CARD_BAR_HEIGHT),
            z=-0.01,
            color=color.rgba32(255, 255, 255, 0),
        )
        self.player_bar_fill = Entity(
            parent=self.player_card,
            model="quad",
            x=-0.10,
            y=0.052,
            origin=(-0.5, 0),
            scale=(config.HUD_CARD_BAR_WIDTH, config.HUD_CARD_BAR_HEIGHT),
            z=-0.02,
            color=_rgb(config.RED_RGB),
        )
        self.city_card_icon = self._text(
            parent=self.player_card,
            text="◆",
            origin=(0, 0),
            x=-0.15,
            y=-0.015,
            scale=1.02,
            color=_rgb(config.BLUE_RGB),
        )
        self.city_card_value = self._text(
            parent=self.player_card,
            text="城市耐久：100%",
            origin=(-0.5, 0),
            x=-0.10,
            y=-0.012,
            scale=0.70,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.city_bar_background = Entity(
            parent=self.player_card,
            model="quad",
            x=-0.10,
            y=-0.06,
            origin=(-0.5, 0),
            scale=(config.HUD_CARD_BAR_WIDTH, config.HUD_CARD_BAR_HEIGHT),
            z=-0.01,
            color=color.rgba32(255, 255, 255, 0),
        )
        self.city_bar_fill = Entity(
            parent=self.player_card,
            model="quad",
            x=-0.10,
            y=-0.06,
            origin=(-0.5, 0),
            scale=(config.HUD_CARD_BAR_WIDTH, config.HUD_CARD_BAR_HEIGHT),
            z=-0.02,
            color=_rgb(config.BLUE_RGB),
        )

        self.wave_card = Entity(
            parent=self.gameplay_root,
            x=0,
            y=0,
        )
        self.wave_card_background = panel(self.wave_card)
        self.wave_card_icon = self._make_flag_icon(self.wave_card)
        self.wave_card_title = self._text(
            parent=self.wave_card,
            text="第 1 波",
            origin=(-0.5, 0),
            x=-0.085,
            y=0.105,
            scale=0.82,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.wave_card_progress = self._text(
            parent=self.wave_card,
            text="敵機進度：0%",
            origin=(-0.5, 0),
            x=-0.085,
            y=0.07,
            scale=0.64,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.wave_bar_background = Entity(
            parent=self.wave_card,
            model="quad",
            x=-0.085,
            y=0.043,
            origin=(-0.5, 0),
            scale=(config.HUD_CARD_BAR_WIDTH, config.HUD_CARD_BAR_HEIGHT),
            z=-0.01,
            color=color.rgba32(255, 255, 255, 0),
        )
        self.wave_bar_fill = Entity(
            parent=self.wave_card,
            model="quad",
            x=-0.085,
            y=0.043,
            origin=(-0.5, 0),
            scale=(0.0, config.HUD_CARD_BAR_HEIGHT),
            z=-0.02,
            color=_rgb(config.BLUE_RGB),
        )
        self.wave_dots_root = Entity(parent=self.wave_card, x=-0.085, y=0.012)
        self.wave_card_type = self._text(
            parent=self.wave_card,
            text="敵機：快速・普通・Boss",
            origin=(-0.5, 0),
            x=-0.085,
            y=-0.072,
            scale=0.52,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.wave_card_target = self._text(
            parent=self.wave_card,
            text="鎖定：未選定",
            origin=(-0.5, 0),
            x=-0.085,
            y=-0.115,
            scale=0.5,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.wave_dot_entities: list[Entity] = []
        for _ in range(32):
            dot = Entity(
                parent=self.wave_dots_root,
                model=Circle(resolution=16, radius=0.5),
                scale=config.HUD_WAVE_DOT_SIZE,
                z=-0.02,
                color=_rgb(config.BLUE_RGB),
                enabled=False,
            )
            self.wave_dot_entities.append(dot)

        # Keep the legacy text attributes available for callers/tests, but
        # use the cards as the visible source of truth.
        for legacy_text in (
            self.health_text,
            self.city_text,
            self.wave_text,
            self.progress_text,
            self.aircraft_type_text,
        ):
            legacy_text.enabled = False
        self.stats_text.y = 0.46
        self.fps_text.y = 0.425
        self._layout_status_cards()

    def _layout_status_cards(self) -> None:
        """Keep both cards inside the current camera.ui viewport."""

        width = float(config.HUD_STATUS_CARD_WIDTH)
        height = float(config.HUD_STATUS_CARD_HEIGHT)
        margin_x = max(0.02, float(config.HUD_SAFE_MARGIN_X))
        margin_y = max(0.02, float(config.HUD_SAFE_MARGIN_Y))
        try:
            aspect = max(0.75, float(window.aspect_ratio))
        except (AttributeError, TypeError, ValueError):
            aspect = float(config.WINDOW_WIDTH) / float(config.WINDOW_HEIGHT)

        # On a very narrow viewport, shrink the card roots just enough to
        # preserve a visible center gap while retaining every label.
        center_gap = 0.08
        max_card_scale = (aspect - (2.0 * margin_x) - center_gap) / (2.0 * width)
        card_scale_x = min(1.0, max(0.72, max_card_scale))
        half_viewport = aspect / 2.0
        edge = half_viewport - margin_x
        half_card = width * card_scale_x / 2.0
        card_x = max(0.0, edge - half_card)
        card_y = 0.5 - margin_y - (height / 2.0)
        for card, x in ((self.player_card, -card_x), (self.wave_card, card_x)):
            card.x = x
            card.y = card_y
            card.scale_x = card_scale_x

    def update_status_cards(
        self,
        player_view: PlayerStatusView,
        city_view: CityStatusView,
        wave_view: WaveStatusView,
        *,
        visible: bool = True,
    ) -> None:
        """Update each card from independent clamped derived views."""

        self._layout_status_cards()
        for card in (self.player_card, self.wave_card):
            card.enabled = bool(visible)
        self.player_card_icon.color = _rgb(player_view.icon_color)
        self.player_card_value.text = f"{player_view.health} / {player_view.max_health}"
        self.player_bar_fill.scale_x = config.HUD_CARD_BAR_WIDTH * player_view.health_ratio
        self.city_card_icon.color = _rgb(city_view.icon_color)
        self.city_card_value.text = f"城市耐久：{city_view.percent}%"
        self.city_bar_fill.scale_x = config.HUD_CARD_BAR_WIDTH * city_view.health_ratio

        self.wave_card_title.text = f"第 {wave_view.wave_number} 波"
        # The dots already communicate the roster count.  Keep this label to
        # one short line so it cannot run past the card at small resolutions.
        self.wave_card_progress.text = f"敵機進度：{wave_view.aircraft_percent}%"
        self.wave_bar_fill.scale_x = config.HUD_CARD_BAR_WIDTH * wave_view.aircraft_ratio
        type_labels = wave_view.aircraft_type_labels
        self.wave_card_type.text = (
            f"敵機：{'・'.join(type_labels)}"
            if type_labels
            else "敵機：未選定"
        )
        selected_label = (
            wave_view.selected_type_label
            if wave_view.selected_aircraft_id is not None
            else "未選定"
        )
        self.wave_card_target.text = f"鎖定：{selected_label}"
        for index, dot in enumerate(self.wave_dot_entities):
            if index >= len(wave_view.dots):
                dot.enabled = False
                continue
            item = wave_view.dots[index]
            dot.enabled = bool(visible)
            dot.color = _rgb(item.color)
            dot.scale = wave_view.dot_size
            row = index // max(1, wave_view.dots_per_row)
            column = index % max(1, wave_view.dots_per_row)
            dot.x = column * (wave_view.dot_size + config.HUD_WAVE_DOT_GAP)
            dot.y = -row * (wave_view.dot_size + config.HUD_WAVE_DOT_GAP)

    def update_weapon_cooldown(
        self,
        view: Optional[WeaponCooldownView],
        *,
        visible: bool = True,
    ) -> None:
        enabled = bool(view is not None and visible and view.visible)
        self.cooldown_bar_background.enabled = enabled
        self.cooldown_bar_fill.enabled = enabled
        self.cooldown_text.enabled = enabled
        if view is None:
            self.cooldown_bar_fill.scale_x = 0.0
            self.cooldown_text.text = ""
            return
        self.cooldown_bar_fill.scale_x = config.HUD_CD_BAR_WIDTH * view.fill_ratio
        self.cooldown_bar_fill.color = _rgb(view.color)
        self.cooldown_text.text = (
            f"{view.weapon.value}  {view.remaining_seconds:.2f}s"
            if not view.ready
            else "READY"
        )

    @staticmethod
    def _text(parent: Entity, text: str, **kwargs) -> Text:
        kwargs.setdefault("font", config.HUD_FONT)
        scale = kwargs.get("scale", 1.0)
        if isinstance(scale, (int, float)):
            kwargs["scale"] = float(scale) * config.HUD_FONT_SCALE
        # UI camera depth uses smaller z values as the foreground.  Keeping
        # labels in front of the card body avoids washed-out/occluded text.
        kwargs.setdefault("z", -0.04)
        return Text(parent=parent, text=text, **kwargs)

    @staticmethod
    def _make_flag_icon(parent: Entity) -> Entity:
        """Build a flag from ASCII-safe primitives instead of a missing glyph."""

        root = Entity(parent=parent, x=-0.15, y=0.105, z=-0.04)
        icon_color = _rgb(config.HUD_TEXT_RGB)
        Entity(
            parent=root,
            model="quad",
            x=-0.012,
            scale=(0.004, 0.046),
            color=icon_color,
        )
        Entity(
            parent=root,
            model="quad",
            x=0.008,
            y=0.012,
            scale=(0.034, 0.019),
            color=icon_color,
        )
        return root

    @staticmethod
    def _make_reticle(parent: Entity) -> Entity:
        root = Entity(parent=parent)
        line_color = _rgb(config.WHITE_RGB)
        size = config.AA_LOCK_FRAME_SIZE
        half = size / 2.0
        thickness = 0.004
        Entity(parent=root, model="quad", scale=(size, thickness), y=half, color=line_color)
        Entity(parent=root, model="quad", scale=(size, thickness), y=-half, color=line_color)
        Entity(parent=root, model="quad", scale=(thickness, size), x=-half, color=line_color)
        Entity(parent=root, model="quad", scale=(thickness, size), x=half, color=line_color)
        return root

    @staticmethod
    def _make_tracking_ring(parent: Entity) -> Entity:
        """Build one continuous ordinary circle, without segmented tick marks."""

        root = Entity(parent=parent, enabled=False)
        root.model = Circle(
            resolution=64,
            radius=config.AA_LOCK_RING_ACQUISITION_RADIUS,
            mode="line",
            thickness=2.0,
        )
        root.color = _rgb(config.RED_RGB)
        return root

    @staticmethod
    def _make_crosshair(parent: Entity, size: float) -> Entity:
        root = Entity(parent=parent)
        line_color = _rgb(config.CYAN_RGB)
        Entity(parent=root, model="quad", scale=(size, 0.0025), color=line_color)
        Entity(parent=root, model="quad", scale=(0.0025, size), color=line_color)
        Entity(parent=root, model="quad", scale=(0.008, 0.008), color=line_color)
        root.enabled = False
        return root

    @staticmethod
    def _set_reticle_color(reticle: Entity, tint) -> None:
        """Apply a lock-state color to the visible crosshair segments."""

        reticle.color = tint
        for child in reticle.children:
            child.color = tint

    @staticmethod
    def _make_scope_overlay(parent: Entity) -> Entity:
        root = Entity(parent=parent, enabled=False)
        root.scope_visual = "circular"
        root.checkerboard = False
        root.scope_fov = config.CAMERA_SCOPE_FOV
        overlay_color = color.rgba32(0, 0, 0, 220)
        # Corner panels leave a circular viewing aperture in the centre.
        Entity(parent=root, model="quad", scale=(2.0, 0.22), y=0.90, color=overlay_color)
        Entity(parent=root, model="quad", scale=(2.0, 0.22), y=-0.90, color=overlay_color)
        Entity(parent=root, model="quad", scale=(0.22, 1.58), x=-0.90, color=overlay_color)
        Entity(parent=root, model="quad", scale=(0.22, 1.58), x=0.90, color=overlay_color)
        Entity(
            parent=root,
            model=Circle(resolution=96, radius=0.72, mode="line", thickness=2.5),
            color=_rgb(config.WHITE_RGB),
        )
        Entity(parent=root, model="quad", scale=(0.34, 0.0025), color=_rgb(config.RED_RGB))
        Entity(parent=root, model="quad", scale=(0.0025, 0.34), color=_rgb(config.RED_RGB))
        Entity(parent=root, model="quad", scale=(0.012, 0.012), color=_rgb(config.RED_RGB))
        return root

    def _build_inventory(self) -> dict[WeaponKind, dict[str, Entity | Text]]:
        """Build the always-visible three-slot weapon inventory bar."""

        self._text(
            parent=self.gameplay_root,
            text="物品欄（數字鍵切換）",
            origin=(0, 0),
            x=0,
            y=-0.375,
            scale=0.62,
            color=_rgb(config.CYAN_RGB),
        )
        slots: dict[WeaponKind, dict[str, Entity | Text]] = {}
        slot_specs = (
            (WeaponKind.ANTI_AIRCRAFT, "1", "防空炮", -0.21),
            (WeaponKind.SNIPER, "2", "狙擊槍", 0.0),
            (WeaponKind.PISTOL, "3", "手槍", 0.21),
        )
        for kind, key_label, item_label, x_position in slot_specs:
            root = Entity(parent=self.gameplay_root, x=x_position, y=-0.45)
            panel = Entity(
                parent=root,
                model="quad",
                scale=(0.18, 0.085),
                color=color.rgba32(255, 255, 255, 0),
            )
            key_text = self._text(
                parent=root,
                text=key_label,
                origin=(0, 0),
                x=-0.07,
                y=0,
                scale=0.72,
                color=_rgb(config.YELLOW_RGB),
            )
            name_text = self._text(
                parent=root,
                text=item_label,
                origin=(0, 0),
                x=0.025,
                y=0,
                scale=0.62,
                color=_rgb(config.WHITE_RGB),
            )
            slots[kind] = {"panel": panel, "key": key_text, "name": name_text}
        return slots

    def _build_menu(self) -> None:
        panel = Entity(
            parent=self.menu_root,
            model="quad",
            scale=(0.72, 0.7),
            color=color.rgba32(18, 25, 38, 235),
        )
        self._text(parent=self.menu_root, text="3D 防空守衛", origin=(0, 0), y=0.22, scale=2.0)
        self._text(
            parent=self.menu_root,
            text="守住大樓，完成固定 18 波戰役",
            origin=(0, 0),
            y=0.11,
            scale=0.85,
            color=_rgb(config.CYAN_RGB),
        )
        self.start_button = Button(parent=self.menu_root, text="開始遊戲", scale=(0.28, 0.075), y=-0.02)
        self.quit_button = Button(parent=self.menu_root, text="離開遊戲", scale=(0.28, 0.075), y=-0.13)

    def _build_game_over(self) -> None:
        Entity(
            parent=self.game_over_root,
            model="quad",
            scale=(0.78, 0.78),
            color=color.rgba32(20, 18, 25, 240),
        )
        self._text(parent=self.game_over_root, text="防守失敗", origin=(0, 0), y=0.25, scale=1.8)
        self.failure_text = self._text(parent=self.game_over_root, text="", origin=(0, 0), y=0.13, scale=1.0)
        self.final_stats_text = self._text(parent=self.game_over_root, text="", origin=(0, 0), y=0.0, scale=0.9)
        self.return_button = Button(
            parent=self.game_over_root,
            text="返回主選單",
            scale=(0.3, 0.075),
            y=-0.18,
        )

    def _build_victory(self) -> None:
        Entity(
            parent=self.victory_root,
            model="quad",
            scale=(0.78, 0.78),
            color=color.rgba32(14, 38, 35, 240),
        )
        self.victory_text = self._text(
            parent=self.victory_root,
            text="你贏了",
            origin=(0, 0),
            y=0.25,
            scale=1.8,
            color=_rgb(config.GREEN_RGB),
        )
        self.victory_stats_text = self._text(
            parent=self.victory_root,
            text="",
            origin=(0, 0),
            y=0.0,
            scale=0.9,
        )
        self.victory_return_button = Button(
            parent=self.victory_root,
            text="返回主選單",
            scale=(0.3, 0.075),
            y=-0.18,
        )

    def bind_menu_actions(self, start: Callable[[], None], quit_game: Callable[[], None]) -> None:
        self.start_button.on_click = start
        self.quit_button.on_click = quit_game

    def bind_return_action(self, callback: Callable[[], None]) -> None:
        self.return_button.on_click = callback
        self.victory_return_button.on_click = callback

    def show_main_menu(self) -> None:
        self.menu_root.enabled = True
        self.gameplay_root.enabled = False
        self.game_over_root.enabled = False
        if hasattr(self, "victory_root"):
            self.victory_root.enabled = False

    def show_gameplay(self) -> None:
        self.menu_root.enabled = False
        self.gameplay_root.enabled = True
        self.game_over_root.enabled = False
        if hasattr(self, "victory_root"):
            self.victory_root.enabled = False

    def show_game_over(self, stats: SessionStats) -> None:
        self.menu_root.enabled = False
        # Keep the final player/city/wave cards visible as a frozen snapshot.
        # Dynamic lock, cooldown and weapon reticle elements are hidden by the
        # GAME_OVER update path below.
        self.gameplay_root.enabled = True
        self.game_over_root.enabled = True
        if hasattr(self, "victory_root"):
            self.victory_root.enabled = False
        reason = {
            FailureReason.BUILDING_IMPACT: "飛機撞擊大樓",
            FailureReason.PLAYER_DEAD: "玩家生命值歸零",
            FailureReason.CITY_DESTROYED: "城市被摧毀",
        }.get(stats.failure_reason, "防守失敗")
        self.failure_text.text = reason
        self.final_stats_text.text = (
            f"存活時間 {stats.survival_seconds:.1f} 秒\n"
            f"擊落飛機 {stats.aircraft_destroyed}  架\n"
            f"擊倒敵人 {stats.enemies_defeated}  名"
        )

    def show_victory(self, stats: SessionStats) -> None:
        """Show a frozen final result without adding descent-specific HUD."""

        self.menu_root.enabled = False
        self.gameplay_root.enabled = True
        self.game_over_root.enabled = False
        self.victory_root.enabled = True
        self.victory_text.text = "你贏了"
        self.victory_stats_text.text = (
            f"存活時間 {stats.survival_seconds:.1f} 秒\n"
            f"擊落飛機 {stats.aircraft_destroyed}  架\n"
            f"擊倒敵人 {stats.enemies_defeated}  名"
        )

    def update_lock(
        self,
        state: LockState,
        visible: bool,
        *,
        active: bool = True,
        progress: float = 0.0,
        target_position: Optional[tuple[float, float]] = None,
        target_radius: float = 0.008,
        completion_flash: bool = False,
    ) -> None:
        self.lock_frame.enabled = active
        # The frame is a fixed white boundary. Target feedback belongs to the
        # separate small reticle and must never recolor this frame.
        self.lock_ring.enabled = False
        self.lock_reticle.enabled = active
        self.lock_label.enabled = active
        self.lock_percent_text.enabled = active
        self.lock_bar_background.enabled = active
        self.lock_bar_fill.enabled = active
        for child in self.lock_frame.children:
            child.color = _rgb(config.WHITE_RGB)
        if state == LockState.WHITE:
            tint = _rgb(config.WHITE_RGB)
        elif state == LockState.RED_TRACKING:
            tint = _rgb(config.RED_RGB) if visible else _rgb(config.WHITE_RGB)
        else:
            tint = _rgb(config.RED_RGB) if completion_flash else _rgb(config.GREEN_RGB)
        self._set_reticle_color(self.lock_reticle, tint)
        self.lock_label.text = lock_status_label(state)
        # Keep all lock labels readable in the transparent HUD; state color is
        # carried by the small reticle and bars instead of the text.
        self.lock_label.color = _rgb(config.WHITE_RGB)
        clamped_progress = max(0.0, min(1.0, float(progress)))
        self.lock_percent_text.text = f"鎖定 {clamped_progress * 100.0:.0f}%"
        self.lock_percent_text.color = _rgb(config.WHITE_RGB)
        self.lock_bar_fill.scale_x = config.AA_LOCK_PROGRESS_BAR_WIDTH * clamped_progress
        self.lock_bar_fill.color = tint
        frame_half = config.AA_LOCK_FRAME_SIZE / 2.0
        reticle_position = reticle_position_for_progress(
            (0.0, 0.0),
            (-frame_half, -frame_half, frame_half, frame_half),
            target_position,
            clamped_progress,
        )
        self.lock_reticle.position = reticle_position

    def update_reticle(
        self,
        weapon: Optional[WeaponKind],
        phase: GamePhase,
        *,
        scope_enabled: bool = False,
        anti_air_scope_enabled: bool = False,
    ) -> None:
        """Show exactly one weapon reticle family for the active phase/slot."""

        anti_air_equipped = (
            phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT)
            and weapon == WeaponKind.ANTI_AIRCRAFT
        )
        anti_air_scope_active = anti_air_equipped and anti_air_scope_enabled
        sniper_active = phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT) and weapon == WeaponKind.SNIPER
        pistol_active = phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT) and weapon == WeaponKind.PISTOL
        # The enlarged fixed frame remains visible while the anti-air weapon
        # is equipped; dynamic lock feedback is scope-only.
        self.lock_frame.enabled = anti_air_equipped
        self.lock_label.enabled = anti_air_scope_active
        self.lock_reticle.enabled = anti_air_scope_active
        self.sniper_crosshair.enabled = sniper_active
        self.pistol_reticle.enabled = pistol_active
        self.scope_overlay.enabled = sniper_active and scope_enabled

    def update_session(
        self,
        health: int,
        stats: SessionStats,
        weapon: Optional[WeaponKind],
        *,
        phase: GamePhase = GamePhase.MAIN_MENU,
        warning: bool = False,
        prompt: str = "",
        hit_feedback: str = "",
        scope_enabled: bool = False,
        anti_air_scope_enabled: bool = False,
        lock_state: LockState = LockState.WHITE,
        lock_visible: bool = True,
        lock_progress: float = 0.0,
        lock_target_position: Optional[tuple[float, float]] = None,
        lock_target_radius: float = 0.008,
        fps: Optional[float] = None,
        wave_number: Optional[int] = None,
        aircraft_index: Optional[int] = None,
        aircraft_count: Optional[int] = None,
        aircraft_type: Optional[AircraftType] = None,
        city_health: Optional[float] = None,
        boss_health: Optional[int] = None,
        boss_max_health: Optional[int] = None,
        boss_label: Optional[str] = None,
        player_view: Optional[PlayerStatusView] = None,
        city_view: Optional[CityStatusView] = None,
        wave_view: Optional[WaveStatusView] = None,
        cooldown_view: Optional[WeaponCooldownView] = None,
        lock_completion_flash: bool = False,
    ) -> None:
        weapon_name = {
            None: "空手",
            WeaponKind.ANTI_AIRCRAFT: "防空炮",
            WeaponKind.SNIPER: "狙擊槍",
            WeaponKind.PISTOL: "手槍",
        }[weapon]
        self.health_text.text = f"生命值: {health} / {config.PLAYER_MAX_HEALTH}"
        if city_health is not None:
            self.city_text.text = f"城市耐久: {max(0.0, city_health):.0f} / {config.CITY_MAX_HEALTH}"
        if wave_number is not None:
            self.wave_text.text = f"第 {wave_number} 波"
        if aircraft_index is not None and aircraft_count is not None:
            self.progress_text.text = f"敵機 {aircraft_index + 1} / {aircraft_count}"
        if aircraft_type is not None:
            type_name = {
                AircraftType.NORMAL: "普通",
                AircraftType.MANPOWER_SUPPORT: "人力支援",
                AircraftType.FAST: "快速",
                AircraftType.ARMORED_BOSS: "裝甲 Boss",
            }[AircraftType(aircraft_type)]
            self.aircraft_type_text.text = f"敵機: {type_name}"
        self.stats_text.text = (
            f"存活 {stats.survival_seconds:05.1f}s  "
            f"擊落 {stats.aircraft_destroyed}  "
            f"擊倒 {stats.enemies_defeated}"
        )
        self.weapon_text.text = f"武器: {weapon_name}"
        self.update_inventory(weapon, phase)
        self.fps_text.text = f"FPS: {fps:.0f}" if fps is not None else "FPS: --"
        self.warning_text.text = "空襲警告：戰鬥機接近目標" if warning else ""
        self.prompt_text.text = prompt
        self.hit_text.text = hit_feedback
        self.scope_text.text = "狙擊瞄準：右鍵關閉" if scope_enabled else ""
        self.update_boss_health(boss_health, boss_max_health, label=boss_label)
        if player_view is None:
            player_view = build_player_status_view(health, config.PLAYER_MAX_HEALTH)
        if city_view is None:
            city_view = build_city_status_view(
                city_health if city_health is not None else config.CITY_MAX_HEALTH,
                config.CITY_MAX_HEALTH,
            )
        if wave_view is None:
            # Legacy callers do not own a WaveRuntime; preserve their scalar
            # labels while still keeping the card widgets safe and hidden.
            wave_view = WaveStatusView(
                wave_number=wave_number or 1,
                aircraft_total=aircraft_count or 0,
                aircraft_alive=(
                    max(0, (aircraft_count or 0) - (aircraft_index or 0))
                    if aircraft_count is not None
                    else 0
                ),
                aircraft_ratio=(
                    max(0.0, min(1.0, float((aircraft_count or 0) - (aircraft_index or 0)) / float(aircraft_count)))
                    if aircraft_count
                    else 0.0
                ),
                aircraft_percent=(
                    int(round(max(0.0, min(1.0, float((aircraft_count or 0) - (aircraft_index or 0)) / float(aircraft_count))) * 100.0))
                    if aircraft_count
                    else 0
                ),
                dots=(),
                selected_aircraft_type=aircraft_type,
                selected_aircraft_id=None,
                selected_type_label="未選定",
                layout_rows=0,
                dots_per_row=0,
                dot_size=config.HUD_WAVE_DOT_SIZE,
            )
        self.update_status_cards(
            player_view,
            city_view,
            wave_view,
            visible=phase in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
                GamePhase.GAME_OVER,
                GamePhase.VICTORY,
            ),
        )
        self.update_weapon_cooldown(
            cooldown_view,
            visible=phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT),
        )
        self.update_lock(
            lock_state,
            lock_visible,
            active=anti_air_scope_enabled and phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT) and weapon == WeaponKind.ANTI_AIRCRAFT,
            progress=lock_progress,
            target_position=lock_target_position,
            target_radius=lock_target_radius,
            completion_flash=lock_completion_flash,
        )
        self.update_reticle(
            weapon,
            phase,
            scope_enabled=scope_enabled,
            anti_air_scope_enabled=anti_air_scope_enabled,
        )

    def update_boss_health(
        self,
        current: Optional[int],
        maximum: Optional[int],
        *,
        label: Optional[str] = None,
    ) -> None:
        if current is None or maximum is None:
            self.boss_health_text.text = ""
            return
        self.boss_health_text.text = f"{label or 'Boss HP'}: {current} / {maximum}"

    def update_inventory(
        self,
        selected_weapon: Optional[WeaponKind],
        phase: GamePhase,
    ) -> None:
        """Highlight the selected slot and dim the weapon for the other phase."""

        for kind, slot in self.inventory_slots.items():
            usable = (
                kind == WeaponKind.ANTI_AIRCRAFT and phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT)
            ) or (
                kind in (WeaponKind.SNIPER, WeaponKind.PISTOL)
                and phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
            )
            selected = kind == selected_weapon
            panel = slot["panel"]
            key_text = slot["key"]
            name_text = slot["name"]
            assert isinstance(panel, Entity)
            assert isinstance(key_text, Text)
            assert isinstance(name_text, Text)
            # Gameplay HUD backgrounds stay transparent; selection is shown
            # through the text colors instead of a filled inventory tile.
            panel.color = color.rgba32(255, 255, 255, 0)
            key_text.color = _rgb(config.YELLOW_RGB) if usable else color.rgba32(170, 170, 170, 170)
            name_text.color = (
                _rgb(config.GREEN_RGB)
                if selected
                else _rgb(config.WHITE_RGB)
                if usable
                else color.rgba32(170, 170, 170, 170)
            )
