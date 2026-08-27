"""Ursina HUD and menu adapter."""

from __future__ import annotations

from typing import Callable, Optional

from ursina import Button, Entity, Text, camera, color
from ursina.models.procedural.circle import Circle

from . import config
from .rules import lock_status_label, tracking_ring_radius
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


class GameHUD:
    """Owns screen-space labels and the color-plus-text lock contract."""

    def __init__(self) -> None:
        self.root = Entity(parent=camera.ui)
        self.gameplay_root = Entity(parent=self.root, enabled=False)
        self.menu_root = Entity(parent=self.root, enabled=False)
        self.game_over_root = Entity(parent=self.root, enabled=False)

        self.lock_frame = self._make_reticle(self.gameplay_root)
        self.lock_ring = self._make_tracking_ring(self.gameplay_root)
        self.sniper_crosshair = self._make_crosshair(self.gameplay_root, 0.07)
        self.pistol_reticle = self._make_crosshair(self.gameplay_root, 0.035)
        self.scope_overlay = self._make_scope_overlay(self.gameplay_root)
        self.lock_frame.enabled = False
        self.lock_ring.enabled = False
        self.sniper_crosshair.enabled = False
        self.pistol_reticle.enabled = False
        self.lock_label = Text(
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
            color=color.rgba32(20, 25, 30, 210),
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
        self.lock_percent_text.enabled = False
        self.lock_bar_background.enabled = False
        self.lock_bar_fill.enabled = False
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
        self.stats_text = self._text(self.gameplay_root, "", x=-0.86, y=0.39, scale=0.85)
        self.fps_text = self._text(self.gameplay_root, "", x=0.72, y=0.45, scale=0.75)
        self.weapon_text = self._text(self.gameplay_root, "武器: 空手", x=-0.86, y=-0.43, scale=0.95)
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

        self._build_menu()
        self._build_game_over()

    @staticmethod
    def _text(parent: Entity, text: str, **kwargs) -> Text:
        return Text(parent=parent, text=text, **kwargs)

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
    def _make_scope_overlay(parent: Entity) -> Entity:
        root = Entity(parent=parent, enabled=False)
        overlay_color = color.rgba32(0, 0, 0, 220)
        Entity(parent=root, model="quad", scale=(2.0, 0.08), y=0.46, color=overlay_color)
        Entity(parent=root, model="quad", scale=(2.0, 0.08), y=-0.46, color=overlay_color)
        Entity(parent=root, model="quad", scale=(0.08, 0.86), x=-0.96, color=overlay_color)
        Entity(parent=root, model="quad", scale=(0.08, 0.86), x=0.96, color=overlay_color)
        return root

    def _build_inventory(self) -> dict[WeaponKind, dict[str, Entity | Text]]:
        """Build the always-visible three-slot weapon inventory bar."""

        Text(
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
                color=color.rgba32(28, 34, 46, 230),
            )
            key_text = Text(
                parent=root,
                text=key_label,
                origin=(0, 0),
                x=-0.07,
                y=0,
                scale=0.72,
                color=_rgb(config.YELLOW_RGB),
            )
            name_text = Text(
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
        Text(parent=self.menu_root, text="3D 防空守衛", origin=(0, 0), y=0.22, scale=2.0)
        Text(
            parent=self.menu_root,
            text="守住大樓，撐過無限空襲循環",
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
        Text(parent=self.game_over_root, text="防守失敗", origin=(0, 0), y=0.25, scale=1.8)
        self.failure_text = Text(parent=self.game_over_root, text="", origin=(0, 0), y=0.13, scale=1.0)
        self.final_stats_text = Text(parent=self.game_over_root, text="", origin=(0, 0), y=0.0, scale=0.9)
        self.return_button = Button(
            parent=self.game_over_root,
            text="返回主選單",
            scale=(0.3, 0.075),
            y=-0.18,
        )

    def bind_menu_actions(self, start: Callable[[], None], quit_game: Callable[[], None]) -> None:
        self.start_button.on_click = start
        self.quit_button.on_click = quit_game

    def bind_return_action(self, callback: Callable[[], None]) -> None:
        self.return_button.on_click = callback

    def show_main_menu(self) -> None:
        self.menu_root.enabled = True
        self.gameplay_root.enabled = False
        self.game_over_root.enabled = False

    def show_gameplay(self) -> None:
        self.menu_root.enabled = False
        self.gameplay_root.enabled = True
        self.game_over_root.enabled = False

    def show_game_over(self, stats: SessionStats) -> None:
        self.menu_root.enabled = False
        self.gameplay_root.enabled = False
        self.game_over_root.enabled = True
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

    def update_lock(
        self,
        state: LockState,
        visible: bool,
        *,
        active: bool = True,
        progress: float = 0.0,
        target_position: Optional[tuple[float, float]] = None,
        target_radius: float = 0.008,
    ) -> None:
        self.lock_frame.enabled = active
        self.lock_ring.enabled = active and target_position is not None
        self.lock_label.enabled = active
        self.lock_percent_text.enabled = active
        self.lock_bar_background.enabled = active
        self.lock_bar_fill.enabled = active
        if state == LockState.WHITE:
            tint = _rgb(config.WHITE_RGB)
        elif state == LockState.RED_TRACKING:
            tint = _rgb(config.RED_RGB) if visible else color.rgba(0, 0, 0, 0)
        else:
            tint = _rgb(config.GREEN_RGB)
        for child in self.lock_frame.children:
            child.color = tint
        self.lock_ring.color = tint
        self.lock_label.text = lock_status_label(state)
        self.lock_label.color = _rgb(config.GREEN_RGB) if state == LockState.GREEN_READY else _rgb(config.WHITE_RGB)
        clamped_progress = max(0.0, min(1.0, float(progress)))
        self.lock_percent_text.text = f"鎖定 {clamped_progress * 100.0:.0f}%"
        self.lock_percent_text.color = self.lock_label.color
        self.lock_bar_fill.scale_x = config.AA_LOCK_PROGRESS_BAR_WIDTH * clamped_progress
        self.lock_bar_fill.color = tint
        if target_position is not None:
            self.lock_ring.position = target_position
            radius = tracking_ring_radius(
                config.AA_LOCK_RING_ACQUISITION_RADIUS,
                target_radius,
                clamped_progress,
                padding=config.AA_LOCK_RING_PADDING,
            )
            base_radius = max(1e-6, config.AA_LOCK_RING_ACQUISITION_RADIUS)
            ratio = radius / base_radius
            self.lock_ring.scale = (ratio, ratio, 1.0)

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
            phase == GamePhase.AIRSTRIKE
            and weapon == WeaponKind.ANTI_AIRCRAFT
        )
        anti_air_scope_active = anti_air_equipped and anti_air_scope_enabled
        sniper_active = phase == GamePhase.GROUND_COMBAT and weapon == WeaponKind.SNIPER
        pistol_active = phase == GamePhase.GROUND_COMBAT and weapon == WeaponKind.PISTOL
        # The enlarged fixed frame remains visible while the anti-air weapon
        # is equipped; dynamic lock feedback is scope-only.
        self.lock_frame.enabled = anti_air_equipped
        self.lock_label.enabled = anti_air_scope_active
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
        self.update_lock(
            lock_state,
            lock_visible,
            active=anti_air_scope_enabled and phase == GamePhase.AIRSTRIKE and weapon == WeaponKind.ANTI_AIRCRAFT,
            progress=lock_progress,
            target_position=lock_target_position,
            target_radius=lock_target_radius,
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
                kind == WeaponKind.ANTI_AIRCRAFT and phase == GamePhase.AIRSTRIKE
            ) or (
                kind in (WeaponKind.SNIPER, WeaponKind.PISTOL)
                and phase == GamePhase.GROUND_COMBAT
            )
            selected = kind == selected_weapon
            panel = slot["panel"]
            key_text = slot["key"]
            name_text = slot["name"]
            assert isinstance(panel, Entity)
            assert isinstance(key_text, Text)
            assert isinstance(name_text, Text)
            if selected:
                panel.color = color.rgba32(25, 112, 78, 245)
            elif usable:
                panel.color = color.rgba32(28, 58, 72, 235)
            else:
                panel.color = color.rgba32(28, 34, 46, 145)
            key_text.color = _rgb(config.YELLOW_RGB) if usable else color.rgba32(170, 170, 170, 170)
            name_text.color = _rgb(config.WHITE_RGB) if usable else color.rgba32(170, 170, 170, 170)
