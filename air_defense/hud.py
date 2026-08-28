"""Ursina HUD and menu adapter."""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from ursina import Button, Entity, Text, camera, color, window
from ursina.models.procedural.circle import Circle
from ursina.models.procedural.quad import Quad

from . import config
from .rules import (
    CityStatusView,
    MultiLockView,
    PlayerStatusView,
    WaveStatusView,
    WeaponCooldownView,
    build_city_status_view,
    build_player_status_view,
    lock_status_label,
    inventory_selection_allowed,
    reticle_position_for_progress,
    tracking_ring_radius,
)
from .save_data import SaveProfile, SaveLoadResult
from .progression import (
    LevelKey,
    calculate_rebirth_cost,
    effective_max_hp,
    effective_whitebox_scale,
    get_upgrade_level,
    price_for_upgrade,
    upgrade_catalog,
)
from .state import (
    AntiAirGuiMode,
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
        self.settings_root = Entity(parent=self.root, enabled=False)
        self.save_select_root = Entity(parent=self.root, enabled=False)
        self.shop_root = Entity(parent=self.root, enabled=False)
        self.game_over_root = Entity(parent=self.root, enabled=False)
        self.victory_root = Entity(parent=self.root, enabled=False)

        self.lock_frame = self._make_reticle(self.gameplay_root)
        self.lock_ring = self._make_tracking_ring(self.gameplay_root)
        self.lock_reticle = self._make_crosshair(self.gameplay_root, 0.032)
        self.sniper_crosshair = self._make_crosshair(self.gameplay_root, 0.07)
        normal_crosshair_size = 0.035
        self.pistol_reticle = self._make_crosshair(self.gameplay_root, normal_crosshair_size)
        # RPG deliberately uses the same geometry, size and color as the
        # pistol while remaining a separate family for exclusive visibility.
        self.rpg_reticle = self._make_crosshair(self.gameplay_root, normal_crosshair_size)
        self.multi_reticle_pool: dict[str, Entity] = {}
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
        self._build_settings()
        self._build_save_select()
        self._build_shop()
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
        self.wave_card_turrets = self._text(
            parent=self.wave_card,
            text="砲塔：--",
            origin=(-0.5, 0),
            x=-0.085,
            y=-0.15,
            scale=0.48,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.wave_dot_entities: list[Entity] = []
        for _ in range(32):
            self.wave_dot_entities.append(self._make_wave_dot())

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

    def _make_wave_dot(self) -> Entity:
        """建立一個敵機圓點；數量可隨 A 擴充，不受固定上限限制。"""

        return Entity(
            parent=self.wave_dots_root,
            model=Circle(resolution=16, radius=0.5),
            scale=config.HUD_WAVE_DOT_SIZE,
            z=-0.02,
            color=_rgb(config.BLUE_RGB),
            enabled=False,
        )

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
        while len(self.wave_dot_entities) < len(wave_view.dots):
            self.wave_dot_entities.append(self._make_wave_dot())
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

    def clear_transient_weapon_ui(self) -> None:
        """Hide weapon feedback without touching domain objects or missiles.

        Lifecycle boundaries call this small UI-only reset before changing the
        scene.  In particular, an already launched guided missile belongs to
        the game/session layer and must continue independently of this method.
        ``getattr`` keeps the helper safe for lightweight HUD doubles used by
        lifecycle tests and headless callers.
        """

        for widget_name in (
            "lock_frame",
            "lock_ring",
            "lock_reticle",
            "sniper_crosshair",
            "pistol_reticle",
            "rpg_reticle",
            "scope_overlay",
            "lock_label",
            "lock_percent_text",
            "lock_bar_background",
            "lock_bar_fill",
            "cooldown_bar_background",
            "cooldown_bar_fill",
            "cooldown_text",
        ):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.enabled = False
        for widget_name in ("lock_bar_fill", "cooldown_bar_fill"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.scale_x = 0.0
        cooldown_text = getattr(self, "cooldown_text", None)
        if cooldown_text is not None:
            cooldown_text.text = ""
        hit_text = getattr(self, "hit_text", None)
        if hit_text is not None:
            hit_text.text = ""
        pool = getattr(self, "multi_reticle_pool", None)
        if pool is not None:
            for reticle in pool.values():
                reticle.enabled = False
            pool.clear()

    def update_multi_lock_views(
        self,
        views: Iterable[MultiLockView],
        *,
        active: bool = True,
    ) -> None:
        """Render one reusable small reticle per current multi-lock target."""

        pool = getattr(self, "multi_reticle_pool", None)
        if pool is None:
            pool = {}
            self.multi_reticle_pool = pool
        current_ids: set[str] = set()
        state_colors = {
            LockState.WHITE: _rgb(config.WHITE_RGB),
            LockState.RED_TRACKING: _rgb(config.RED_RGB),
            LockState.GREEN_READY: _rgb(config.GREEN_RGB),
        }
        for view in views:
            target_id = str(view.target_id)
            current_ids.add(target_id)
            reticle = pool.get(target_id)
            if reticle is None:
                reticle = self._make_crosshair(self.gameplay_root, 0.032)
                pool[target_id] = reticle
            reticle.position = view.screen_position
            reticle.enabled = bool(active and view.visible)
            reticle.lock_progress = view.progress
            reticle.lock_state = view.state
            reticle.fireable = view.fireable
            self._set_reticle_color(reticle, state_colors[view.state])
        for target_id in tuple(pool):
            if target_id not in current_ids:
                pool[target_id].enabled = False
                pool.pop(target_id, None)

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
        """建立 1～5 武器槽位；未解鎖槽位仍保留可見但不可選。"""

        self._text(
            parent=self.gameplay_root,
            text="物品欄（數字鍵切換）",
            origin=(0, 0),
            x=0,
            y=-0.375,
            scale=0.62,
            color=_rgb(config.CYAN_RGB),
        )
        slots: dict[WeaponKind, dict[str, Entity | Text | str]] = {}
        slot_specs = (
            (WeaponKind.ANTI_AIRCRAFT, "1", "防空炮", -0.21),
            (WeaponKind.SNIPER, "2", "狙擊槍", 0.0),
            (WeaponKind.PISTOL, "3", "手槍", 0.21),
            (WeaponKind.RPG, "4", "RPG", 0.42),
            (WeaponKind.MULTI_ANTI_AIRCRAFT, "5", "多目標防空炮", 0.63),
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
            slots[kind] = {
                "panel": panel,
                "key": key_text,
                "name": name_text,
                "base_name": item_label,
            }
        return slots

    def _build_menu(self) -> None:
        panel = Entity(
            parent=self.menu_root,
            model="quad",
            scale=(0.74, 0.84),
            color=color.rgba32(18, 25, 38, 235),
        )
        self.menu_title = self._text(
            parent=self.menu_root,
            text="3D 防空守衛",
            origin=(0, 0),
            y=0.27,
            scale=2.0,
        )
        self.menu_profile_text = self._text(
            parent=self.menu_root,
            text="尚未載入存檔",
            origin=(0, 0),
            y=0.18,
            scale=0.68,
            color=_rgb(config.CYAN_RGB),
        )
        self.menu_subtitle = self._text(
            parent=self.menu_root,
            text="選擇功能後開始防守",
            origin=(0, 0),
            y=0.12,
            scale=0.85,
            color=_rgb(config.CYAN_RGB),
        )
        self.menu_rebirth_text = self._text(
            parent=self.menu_root,
            text="",
            origin=(0, 0),
            y=-0.31,
            scale=0.52,
            color=_rgb(config.YELLOW_RGB),
        )
        self.start_button = Button(parent=self.menu_root, text="開始遊戲", scale=(0.28, 0.075), y=0.03)
        self.shop_button = Button(parent=self.menu_root, text="升級商店", scale=(0.28, 0.075), y=-0.06)
        self.settings_button = Button(parent=self.menu_root, text="設定", scale=(0.28, 0.075), y=-0.15)
        self.rebirth_button = Button(parent=self.menu_root, text="重生", scale=(0.28, 0.075), y=-0.24)
        self.quit_button = Button(parent=self.menu_root, text="離開遊戲", scale=(0.28, 0.075), y=-0.39)

    def _build_settings(self) -> None:
        Entity(
            parent=self.settings_root,
            model="quad",
            scale=(0.78, 0.70),
            color=color.rgba32(18, 25, 38, 240),
        )
        self._text(
            parent=self.settings_root,
            text="設定",
            origin=(0, 0),
            y=0.24,
            scale=1.8,
        )
        self._text(
            parent=self.settings_root,
            text="防空武器瞄準介面",
            origin=(0, 0),
            y=0.15,
            scale=0.82,
            color=_rgb(config.CYAN_RGB),
        )
        self.settings_mode_text = self._text(
            parent=self.settings_root,
            text="目前：新版防空瞄準",
            origin=(0, 0),
            y=0.075,
            scale=0.72,
            color=_rgb(config.YELLOW_RGB),
        )
        self.settings_new_button = Button(
            parent=self.settings_root,
            text="新版防空瞄準",
            scale=(0.36, 0.075),
            y=-0.015,
        )
        self.settings_legacy_button = Button(
            parent=self.settings_root,
            text="舊版圓圈鎖定",
            scale=(0.36, 0.075),
            y=-0.115,
        )
        self._text(
            parent=self.settings_root,
            text="新版：白框與多目標小準心\n舊版：普通防空炮以圓圈鎖定飛機",
            origin=(0, 0),
            y=-0.215,
            scale=0.58,
            color=_rgb(config.HUD_TEXT_RGB),
        )
        self.settings_back_button = Button(
            parent=self.settings_root,
            text="返回主選單",
            scale=(0.30, 0.07),
            y=-0.315,
        )

    def _build_save_select(self) -> None:
        Entity(
            parent=self.save_select_root,
            model="quad",
            scale=(0.84, 0.78),
            color=color.rgba32(18, 25, 38, 240),
        )
        self._text(
            parent=self.save_select_root,
            text="選擇存檔",
            origin=(0, 0),
            y=0.27,
            scale=1.8,
        )
        self.save_select_hint = self._text(
            parent=self.save_select_root,
            text="可用滑鼠點擊 1～5 號存檔；右側刪除需再次確認",
            origin=(0, 0),
            y=0.18,
            scale=0.7,
            color=_rgb(config.CYAN_RGB),
        )
        self.save_slot_buttons: list[Button] = []
        self.save_delete_buttons: list[Button] = []
        for index in range(1, 6):
            row_y = 0.09 - (index - 1) * 0.09
            button = Button(
                parent=self.save_select_root,
                text=f"{index} 號存檔：空白",
                scale=(0.51, 0.065),
                x=-0.10,
                y=row_y,
            )
            self.save_slot_buttons.append(button)
            delete_button = Button(
                parent=self.save_select_root,
                text="刪除",
                scale=(0.15, 0.065),
                x=0.32,
                y=row_y,
                color=color.rgb(170, 70, 70),
                enabled=False,
            )
            self.save_delete_buttons.append(delete_button)
        self.pending_delete_slot: Optional[int] = None
        self.save_confirm_delete_button = Button(
            parent=self.save_select_root,
            text="確認刪除",
            scale=(0.19, 0.05),
            x=0.18,
            y=-0.355,
            enabled=False,
        )
        self.save_cancel_delete_button = Button(
            parent=self.save_select_root,
            text="取消",
            scale=(0.12, 0.05),
            x=0.38,
            y=-0.355,
            enabled=False,
        )
        self._delete_slot_callback: Optional[Callable[[int], None]] = None
        self.save_warning_text = self._text(
            parent=self.save_select_root,
            text="",
            origin=(0, 0),
            x=-0.20,
            y=-0.355,
            scale=0.48,
            color=_rgb(config.ORANGE_RGB),
        )

    def _build_shop(self) -> None:
        Entity(
            parent=self.shop_root,
            model="quad",
            scale=(0.92, 0.86),
            color=color.rgba32(18, 25, 38, 240),
        )
        self._text(
            parent=self.shop_root,
            text="升級商店",
            origin=(0, 0),
            y=0.34,
            scale=1.55,
        )
        self.shop_summary_text = self._text(
            parent=self.shop_root,
            text="",
            origin=(0, 0),
            y=0.26,
            scale=0.65,
            color=_rgb(config.CYAN_RGB),
        )
        self.shop_result_text = self._text(
            parent=self.shop_root,
            text="",
            origin=(0, 0),
            y=-0.27,
            scale=0.62,
            color=_rgb(config.YELLOW_RGB),
        )
        self.shop_upgrade_buttons: list[Button] = []
        for index, entry in enumerate(upgrade_catalog()):
            column = index % 2
            row = index // 2
            button = Button(
                parent=self.shop_root,
                text=f"{index + 1}{entry.label}",
                scale=(0.34, 0.052),
                x=-0.24 + column * 0.37,
                y=0.17 - row * 0.075,
            )
            self.shop_upgrade_buttons.append(button)
        self.shop_back_button = Button(
            parent=self.shop_root,
            text="返回主選單",
            scale=(0.28, 0.07),
            y=-0.36,
        )

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

    @staticmethod
    def _normalize_anti_air_gui_mode(mode: AntiAirGuiMode | str) -> AntiAirGuiMode:
        try:
            return mode if isinstance(mode, AntiAirGuiMode) else AntiAirGuiMode(mode)
        except (TypeError, ValueError):
            return AntiAirGuiMode.NEW

    def bind_menu_actions(
        self,
        start: Callable[[], None],
        quit_game: Callable[[], None],
        open_settings: Optional[Callable[[], None]] = None,
    ) -> None:
        self.start_button.on_click = start
        self.quit_button.on_click = quit_game
        if open_settings is not None:
            self.settings_button.on_click = open_settings

    def bind_settings_actions(
        self,
        set_mode: Callable[[AntiAirGuiMode], None],
        back_to_menu: Callable[[], None],
    ) -> None:
        self.settings_new_button.on_click = lambda: set_mode(AntiAirGuiMode.NEW)
        self.settings_legacy_button.on_click = lambda: set_mode(AntiAirGuiMode.LEGACY)
        self.settings_back_button.on_click = back_to_menu

    def bind_progression_actions(
        self,
        select_slot: Callable[[int], None],
        open_shop: Callable[[], None],
        rebirth: Callable[[], None],
        back_to_menu: Callable[[], None],
        purchase_upgrade: Optional[Callable[[str], None]] = None,
        delete_slot: Optional[Callable[[int], None]] = None,
    ) -> None:
        for index, button in enumerate(self.save_slot_buttons, start=1):
            button.on_click = lambda index=index: select_slot(index)
        self._delete_slot_callback = delete_slot
        for index, button in enumerate(self.save_delete_buttons, start=1):
            button.on_click = lambda index=index: self.request_delete_slot(index)
        self.save_confirm_delete_button.on_click = self.confirm_delete_slot
        self.save_cancel_delete_button.on_click = self.cancel_delete_slot
        self.shop_button.on_click = open_shop
        self.rebirth_button.on_click = rebirth
        self.shop_back_button.on_click = back_to_menu
        if purchase_upgrade is not None:
            for entry, button in zip(upgrade_catalog(), self.shop_upgrade_buttons):
                button.on_click = lambda entry=entry: purchase_upgrade(entry.upgrade_id)

    def request_delete_slot(self, slot_id: int) -> None:
        """第一階段只選取刪除目標，不執行破壞性操作。"""

        try:
            slot = int(slot_id)
        except (TypeError, ValueError):
            return
        if not 1 <= slot <= len(self.save_delete_buttons):
            return
        button = self.save_delete_buttons[slot - 1]
        if not button.enabled:
            return
        self.pending_delete_slot = slot
        self.save_confirm_delete_button.enabled = True
        self.save_cancel_delete_button.enabled = True
        self.save_confirm_delete_button.text = f"確認刪除 {slot} 號"
        self.save_warning_text.text = f"已選擇 {slot} 號存檔；請再按確認刪除。"

    def confirm_delete_slot(self) -> None:
        """第二階段才呼叫流程層刪除指定存檔。"""

        slot = self.pending_delete_slot
        callback = self._delete_slot_callback
        if slot is None or callback is None:
            return
        self._reset_delete_confirmation()
        callback(slot)

    def cancel_delete_slot(self) -> None:
        """取消目前的刪除確認，不修改任何存檔。"""

        self._reset_delete_confirmation()
        self.save_warning_text.text = ""

    def _reset_delete_confirmation(self) -> None:
        self.pending_delete_slot = None
        self.save_confirm_delete_button.enabled = False
        self.save_cancel_delete_button.enabled = False
        self.save_confirm_delete_button.text = "確認刪除"

    def update_profile_summary(
        self,
        profile: Optional[SaveProfile],
        *,
        save_results: Optional[tuple[SaveLoadResult, ...]] = None,
        warning: Optional[str] = None,
        shop_result: Optional[str] = None,
        next_level: Optional[LevelKey | str] = None,
    ) -> None:
        """更新選檔、主選單與商店共用的永久進度摘要。"""

        if save_results is not None:
            for index, button in enumerate(self.save_slot_buttons):
                result = save_results[index]
                if result.is_empty:
                    label = f"{index + 1} 號存檔：空白"
                else:
                    loaded = result.profile
                    label = (
                        f"{index + 1} 號存檔：{loaded.coins} 金幣／重生 {loaded.rebirth_count}／A {loaded.max_aircraft_count}"
                    )
                    if result.is_corrupt:
                        label += "（損壞，使用安全預設）"
                button.text = label
                if hasattr(self, "save_delete_buttons"):
                    delete_button = self.save_delete_buttons[index]
                    delete_button.enabled = not result.is_empty
                    if self.pending_delete_slot != index + 1:
                        delete_button.text = "刪除"
        if profile is None:
            summary = "尚未載入存檔"
        else:
            summary = (
                f"金幣 {profile.coins}｜重生 {profile.rebirth_count}｜A {profile.max_aircraft_count}｜"
                f"最近完成 {profile.last_completed_a_b or '無'}"
            )
            if next_level is not None:
                summary += f"｜下一關 {LevelKey.parse(next_level)}"
        self.menu_profile_text.text = summary
        self.shop_summary_text.text = summary
        self.save_warning_text.text = warning or ""
        if hasattr(self, "rebirth_button") and hasattr(self, "menu_rebirth_text"):
            if profile is None:
                self.rebirth_button.enabled = False
                self.menu_rebirth_text.text = "尚未載入存檔"
            else:
                rebirth_cost = calculate_rebirth_cost(
                    profile.rebirth_count,
                    config=profile.config,
                )
                can_rebirth = profile.rebirth_available and profile.coins >= rebirth_cost
                self.rebirth_button.enabled = can_rebirth
                if not profile.rebirth_available:
                    self.menu_rebirth_text.text = "重生資格：完成最終小關或死亡後開放"
                elif profile.coins < rebirth_cost:
                    self.menu_rebirth_text.text = (
                        f"重生資格已開放，費用 {rebirth_cost} 金幣（目前 {profile.coins}）"
                    )
                else:
                    self.menu_rebirth_text.text = f"重生資格已開放，費用 {rebirth_cost} 金幣"
        if shop_result is not None:
            self.shop_result_text.text = shop_result

    def update_shop_details(
        self,
        profile: Optional[SaveProfile],
        *,
        selected_upgrade: Optional[str] = None,
        result_message: Optional[str] = None,
    ) -> None:
        """刷新商店按鈕文字與結果提示；保留選取項目參數以相容既有呼叫端。"""

        if profile is None:
            if result_message is not None:
                self.shop_result_text.text = result_message
            return
        entries = upgrade_catalog(profile.config)
        buttons = getattr(self, "shop_upgrade_buttons", ())
        for index, entry in enumerate(entries, start=1):
            level = get_upgrade_level(profile, entry.upgrade_id)
            cap = profile.upgrade_caps.get(entry.upgrade_id, 1)
            price = price_for_upgrade(
                entry.upgrade_id,
                level,
                config=profile.config,
            )
            compact_text = f"{index}{entry.label}({level}/{cap}){price}元"
            if index <= len(buttons):
                buttons[index - 1].text = compact_text
        if result_message is not None:
            self.shop_result_text.text = result_message

    def bind_return_action(self, callback: Callable[[], None]) -> None:
        self.return_button.on_click = callback
        self.victory_return_button.on_click = callback

    def show_main_menu(self) -> None:
        self.menu_root.enabled = True
        self.gameplay_root.enabled = False
        if hasattr(self, "settings_root"):
            self.settings_root.enabled = False
        if hasattr(self, "save_select_root"):
            self.save_select_root.enabled = False
        if hasattr(self, "shop_root"):
            self.shop_root.enabled = False
        self.game_over_root.enabled = False
        if hasattr(self, "victory_root"):
            self.victory_root.enabled = False

    def show_gameplay(self) -> None:
        self.menu_root.enabled = False
        self.gameplay_root.enabled = True
        if hasattr(self, "settings_root"):
            self.settings_root.enabled = False
        if hasattr(self, "save_select_root"):
            self.save_select_root.enabled = False
        if hasattr(self, "shop_root"):
            self.shop_root.enabled = False
        self.game_over_root.enabled = False
        if hasattr(self, "victory_root"):
            self.victory_root.enabled = False

    def show_save_select(
        self,
        results: Optional[tuple[SaveLoadResult, ...]] = None,
        *,
        warning: Optional[str] = None,
    ) -> None:
        self.menu_root.enabled = False
        self.gameplay_root.enabled = False
        if hasattr(self, "settings_root"):
            self.settings_root.enabled = False
        self.save_select_root.enabled = True
        self.shop_root.enabled = False
        self.game_over_root.enabled = False
        if hasattr(self, "victory_root"):
            self.victory_root.enabled = False
        self._reset_delete_confirmation()
        if results is not None:
            self.update_profile_summary(None, save_results=results, warning=warning)

    def show_shop(self, profile: Optional[SaveProfile]) -> None:
        self.menu_root.enabled = False
        self.gameplay_root.enabled = False
        if hasattr(self, "settings_root"):
            self.settings_root.enabled = False
        self.save_select_root.enabled = False
        self.shop_root.enabled = True
        self.game_over_root.enabled = False
        if hasattr(self, "victory_root"):
            self.victory_root.enabled = False
        self.update_profile_summary(profile)
        self.update_shop_details(profile)

    def show_game_over(self, stats: SessionStats) -> None:
        self.menu_root.enabled = False
        if hasattr(self, "settings_root"):
            self.settings_root.enabled = False
        if hasattr(self, "save_select_root"):
            self.save_select_root.enabled = False
        if hasattr(self, "shop_root"):
            self.shop_root.enabled = False
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
        if hasattr(self, "settings_root"):
            self.settings_root.enabled = False
        if hasattr(self, "save_select_root"):
            self.save_select_root.enabled = False
        if hasattr(self, "shop_root"):
            self.shop_root.enabled = False
        self.gameplay_root.enabled = True
        self.game_over_root.enabled = False
        self.victory_root.enabled = True
        self.victory_text.text = "你贏了"
        self.victory_stats_text.text = (
            f"存活時間 {stats.survival_seconds:.1f} 秒\n"
            f"擊落飛機 {stats.aircraft_destroyed}  架\n"
            f"擊倒敵人 {stats.enemies_defeated}  名"
        )

    def show_settings(self, mode: AntiAirGuiMode | str = AntiAirGuiMode.NEW) -> None:
        """顯示防空介面選擇頁，不改變目前 Profile 或戰鬥狀態。"""

        self.menu_root.enabled = False
        self.gameplay_root.enabled = False
        if hasattr(self, "save_select_root"):
            self.save_select_root.enabled = False
        if hasattr(self, "shop_root"):
            self.shop_root.enabled = False
        self.game_over_root.enabled = False
        if hasattr(self, "victory_root"):
            self.victory_root.enabled = False
        self.settings_root.enabled = True
        self.update_settings_mode(mode)

    def update_settings_mode(self, mode: AntiAirGuiMode | str) -> None:
        """更新設定頁的選取狀態與按鈕提示。"""

        normalized = self._normalize_anti_air_gui_mode(mode)
        if not hasattr(self, "settings_mode_text"):
            return
        if normalized == AntiAirGuiMode.LEGACY:
            self.settings_mode_text.text = "目前：舊版圓圈鎖定"
        else:
            self.settings_mode_text.text = "目前：新版防空瞄準"
        selected_color = color.rgb(42, 112, 145)
        idle_color = color.rgb(42, 48, 60)
        if hasattr(self, "settings_new_button"):
            self.settings_new_button.color = (
                selected_color if normalized == AntiAirGuiMode.NEW else idle_color
            )
        if hasattr(self, "settings_legacy_button"):
            self.settings_legacy_button.color = (
                selected_color if normalized == AntiAirGuiMode.LEGACY else idle_color
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
        whitebox_scale: float = 1.0,
        anti_air_gui_mode: AntiAirGuiMode | str = AntiAirGuiMode.NEW,
    ) -> None:
        gui_mode = self._normalize_anti_air_gui_mode(anti_air_gui_mode)
        legacy_single_lock = gui_mode == AntiAirGuiMode.LEGACY
        whitebox_scale = max(0.1, float(whitebox_scale))
        clamped_progress = max(0.0, min(1.0, float(progress)))
        self.lock_frame.scale = whitebox_scale
        # The legacy presentation is the original 003 HUD: the enlarged
        # fixed frame stays visible together with the continuous follow ring.
        # The newer presentation reserves the fixed frame for its own reticle.
        self.lock_frame.enabled = bool(active)
        # New mode keeps the frame white; the legacy 003 mode colors the
        # original frame together with its tracking feedback.
        lock_ring = getattr(self, "lock_ring", None)
        if lock_ring is not None:
            lock_ring.enabled = bool(active and legacy_single_lock and target_position is not None)
            if target_position is not None:
                lock_ring.position = target_position
                radius = tracking_ring_radius(
                    config.AA_LOCK_RING_ACQUISITION_RADIUS,
                    target_radius,
                    clamped_progress,
                    padding=config.AA_LOCK_RING_PADDING,
                )
                base_radius = max(1e-6, config.AA_LOCK_RING_ACQUISITION_RADIUS)
                ratio = radius / base_radius
                lock_ring.scale = (ratio, ratio, 1.0)
            else:
                lock_ring.position = (0.0, 0.0)
                lock_ring.scale = (1.0, 1.0, 1.0)
        self.lock_reticle.enabled = bool(active and not legacy_single_lock)
        self.lock_label.enabled = active
        self.lock_percent_text.enabled = active
        self.lock_bar_background.enabled = active
        self.lock_bar_fill.enabled = active
        if state == LockState.WHITE:
            tint = _rgb(config.WHITE_RGB)
        elif state == LockState.RED_TRACKING:
            tint = (
                _rgb(config.RED_RGB)
                if visible
                else color.rgba(0, 0, 0, 0)
                if legacy_single_lock
                else _rgb(config.WHITE_RGB)
            )
        else:
            tint = _rgb(config.RED_RGB) if completion_flash else _rgb(config.GREEN_RGB)
        frame_tint = tint if legacy_single_lock else _rgb(config.WHITE_RGB)
        for child in getattr(self.lock_frame, "children", ()):
            child.color = frame_tint
        self._set_reticle_color(self.lock_reticle, tint)
        if lock_ring is not None:
            lock_ring.color = tint
        self.lock_label.text = lock_status_label(state)
        # Keep all lock labels readable in the transparent HUD; state color is
        # carried by the small reticle and bars instead of the text.
        self.lock_label.color = (
            _rgb(config.GREEN_RGB)
            if legacy_single_lock and state == LockState.GREEN_READY
            else _rgb(config.WHITE_RGB)
        )
        self.lock_percent_text.text = f"鎖定 {clamped_progress * 100.0:.0f}%"
        self.lock_percent_text.color = self.lock_label.color
        self.lock_bar_fill.scale_x = config.AA_LOCK_PROGRESS_BAR_WIDTH * clamped_progress
        self.lock_bar_fill.color = tint
        frame_half = config.AA_LOCK_FRAME_SIZE * whitebox_scale / 2.0
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
        whitebox_scale: float = 1.0,
        whitebox_multiplier: float = 1.0,
        anti_air_gui_mode: AntiAirGuiMode | str = AntiAirGuiMode.NEW,
    ) -> None:
        """Show exactly one weapon reticle family for the active phase/slot."""

        gui_mode = self._normalize_anti_air_gui_mode(anti_air_gui_mode)
        anti_air_equipped = (
            phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
            and weapon in (WeaponKind.ANTI_AIRCRAFT, WeaponKind.MULTI_ANTI_AIRCRAFT)
        )
        anti_air_scope_active = anti_air_equipped and anti_air_scope_enabled
        sniper_active = phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT) and weapon == WeaponKind.SNIPER
        pistol_active = phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT) and weapon == WeaponKind.PISTOL
        rpg_active = phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT) and weapon == WeaponKind.RPG
        legacy_single_lock = (
            gui_mode == AntiAirGuiMode.LEGACY
            and weapon == WeaponKind.ANTI_AIRCRAFT
        )
        # The enlarged fixed frame remains visible while the anti-air weapon
        # is equipped; dynamic lock feedback is scope-only.
        self.lock_frame.scale = max(
            0.1,
            float(whitebox_scale) * max(0.0, float(whitebox_multiplier)),
        )
        self.lock_frame.enabled = bool(anti_air_equipped)
        lock_ring = getattr(self, "lock_ring", None)
        if lock_ring is not None:
            if not (anti_air_scope_active and legacy_single_lock):
                lock_ring.enabled = False
        self.lock_label.enabled = anti_air_scope_active
        self.lock_reticle.enabled = bool(anti_air_scope_active and not legacy_single_lock)
        self.sniper_crosshair.enabled = sniper_active
        self.pistol_reticle.enabled = pistol_active
        rpg_reticle = getattr(self, "rpg_reticle", None)
        if rpg_reticle is not None:
            rpg_reticle.enabled = rpg_active
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
        level_key: Optional[LevelKey | str] = None,
        maximum_aircraft_count: Optional[int] = None,
        profile: Optional[SaveProfile] = None,
        ammo_text: Optional[str] = None,
        locked_target_ids: Optional[tuple[str, ...]] = None,
        turret_count: Optional[int] = None,
        player_view: Optional[PlayerStatusView] = None,
        city_view: Optional[CityStatusView] = None,
        wave_view: Optional[WaveStatusView] = None,
        cooldown_view: Optional[WeaponCooldownView] = None,
        multi_lock_views: Optional[Iterable[MultiLockView]] = None,
        lock_completion_flash: bool = False,
        anti_air_gui_mode: AntiAirGuiMode | str = AntiAirGuiMode.NEW,
    ) -> None:
        try:
            normalized_weapon = (
                weapon
                if isinstance(weapon, WeaponKind)
                else WeaponKind(weapon)
                if weapon is not None
                else None
            )
        except (TypeError, ValueError):
            normalized_weapon = None
        weapon_name = {
            None: "空手",
            WeaponKind.ANTI_AIRCRAFT: "防空炮",
            WeaponKind.SNIPER: "狙擊槍",
            WeaponKind.PISTOL: "手槍",
            WeaponKind.RPG: "RPG",
            WeaponKind.MULTI_ANTI_AIRCRAFT: "多目標防空炮",
        }[normalized_weapon]
        maximum_health = (
            effective_max_hp(profile, config=profile.config)
            if profile is not None
            else config.PLAYER_MAX_HEALTH
        )
        whitebox_scale = (
            effective_whitebox_scale(profile, config=profile.config)
            if profile is not None
            else 1.0
        )
        self.health_text.text = f"生命值: {health} / {maximum_health}"
        if city_health is not None:
            self.city_text.text = f"城市耐久: {max(0.0, city_health):.0f} / {config.CITY_MAX_HEALTH}"
        if wave_number is not None:
            self.wave_text.text = f"第 {wave_number} 波"
        if level_key is not None:
            self.wave_card_title.text = (
                f"關卡 {LevelKey.parse(level_key)}"
                + (f"／A={maximum_aircraft_count}" if maximum_aircraft_count is not None else "")
            )
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
        if ammo_text is not None:
            self.weapon_text.text += f"｜{ammo_text}"
        if locked_target_ids is not None:
            self.wave_card_target.text = (
                "鎖定：" + "、".join(locked_target_ids)
                if locked_target_ids
                else "鎖定：無"
            )
        if turret_count is not None:
            self.wave_card_turrets.text = (
                f"砲塔：{turret_count} / {config.MAX_AUTO_DEFENSE_TURRETS}"
            )
        else:
            self.wave_card_turrets.text = "砲塔：--"
        self.update_inventory(normalized_weapon, phase, profile)
        self.fps_text.text = f"FPS: {fps:.0f}" if fps is not None else "FPS: --"
        self.warning_text.text = "空襲警告：戰鬥機接近目標" if warning else ""
        self.prompt_text.text = prompt
        self.hit_text.text = hit_feedback
        self.scope_text.text = "狙擊瞄準：右鍵關閉" if scope_enabled else ""
        self.update_boss_health(boss_health, boss_max_health, label=boss_label)
        if player_view is None:
            player_view = build_player_status_view(health, maximum_health)
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
        if level_key is not None:
            self.wave_card_title.text = (
                f"關卡 {LevelKey.parse(level_key)}"
                + (f"／A={maximum_aircraft_count}" if maximum_aircraft_count is not None else "")
            )
        self.update_weapon_cooldown(
            cooldown_view,
            visible=phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT),
        )
        multi_lock_active = (
            normalized_weapon == WeaponKind.MULTI_ANTI_AIRCRAFT
            and anti_air_scope_enabled
            and phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
        )
        self.update_multi_lock_views(
            multi_lock_views or (),
            active=multi_lock_active,
        )
        whitebox_multiplier = (
            config.AA_MULTI_LOCK_FRAME_MULTIPLIER
            if normalized_weapon == WeaponKind.MULTI_ANTI_AIRCRAFT
            else 1.0
        )
        self.update_lock(
            lock_state,
            lock_visible,
            active=anti_air_scope_enabled and phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT) and normalized_weapon == WeaponKind.ANTI_AIRCRAFT,
            progress=lock_progress,
            target_position=lock_target_position,
            target_radius=lock_target_radius,
            completion_flash=lock_completion_flash,
            whitebox_scale=whitebox_scale * whitebox_multiplier,
            anti_air_gui_mode=anti_air_gui_mode,
        )
        self.update_reticle(
            normalized_weapon,
            phase,
            scope_enabled=scope_enabled,
            anti_air_scope_enabled=anti_air_scope_enabled,
            whitebox_scale=whitebox_scale,
            whitebox_multiplier=whitebox_multiplier,
            anti_air_gui_mode=anti_air_gui_mode,
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
        profile: Optional[SaveProfile] = None,
    ) -> None:
        """顯示選取、戰鬥階段與永久解鎖狀態。"""

        for kind, slot in self.inventory_slots.items():
            usable = inventory_selection_allowed(phase, kind)
            unlocked = profile is None or kind.value in set(profile.unlocked_weapons)
            selected = kind == selected_weapon
            panel = slot["panel"]
            key_text = slot["key"]
            name_text = slot["name"]
            base_name = slot.get("base_name", "")
            assert isinstance(panel, Entity)
            assert isinstance(key_text, Text)
            assert isinstance(name_text, Text)
            assert isinstance(base_name, str)
            # Gameplay HUD backgrounds stay transparent; selection is shown
            # through the text colors instead of a filled inventory tile.
            panel.color = color.rgba32(255, 255, 255, 0)
            key_text.color = (
                _rgb(config.YELLOW_RGB)
                if usable and unlocked
                else color.rgba32(170, 170, 170, 170)
            )
            name_text.color = (
                _rgb(config.GREEN_RGB)
                if selected
                else _rgb(config.WHITE_RGB)
                if usable and unlocked
                else color.rgba32(170, 170, 170, 170)
            )
            name_text.text = base_name if unlocked else f"{base_name}（未解鎖）"
