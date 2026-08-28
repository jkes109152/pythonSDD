"""Application entry point and frame/update orchestration for the prototype."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from direct.task import Task
from ursina import Text, Ursina, application, camera, time, window

from . import config
from .entities import (
    Aircraft,
    AntiAircraftGun,
    AutoDefenseTurret,
    GuidedMissile,
    GroundEncounter,
    GroundTracerEffect,
    MultiAntiAircraftGun,
    Pistol,
    Player,
    RPGProjectileEffect,
    RPGWeapon,
    SniperRifle,
    TargetBuilding,
)
from .hud import GameHUD
from .rules import (
    EncounterFactory,
    LockOnTracker,
    MissileVolley,
    MultiLockOnTracker,
    advance_crew_behavior,
    apply_city_damage,
    apply_enemy_hit,
    apply_guided_missile_damage,
    auto_defense_damage_for_target,
    can_fire_anti_air,
    can_fire_pistol,
    can_fire_sniper,
    build_city_status_view,
    build_player_status_view,
    build_wave_status_view,
    damage_crew_member,
    inventory_selection_allowed,
    apply_rpg_explosion,
    is_valid_target,
    select_turret_target,
    resolve_aircraft_outcome,
    reset_weapon_cooldowns,
    select_lock_target,
    WaveDirector,
    weapon_cooldown_view,
    warning_active,
)
from .scene import AirDefenseScene, distance_xz
from .save_data import SaveLoadResult, SaveStore
from .progression import (
    effective_cooldown,
    effective_lock_duration,
    effective_whitebox_scale,
    has_upgrade,
    upgrade_catalog,
)
from .state import (
    AntiAirGuiMode,
    CrewBehaviorState,
    AircraftPhase,
    GamePhase,
    GameSession,
    LockState,
    SessionEvent,
    AircraftType,
    WeaponKind,
)


class AirDefenseGame:
    """Coordinates the state machine, domain entities and Ursina adapters."""

    def __init__(self, app: Ursina, save_store: Optional[SaveStore] = None) -> None:
        self.app = app
        self.save_store = save_store or SaveStore()
        self.session = GameSession(save_store=self.save_store, phase=GamePhase.SAVE_SELECT)
        self.player = Player()
        self.scene = AirDefenseScene()
        self.hud = GameHUD()
        self.lock_tracker = LockOnTracker()
        self.encounter_factory = EncounterFactory()
        self.wave_director = WaveDirector()
        self.aircraft: Optional[Aircraft] = None
        self.aircrafts: dict[str, Aircraft] = {}
        self.encounter: Optional[GroundEncounter] = None
        self.city = TargetBuilding()
        self.anti_aircraft: Optional[AntiAircraftGun] = None
        self.sniper: Optional[SniperRifle] = None
        self.pistol: Optional[Pistol] = None
        self.rpg: Optional[RPGWeapon] = None
        self.multi_anti_aircraft: Optional[MultiAntiAircraftGun] = None
        self.multi_lock_tracker = MultiLockOnTracker()
        self.turrets: list[AutoDefenseTurret] = []
        self._game_over_presented = False
        self._hit_feedback_seconds = 0.0
        self._fps_sample_elapsed = 0.0
        self._fps_sample_frames = 0
        self._fps_value: Optional[float] = None
        self.active_missiles: dict[str, GuidedMissile] = {}
        self.active_volleys: dict[str, MissileVolley] = {}
        self._missile_sequence = 0
        self._rpg_explosion_sequence = 0
        self._aircraft_screen_target = None
        self._aircraft_screen_targets: dict[str, object] = {}
        self._tracer_event_ids: set[str] = set()
        self._game_over_snapshot: Optional[dict[str, object]] = None
        self._victory_presented = False
        self.anti_air_gui_mode = AntiAirGuiMode.NEW
        self._settings_open = False

        self.hud.bind_menu_actions(self.start_game, self.quit_game, self.open_settings)
        self.hud.bind_settings_actions(self.set_anti_air_gui_mode, self.close_settings)
        self.hud.bind_progression_actions(
            self.select_save_slot,
            self.open_shop,
            self.rebirth,
            self.return_to_menu,
            self.purchase_upgrade,
            self.delete_save_slot,
        )
        self.hud.bind_return_action(self.return_to_menu)
        self.hud.show_save_select(self.save_store.list_slots())
        self.scene.set_gameplay_enabled(False)

    def start_game(self) -> None:
        if self.session.phase != GamePhase.MAIN_MENU:
            return
        self._settings_open = False
        if self.session.profile is not None:
            self._start_profile_sublevel()
            return
        self.scene.clear_world()
        first_plan = self.wave_director.plan_wave(1)
        self.session.transition(SessionEvent.START_GAME, wave_plan=first_plan)
        first_ids = tuple(
            "aircraft-001" if index == 0 else f"aircraft-001-{index + 1:02d}"
            for index in range(first_plan.aircraft_count)
        )
        self.session.initialize_wave_runtime(first_ids, dict(zip(first_ids, first_plan.roster)))
        self.player = Player()
        self.city = TargetBuilding()
        self.anti_aircraft = AntiAircraftGun(world_position=config.DEFENSE_POINT_POSITION)
        self.sniper = SniperRifle(world_position=config.WEAPON_RACK_POSITION)
        self.pistol = Pistol(world_position=config.WEAPON_RACK_POSITION)
        self._reset_airstrike_guidance(clear_missiles=True)
        self.encounter = None
        self.aircrafts.clear()
        self._aircraft_screen_target = None
        getattr(self, "_aircraft_screen_targets", {}).clear()
        self._game_over_snapshot = None
        self._victory_presented = False
        self._tracer_event_ids.clear()
        self._game_over_presented = False
        self._hit_feedback_seconds = 0.0
        self._fps_sample_elapsed = 0.0
        self._fps_sample_frames = 0
        self._fps_value = None

        world = self.scene.build_world()
        world.sniper_pickup.enabled = False
        self._spawn_current_aircraft()
        self.scene.set_gameplay_enabled(True)
        self.hud.show_gameplay()
        self._refresh_hud()

    def select_save_slot(self, slot_id: int) -> SaveLoadResult:
        """啟動時選擇欄位；載入後只顯示該欄位主選單。"""

        result = self.session.select_save_slot(slot_id, store=self.save_store)
        self.hud.update_profile_summary(
            self.session.profile,
            warning=result.warning,
            next_level=self.session.session_progress.next_play_level,
        )
        self.hud.show_main_menu()
        self._settings_open = False
        self.scene.set_gameplay_enabled(False)
        return result

    def delete_save_slot(self, slot_id: int) -> None:
        """刪除選檔畫面指定欄位後重新整理五個欄位。"""

        result = self.session.delete_save_slot(slot_id)
        if result.deleted:
            message = f"{result.slot_id} 號存檔已刪除。"
        elif result.is_empty:
            message = f"{result.slot_id} 號存檔本來就是空白。"
        else:
            message = f"刪除 {result.slot_id} 號存檔失敗：{result.error}"
        self.hud.show_save_select(self.save_store.list_slots(), warning=message)
        self.scene.set_gameplay_enabled(False)

    def open_shop(self) -> None:
        self._settings_open = False
        if self.session.open_shop() != GamePhase.SHOP:
            return
        self.hud.show_shop(self.session.profile)

    def open_settings(self) -> None:
        """Open the session-only anti-air HUD preference page."""

        if self.session.phase != GamePhase.MAIN_MENU:
            return
        self._settings_open = True
        self.hud.show_settings(self.anti_air_gui_mode)

    def close_settings(self) -> None:
        """Return from settings without changing gameplay or Profile data."""

        self._settings_open = False
        if self.session.phase == GamePhase.MAIN_MENU:
            self.hud.show_main_menu()

    def set_anti_air_gui_mode(self, mode: AntiAirGuiMode | str) -> None:
        """Select the visual anti-air interface; weapon rules remain shared."""

        try:
            self.anti_air_gui_mode = (
                mode if isinstance(mode, AntiAirGuiMode) else AntiAirGuiMode(mode)
            )
        except (TypeError, ValueError):
            return
        if self._settings_open:
            self.hud.update_settings_mode(self.anti_air_gui_mode)

    def purchase_upgrade(self, upgrade_id: str) -> None:
        """結算一次商店操作，鍵盤與按鈕共用同一個冪等入口。"""

        profile = self.session.profile
        if profile is None or self.session.phase != GamePhase.SHOP:
            return
        level = profile.upgrade_levels.get(str(upgrade_id), 0)
        operation_id = (
            f"shop-ui-{id(self)}-{upgrade_id}-"
            f"{profile.coins}-{level}"
        )
        result = self.session.purchase_upgrade_once(operation_id, upgrade_id)
        self.hud.update_shop_details(
            self.session.profile,
            selected_upgrade=upgrade_id,
            result_message=(
                "購買成功"
                if result.success
                else f"購買失敗：{result.error}"
            ),
        )
        self.hud.update_profile_summary(
            self.session.profile,
            next_level=self.session.session_progress.next_play_level,
        )

    def rebirth(self) -> None:
        profile = self.session.profile
        operation_id = (
            f"rebirth-ui-{id(self)}-"
            f"{profile.rebirth_count if profile else 0}-"
            f"{profile.coins if profile else 0}-"
            f"{int(profile.rebirth_available) if profile else 0}"
        )
        result = self.session.apply_rebirth_once(operation_id)
        if result.success:
            self.hud.update_profile_summary(
                self.session.profile,
                next_level=self.session.session_progress.next_play_level,
            )
            self.hud.show_main_menu()
        else:
            message = f"重生失敗：{result.error}"
            if self.session.phase == GamePhase.SHOP:
                self.hud.update_shop_details(
                    self.session.profile,
                    result_message=message,
                )
                self.hud.show_shop(self.session.profile)
            else:
                self.hud.update_profile_summary(
                    self.session.profile,
                    warning=message,
                    next_level=self.session.session_progress.next_play_level,
                )
                self.hud.show_main_menu()

    def _start_profile_sublevel(self) -> None:
        """以 Profile／SessionProgress 建立單一動態 a-b 小關。"""

        self.scene.clear_world()
        run = self.session.start_sublevel()
        self.player = Player(
            max_health=run.effective_max_hp,
            health=int(run.current_hp),
        )
        self.city = TargetBuilding()
        self.anti_aircraft = AntiAircraftGun(world_position=config.DEFENSE_POINT_POSITION)
        self.sniper = SniperRifle(world_position=config.WEAPON_RACK_POSITION)
        self.pistol = Pistol(world_position=config.WEAPON_RACK_POSITION)
        self.rpg = RPGWeapon(
            world_position=config.WEAPON_RACK_POSITION,
            ammo_remaining=self.session.progression_config.rpg_ammo_per_sublevel,
            explosion_radius=self.session.progression_config.rpg_explosion_radius,
            damage=self.session.progression_config.rpg_damage,
        )
        self.multi_anti_aircraft = MultiAntiAircraftGun(
            world_position=config.DEFENSE_POINT_POSITION,
        )
        self.turrets = run.turrets
        lock_duration = effective_lock_duration(
            self.session.profile,
            config=self.session.progression_config,
        )
        self.lock_tracker.lock_duration = lock_duration
        self.multi_lock_tracker = MultiLockOnTracker(
            lock_duration=lock_duration,
        )
        self._reset_airstrike_guidance(clear_missiles=True)
        self.encounter = None
        self.aircrafts.clear()
        self._aircraft_screen_target = None
        self._aircraft_screen_targets.clear()
        self._game_over_snapshot = None
        self._victory_presented = False
        self._tracer_event_ids.clear()
        self._game_over_presented = False
        self._hit_feedback_seconds = 0.0
        self._fps_sample_elapsed = 0.0
        self._fps_sample_frames = 0
        self._fps_value = None
        world = self.scene.build_world()
        world.sniper_pickup.enabled = False
        self.scene.create_auto_defense_turrets(self.turrets)
        self._spawn_current_aircraft()
        self.scene.set_gameplay_enabled(True)
        self.hud.show_gameplay()
        self._refresh_hud()

    def quit_game(self) -> None:
        application.quit()

    def return_to_menu(self) -> None:
        if self.session.profile is not None:
            self.session.return_to_profile_menu()
        elif self.session.phase in (GamePhase.GAME_OVER, GamePhase.VICTORY):
            self.session.transition(SessionEvent.RETURN_TO_MENU)
        self.reset_weapon_cooldowns()
        self.scene.clear_world()
        self.aircraft = None
        self.aircrafts.clear()
        self.encounter = None
        self.city = TargetBuilding()
        self.anti_aircraft = None
        self.sniper = None
        self.pistol = None
        self.rpg = None
        self.multi_anti_aircraft = None
        getattr(self, "turrets", []).clear()
        if getattr(self, "multi_lock_tracker", None) is not None:
            self.multi_lock_tracker.reset()
        self._reset_airstrike_guidance(clear_missiles=True)
        self._aircraft_screen_target = None
        self._aircraft_screen_targets.clear()
        self._game_over_snapshot = None
        self._victory_presented = False
        self._tracer_event_ids.clear()
        self.scene.set_scope_enabled(False)
        self._game_over_presented = False
        self._settings_open = False
        self.hud.show_main_menu()
        if self.session.profile is not None:
            self.hud.update_profile_summary(
                self.session.profile,
                next_level=self.session.session_progress.next_play_level,
            )
        self.scene.set_gameplay_enabled(False)

    def input(self, key: str) -> None:
        """Process input before the next object/rule update."""

        if self.session.phase == GamePhase.SAVE_SELECT:
            if key in {"1", "2", "3", "4", "5"}:
                self.select_save_slot(int(key))
            elif key == "left mouse down":
                for index, button in enumerate(self.hud.save_slot_buttons, start=1):
                    if button.hovered:
                        self.select_save_slot(index)
                        return
                for index, button in enumerate(self.hud.save_delete_buttons, start=1):
                    if button.hovered:
                        self.hud.request_delete_slot(index)
                        return
                if self.hud.save_confirm_delete_button.hovered:
                    self.hud.confirm_delete_slot()
                    return
                if self.hud.save_cancel_delete_button.hovered:
                    self.hud.cancel_delete_slot()
                    return
            elif key in ("q", "escape"):
                self.quit_game()
            return

        if self.session.phase == GamePhase.MAIN_MENU:
            if getattr(self, "_settings_open", False):
                if key in ("escape", "backspace"):
                    self.close_settings()
                elif key == "q":
                    self.quit_game()
                elif key == "left mouse down":
                    if getattr(self.hud, "settings_new_button", None) is not None and self.hud.settings_new_button.hovered:
                        self.set_anti_air_gui_mode(AntiAirGuiMode.NEW)
                    elif getattr(self.hud, "settings_legacy_button", None) is not None and self.hud.settings_legacy_button.hovered:
                        self.set_anti_air_gui_mode(AntiAirGuiMode.LEGACY)
                    elif getattr(self.hud, "settings_back_button", None) is not None and self.hud.settings_back_button.hovered:
                        self.close_settings()
                return
            if key in ("enter", "space"):
                self.start_game()
            elif key in ("u", "s"):
                self.open_shop()
            elif key == "r":
                self.rebirth()
            elif key in ("q", "escape"):
                self.quit_game()
            elif key == "left mouse down":
                # Keep menu actions working even when a window/input backend
                # delivers the click to the game bridge before Ursina's
                # Button mouse handler.
                if self.hud.start_button.hovered:
                    self.start_game()
                elif self.hud.shop_button.hovered:
                    self.open_shop()
                elif getattr(self.hud, "settings_button", None) is not None and self.hud.settings_button.hovered:
                    self.open_settings()
                elif self.hud.rebirth_button.hovered:
                    self.rebirth()
                elif self.hud.quit_button.hovered:
                    self.quit_game()
            return

        if self.session.phase == GamePhase.SHOP:
            if key in ("escape", "backspace"):
                self.return_to_menu()
            elif key in {"1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "t"}:
                upgrade_ids = (
                    "max_hp",
                    "armor",
                    "aa_lock_time",
                    "aa_whitebox",
                    "aa_aim_assist",
                    "weapon_cooldown",
                    "rpg",
                    "auto_defense",
                    "multi_anti_aircraft",
                    "auto_defense_capacity",
                    "multi_anti_aircraft_targets",
                )
                index = int(key) - 1 if key != "0" else 9
                if key == "t":
                    index = 10
                self.purchase_upgrade(upgrade_ids[index])
            elif key == "left mouse down":
                handled = False
                for entry, button in zip(
                    upgrade_catalog(self.session.progression_config),
                    getattr(self.hud, "shop_upgrade_buttons", ()),
                ):
                    if button.hovered:
                        self.purchase_upgrade(entry.upgrade_id)
                        handled = True
                        break
                if not handled and self.hud.shop_back_button.hovered:
                    self.return_to_menu()
            return

        if self.session.phase in (GamePhase.GAME_OVER, GamePhase.VICTORY):
            if key in ("enter", "escape"):
                self.return_to_menu()
            elif key == "left mouse down" and (
                self.hud.return_button.hovered
                or getattr(self.hud, "victory_return_button", None) is not None
                and self.hud.victory_return_button.hovered
            ):
                self.return_to_menu()
            return

        # E/G 已永久取消，不觸發互動、丟棄或任何替代功能。
        if key in {"e", "g"}:
            return
        if key == "1":
            self._select_weapon(WeaponKind.ANTI_AIRCRAFT)
        elif key == "2":
            self._select_weapon(WeaponKind.SNIPER)
        elif key == "3":
            self._select_weapon(WeaponKind.PISTOL)
        elif key == "4":
            self._select_weapon(WeaponKind.RPG)
        elif key == "5":
            self._select_weapon(WeaponKind.MULTI_ANTI_AIRCRAFT)
        elif key == "left mouse down":
            self._fire_current_weapon()
        elif key == "right mouse down":
            self._toggle_scope()

    def update(self) -> None:
        """Run the explicit per-frame order described by the implementation plan."""

        raw_delta_seconds = max(float(time.dt), 0.0)
        delta_seconds = min(raw_delta_seconds, 0.1)
        self._fps_sample_elapsed += raw_delta_seconds
        self._fps_sample_frames += 1
        if self._fps_sample_elapsed >= 1.0:
            if self._fps_sample_elapsed > 0:
                self._fps_value = self._fps_sample_frames / self._fps_sample_elapsed
            self._fps_sample_elapsed = 0.0
            self._fps_sample_frames = 0
        self.scene.tick_effects(delta_seconds)
        position = self.scene.player_position()
        self.player.position = (float(position.x), float(position.y), float(position.z))
        gameplay_phase = self.session.phase in (
            GamePhase.AIRSTRIKE,
            GamePhase.HYBRID_COMBAT,
            GamePhase.GROUND_COMBAT,
        )
        if gameplay_phase:
            self._tick_weapon_cooldowns(delta_seconds)
            self.session.tick(delta_seconds)

        if self.session.phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT):
            self._update_airstrike(delta_seconds)
        if self.session.phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT):
            self._update_ground_combat(delta_seconds)
        elif self.session.phase == GamePhase.GAME_OVER:
            self._present_game_over()
        elif self.session.phase == GamePhase.VICTORY:
            self._present_victory()

        self.player.health = self.session.health
        if self._hit_feedback_seconds > 0:
            self._hit_feedback_seconds = max(0.0, self._hit_feedback_seconds - delta_seconds)
        self._refresh_hud()

    def _tick_weapon_cooldowns(self, delta_seconds: float) -> None:
        if self.anti_aircraft is not None:
            self.anti_aircraft.update_cooldown(delta_seconds)
        if self.sniper is not None:
            self.sniper.update_cooldown(delta_seconds)
        if self.pistol is not None:
            self.pistol.update_cooldown(delta_seconds)
        if self.rpg is not None:
            self.rpg.update_cooldown(delta_seconds)
        if self.multi_anti_aircraft is not None:
            self.multi_anti_aircraft.update_cooldown(delta_seconds)
        for turret in getattr(self, "turrets", []):
            turret.update(delta_seconds)

    def _reset_airstrike_guidance(self, *, clear_missiles: bool) -> None:
        """Reset lock/target state and optionally remove active target-bound missiles."""

        hud = getattr(self, "hud", None)
        clear_weapon_ui = getattr(hud, "clear_transient_weapon_ui", None)
        if callable(clear_weapon_ui):
            clear_weapon_ui()
        self.lock_tracker.set_scope_enabled(False)
        self.session.reset_airstrike_guidance(clear_missiles=clear_missiles)
        if self.session.wave_runtime is not None:
            self.session.wave_runtime.set_active_target(None)
        if self.anti_aircraft is not None:
            self.anti_aircraft.lock_state = LockState.WHITE
            self.anti_aircraft.lock_elapsed = 0.0
            self.anti_aircraft.target_aircraft_id = None
            self.anti_aircraft.target_in_zone = False
        if getattr(self, "multi_lock_tracker", None) is not None:
            self.multi_lock_tracker.reset()
        if getattr(self, "multi_anti_aircraft", None) is not None:
            self.multi_anti_aircraft.target_aircraft_ids.clear()
        if clear_missiles:
            self._clear_active_missiles()
            self._missile_sequence = 0

    def reset_weapon_cooldowns(self) -> int:
        """Reset all weapon-local timers at an explicit lifecycle boundary."""

        return reset_weapon_cooldowns(
            getattr(self, "anti_aircraft", None),
            getattr(self, "sniper", None),
            getattr(self, "pistol", None),
            getattr(self, "rpg", None),
            getattr(self, "multi_anti_aircraft", None),
        )

    def _clear_active_missiles(self) -> None:
        """Remove every visual/domain missile before a target/session boundary."""

        for missile_id in tuple(getattr(self, "active_missiles", {})):
            self.scene.remove_guided_missile(missile_id)
        getattr(self, "active_missiles", {}).clear()
        self.session.active_missile_ids.clear()
        getattr(self, "active_volleys", {}).clear()

    def _reset_lock_after_shot(self) -> None:
        """Require a fresh full lock after each valid missile launch."""

        self.lock_tracker.reset()
        self.session.lock_state = LockState.WHITE
        self.session.lock_elapsed = 0.0
        self.session.target_in_zone = False
        if self.session.wave_runtime is not None:
            self.session.wave_runtime.set_active_target(None)
        if self.anti_aircraft is not None:
            self.anti_aircraft.lock_state = LockState.WHITE
            self.anti_aircraft.lock_elapsed = 0.0
            self.anti_aircraft.target_aircraft_id = None
            self.anti_aircraft.target_in_zone = False

    def _update_active_missiles(self, delta_seconds: float) -> bool:
        """Advance each missile against its own target ID."""

        aircrafts = dict(self.aircrafts)
        if not aircrafts and self.aircraft is not None:
            aircrafts[self.aircraft.id] = self.aircraft
        if not aircrafts:
            self._clear_active_missiles()
            return False
        destroyed_any = False
        for missile_id, missile in tuple(self.active_missiles.items()):
            aircraft = aircrafts.get(missile.target_aircraft_id)
            if aircraft is None or aircraft.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
                self.scene.remove_guided_missile(missile_id)
                self.active_missiles.pop(missile_id, None)
                self.session.active_missile_ids.discard(missile_id)
                continue

            step = missile.advance(delta_seconds, aircraft.position)
            self.scene.update_guided_missile(missile)
            if step.hit:
                destroyed = apply_guided_missile_damage(
                    aircraft,
                    missile,
                    step,
                    active_aircraft_id=aircraft.id,
                    expected_aircraft_id=aircraft.id,
                )
                self.scene.remove_guided_missile(missile_id, explode=True)
                self.active_missiles.pop(missile_id, None)
                self.session.active_missile_ids.discard(missile_id)
                self._hit_feedback_seconds = 0.6
                if destroyed:
                    destroyed_any = True
                    self._on_aircraft_destroyed(aircraft.id)
            elif step.expired:
                self.scene.remove_guided_missile(missile_id)
                self.active_missiles.pop(missile_id, None)
                self.session.active_missile_ids.discard(missile_id)
        self._prune_active_volleys()
        return destroyed_any

    def _prune_active_volleys(self) -> None:
        """Drop completed volley snapshots after all of their missiles finish."""

        volleys = getattr(self, "active_volleys", {})
        active_missile_ids = set(getattr(self, "active_missiles", {}))
        for volley_id, volley in tuple(volleys.items()):
            missile_ids = {
                str(missile_id)
                for _target_id, missile_id in getattr(volley, "missile_ids", ())
            }
            if not missile_ids or not (missile_ids & active_missile_ids):
                volleys.pop(volley_id, None)

    def _on_aircraft_destroyed(self, aircraft_id: Optional[str] = None) -> None:
        """Resolve one collision and immediately attach its source drop batch."""

        aircrafts = getattr(self, "aircrafts", {})
        aircraft = aircrafts.get(aircraft_id) if aircraft_id is not None else None
        if aircraft_id is not None and aircraft is None:
            return
        if aircraft is None:
            aircraft = self.aircraft
        if aircraft is None:
            return
        aircraft_id = aircraft.id
        aircraft_type = aircraft.aircraft_type

        # Preserve the original single-aircraft controller path for external
        # callers and older lifecycle tests that did not opt into WaveRuntime.
        runtime = self.session.wave_runtime
        if runtime is None:
            self._reset_airstrike_guidance(clear_missiles=True)
            self.scene.remove_aircraft(crash=False)
            self.scene.set_scope_enabled(False)
            self._aircraft_screen_target = None
            outcome = resolve_aircraft_outcome(
                self.session,
                aircraft_id=aircraft_id,
                outcome="destroyed",
            )
            if not outcome.success:
                return
            self.aircraft = None
            self.encounter = self.encounter_factory.create_for_aircraft(
                aircraft_id,
                aircraft_type,
            )
            if self.scene.world is not None:
                self.scene.world.sniper_pickup.enabled = True
            self.scene.create_crew(self.encounter)
            if self.encounter.cleared:
                self._complete_encounter()
            return

        if self.session.phase not in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT):
            return
        aircraft_type = runtime.aircraft_types.get(aircraft_id, aircraft.aircraft_type)
        if aircraft_id in runtime.drop_spawned_aircraft_ids:
            return
        hit_position = tuple(aircraft.position)
        if not self.session.mark_aircraft_destroyed(aircraft_id):
            return
        self.scene.remove_aircraft(aircraft_id, crash=False)
        aircrafts.pop(aircraft_id, None)
        for missile_id, missile in tuple(self.active_missiles.items()):
            if missile.target_aircraft_id == aircraft_id:
                self.scene.remove_guided_missile(missile_id)
                self.active_missiles.pop(missile_id, None)
                self.session.active_missile_ids.discard(missile_id)
        if self.lock_tracker.target_aircraft_id == aircraft_id:
            self._reset_airstrike_guidance(clear_missiles=False)
        runtime.set_active_target(None)
        self._aircraft_screen_target = None
        getattr(self, "_aircraft_screen_targets", {}).pop(aircraft_id, None)

        # Source completion is recorded even when FAST (or a zero-roll NORMAL)
        # intentionally produces no crew, so duplicate callbacks can never
        # create the same batch twice.
        encounter = self._current_ground_encounter()
        if encounter is not None:
            # Prefer the aggregate encounter already present in RunState (or
            # repair it from the controller cache) so a stale encounter ID
            # cannot strand this destroyed source without a drop decision.
            encounter_id = encounter.id
            runtime.ground_encounter_id = encounter_id
            if self.session.run_state is not None:
                self.session.run_state.ground_encounter = encounter
        else:
            encounter_id = runtime.ground_encounter_id or (
                f"encounter:wave-{runtime.wave.wave_number}"
            )
        batch = self.encounter_factory.create_drop_batch(
            aircraft_id,
            aircraft_type,
            encounter_id,
            hit_position,
        )
        if not batch:
            runtime.mark_drop_spawned(aircraft_id)
        else:
            if encounter is None:
                encounter = GroundEncounter(
                    aircraft_id=f"wave-{runtime.wave.wave_number}",
                    crew=[],
                    group_id=f"wave-{runtime.wave.wave_number}",
                )
                self.encounter = encounter
                if self.session.run_state is not None:
                    self.session.run_state.ground_encounter = encounter
            if not encounter.add_reinforcement(batch, aircraft_id):
                return
            self.session.transition(
                SessionEvent.DROP_STARTED,
                event_id=f"drop-started:{runtime.wave.wave_number}:{aircraft_id}",
                aircraft_id=aircraft_id,
                encounter_id=encounter.id,
            )
            self.session.active_encounter_id = encounter.id
            if self.session.run_state is not None:
                self.session.run_state.ground_encounter = encounter
            self.scene.create_crew_members(batch)
            if self.scene.world is not None:
                self.scene.world.sniper_pickup.enabled = True

        if runtime.all_aircraft_destroyed:
            self.aircraft = None
            self.session.active_aircraft_id = None
            self.session.active_aircraft_type = None
            self._reset_airstrike_guidance(clear_missiles=False)
            self.scene.set_scope_enabled(False)
        else:
            alive_id = runtime.alive_aircraft_ids[0] if runtime.alive_aircraft_ids else None
            self.session.active_aircraft_id = alive_id
            self.session.active_aircraft_type = (
                runtime.aircraft_types[alive_id] if alive_id is not None else None
            )
            self.aircraft = aircrafts.get(alive_id)

        if self._wave_clear_ready():
            self._complete_encounter()

    def _on_aircraft_impacted(self, aircraft_id: str) -> None:
        """Make one impact a global terminal event and stop every dynamic path."""

        if self.session.profile is not None and self.session.run_state is not None:
            self.session.transition(
                SessionEvent.BUILDING_IMPACT,
                aircraft_id=aircraft_id,
            )
            self._finish_profile_failure("飛機撞擊大樓")
            return

        aircrafts = getattr(self, "aircrafts", {})
        aircraft = aircrafts.get(aircraft_id) or self.aircraft
        if aircraft is not None and aircraft.phase != AircraftPhase.IMPACTED:
            aircraft.impact()
        runtime = self.session.wave_runtime
        if runtime is not None:
            already_impacted = runtime.aircraft_statuses.get(aircraft_id) == AircraftPhase.IMPACTED
            if not already_impacted and not runtime.mark_impacted(aircraft_id):
                return
            if already_impacted and self.session.phase == GamePhase.GAME_OVER:
                return
            self.session.stats.record_once(
                f"building-impact:{aircraft_id}",
                "building_impact",
            )
            self.session.phase = GamePhase.GAME_OVER
        else:
            self.session.transition(
                SessionEvent.BUILDING_IMPACT,
                aircraft_id=aircraft_id,
            )
        self._clear_active_missiles()
        self._reset_airstrike_guidance(clear_missiles=False)
        self.scene.clear_dynamic(clear_effects=False)
        self.aircrafts.clear()
        self.aircraft = None
        self._aircraft_screen_target = None
        getattr(self, "_aircraft_screen_targets", {}).clear()
        self.encounter = None
        self.scene.set_scope_enabled(False)
        self.reset_weapon_cooldowns()
        self._present_game_over()

    def _update_airstrike(self, delta_seconds: float) -> None:
        aircrafts = getattr(self, "aircrafts", {})
        if not aircrafts and self.aircraft is not None:
            aircrafts = {self.aircraft.id: self.aircraft}
        if not aircrafts:
            return

        runtime = self.session.wave_runtime
        for aircraft_id in sorted(tuple(aircrafts)):
            aircraft = aircrafts.get(aircraft_id)
            if aircraft is None or aircraft.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
                continue
            aircraft.advance(delta_seconds)
            self.scene.update_aircraft(aircraft)
            if runtime is not None:
                self.session.sync_aircraft_phase(aircraft_id, aircraft.phase)
            if aircraft.path_progress >= 1.0:
                if aircraft.impact():
                    if runtime is not None:
                        self.session.sync_aircraft_phase(aircraft_id, AircraftPhase.IMPACTED)
                    self._on_aircraft_impacted(aircraft_id)
                return

        # Process target-bound missiles before calculating the next lock view.
        self._update_active_missiles(delta_seconds)
        if self.session.phase not in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT):
            return
        aircrafts = getattr(self, "aircrafts", {}) or (
            {self.aircraft.id: self.aircraft} if self.aircraft is not None else {}
        )
        if not aircrafts:
            return

        is_multi_weapon = self.session.held_weapon == WeaponKind.MULTI_ANTI_AIRCRAFT
        whitebox_scale = 1.0
        if self.session.profile is not None:
            whitebox_scale = effective_whitebox_scale(
                self.session.profile,
                config=self.session.progression_config,
            )
        ordinary_lock_frame_size = config.AA_LOCK_FRAME_SIZE * whitebox_scale
        lock_frame_size = ordinary_lock_frame_size * (
            config.AA_MULTI_LOCK_FRAME_MULTIPLIER if is_multi_weapon else 1.0
        )
        projections = self.scene.project_aircraft_targets(
            self.scene.aircraft_entities,
            lock_frame_size=lock_frame_size,
        )
        self._aircraft_screen_targets = projections
        current_id = (
            self.multi_lock_tracker.target_ids[0]
            if is_multi_weapon and self.multi_lock_tracker.target_ids
            else self.lock_tracker.target_aircraft_id
        )
        current_projection = projections.get(current_id) if current_id is not None else None
        # A target remains sticky through the 0.75 s decay buffer, even while
        # another aircraft becomes a closer candidate.
        if (
            current_id is not None
            and (
                self.multi_lock_tracker.lock_progress.get(current_id, 0.0)
                if is_multi_weapon
                else self.lock_tracker.progress
            ) > 0.0
            and current_id in aircrafts
            and aircrafts[current_id].phase not in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED)
        ):
            target_projection = current_projection
        else:
            target_projection = select_lock_target(
                tuple(projections.values()),
                current_target_id=None,
                lock_progress=(
                    self.multi_lock_tracker.lock_progress.get(current_id, 0.0)
                    if is_multi_weapon and current_id is not None
                    else self.lock_tracker.progress
                ),
            )
            if target_projection is not None:
                current_id = target_projection.aircraft_id
            else:
                current_id = None
            self.lock_tracker.set_target(current_id)

        has_anti_air = self.session.held_weapon in (
            WeaponKind.ANTI_AIRCRAFT,
            WeaponKind.MULTI_ANTI_AIRCRAFT,
        )
        scope_active = has_anti_air and self.session.anti_air_scope_enabled
        if (
            scope_active
            and target_projection is not None
            and (
                self.session.profile is None
                or has_upgrade(self.session.profile, "aa_aim_assist")
            )
        ):
            self.scene.apply_aircraft_aim_assist(target_projection, delta_seconds)
            projections = self.scene.project_aircraft_targets(
                self.scene.aircraft_entities,
                lock_frame_size=lock_frame_size,
            )
            self._aircraft_screen_targets = projections
            target_projection = projections.get(current_id) if current_id is not None else None

        self._aircraft_screen_target = target_projection
        if is_multi_weapon:
            self.lock_tracker.set_scope_enabled(False)
            self.multi_lock_tracker.update(
                projections,
                delta_seconds,
                scope_enabled=scope_active,
            )
            eligible_ids = tuple(
                target_id
                for target_id, projection in sorted(projections.items())
                if projection.visible and projection.in_lock_frame
            )
            if self.multi_anti_aircraft is not None:
                self.multi_anti_aircraft.set_targets(eligible_ids)
            if self.multi_lock_tracker.all_targets_ready:
                lock_state = LockState.GREEN_READY
            elif any(progress > 0.0 for progress in self.multi_lock_tracker.lock_progress.values()):
                lock_state = LockState.RED_TRACKING
            else:
                lock_state = LockState.WHITE
            self.session.lock_state = lock_state
            self.session.lock_elapsed = max(
                self.multi_lock_tracker.lock_progress.values(),
                default=0.0,
            ) * self.multi_lock_tracker.lock_duration
            self.session.target_in_zone = False
        else:
            self.multi_lock_tracker.set_scope_enabled(False)
            if self.multi_anti_aircraft is not None:
                self.multi_anti_aircraft.target_aircraft_ids.clear()
            self.lock_tracker.set_scope_enabled(scope_active)
            lock_state = self.lock_tracker.update(
                target_visible=bool(target_projection is not None and target_projection.visible),
                target_in_frame=bool(target_projection is not None and target_projection.in_lock_frame),
                delta_seconds=delta_seconds,
                target_aircraft_id=current_id,
            )
            if self.anti_aircraft is not None:
                self.anti_aircraft.lock_state = lock_state
                self.anti_aircraft.lock_elapsed = self.lock_tracker.lock_elapsed
                self.anti_aircraft.target_aircraft_id = self.lock_tracker.target_aircraft_id
                self.anti_aircraft.target_in_zone = self.lock_tracker.target_in_frame
            self.session.lock_state = lock_state
            self.session.lock_elapsed = self.lock_tracker.lock_elapsed
            self.session.target_in_zone = self.lock_tracker.target_in_frame
        if runtime is not None:
            runtime.set_active_target(self.lock_tracker.target_aircraft_id)
        active_target_id = (
            self.multi_lock_tracker.target_ids[0]
            if is_multi_weapon and self.multi_lock_tracker.target_ids
            else self.lock_tracker.target_aircraft_id
        )
        self.session.active_aircraft_id = active_target_id or (
            runtime.alive_aircraft_ids[0] if runtime is not None and runtime.alive_aircraft_ids else self.session.active_aircraft_id
        )
        self.session.active_aircraft_type = (
            runtime.aircraft_types[self.session.active_aircraft_id]
            if runtime is not None and self.session.active_aircraft_id in runtime.aircraft_types
            else (aircrafts[self.session.active_aircraft_id].aircraft_type
                  if self.session.active_aircraft_id in aircrafts else None)
        )
        if (
            not is_multi_weapon
            and lock_state == LockState.GREEN_READY
            and target_projection is not None
            and target_projection.in_lock_frame
        ):
            target_aircraft = aircrafts.get(self.lock_tracker.target_aircraft_id)
            if target_aircraft is not None:
                target_aircraft.mark_locked()
                if runtime is not None:
                    self.session.sync_aircraft_phase(target_aircraft.id, target_aircraft.phase)

    def _update_ground_combat(self, delta_seconds: float) -> None:
        encounter = self._current_ground_encounter()
        if encounter is None:
            if self._wave_clear_ready():
                self._complete_encounter()
            return
        # Descent belongs to each CrewMember.  Updating it before the existing
        # ground pass keeps a newly landed member eligible for ground rules in
        # the same frame while airborne members remain fully targetable.
        for member in encounter.crew:
            member.advance_descent(delta_seconds)
        self.scene.update_crew(encounter)
        advance_crew_behavior(encounter, delta_seconds)
        self.scene.update_crew(encounter)
        self._update_auto_defense_turrets(encounter)
        city_destroyed = apply_city_damage(encounter, self.city, delta_seconds)
        self.session.city_health = self.city.health
        if self.session.run_state is not None:
            self.session.run_state.city_health = self.city.health
        if city_destroyed:
            self.session.transition(SessionEvent.CITY_DESTROYED)
            if self.session.profile is not None:
                self._finish_profile_failure("城市被摧毀")
                return
            self._present_game_over()
            return
        player_position = self.scene.player_position()
        for member in encounter.crew:
            if not member.alive or (
                member.behavior_state != CrewBehaviorState.IN_COVER and not member.at_city
            ):
                continue
            member.update_attack_cooldown(delta_seconds)
            crew_entity = self.scene.crew_entities.get(member.id)
            if crew_entity is None or not member.ready_to_attack():
                continue
            if distance_xz(player_position, crew_entity.world_position) > 38.0:
                continue
            member.mark_attacked()
            attack_event_id = f"{encounter.id}:{member.id}:attack-{member.attack_sequence}"
            if attack_event_id not in self._tracer_event_ids:
                self._tracer_event_ids.add(attack_event_id)
                self.scene.create_ground_tracer(
                    GroundTracerEffect(
                        id=f"tracer-{attack_event_id}",
                        start_position=(
                            float(crew_entity.world_position.x),
                            float(crew_entity.world_position.y),
                            float(crew_entity.world_position.z),
                        ),
                        target_position=(
                            float(player_position.x),
                            float(player_position.y),
                            float(player_position.z),
                        ),
                    )
                )
            if apply_enemy_hit(self.session, config.CREW_DAMAGE):
                if self.session.profile is not None:
                    self._finish_profile_failure("玩家生命值歸零")
                    return
                self._present_game_over()
                return
        self.scene.update_crew(encounter)
        if self._wave_clear_ready():
            self._complete_encounter()

    def _update_auto_defense_turrets(
        self,
        encounter: Optional[GroundEncounter] = None,
    ) -> None:
        """更新短射程固定砲塔與每次開火一發的地面曳光回饋。"""

        encounter = encounter or self._current_ground_encounter()
        if encounter is None or not getattr(self, "turrets", None):
            return
        members = tuple(encounter.crew)
        for turret in self.turrets:
            current = encounter.find(turret.target_id) if turret.target_id else None
            if (
                current is None
                or select_turret_target(
                    turret.position,
                    (current,),
                    max_range=config.AUTO_DEFENSE_MAX_RANGE,
                    allow_boss=True,
                )
                is None
            ):
                target = select_turret_target(
                    turret.position,
                    members,
                    max_range=config.AUTO_DEFENSE_MAX_RANGE,
                    allow_boss=True,
                )
                turret.assign_target(getattr(target, "id", None))
            if not turret.can_fire:
                continue
            target = encounter.find(turret.target_id) if turret.target_id else None
            damage = (
                auto_defense_damage_for_target(target, turret.damage)
                if target is not None
                else 0
            )
            if target is None or damage <= 0:
                turret.release_target()
                continue
            if not turret.mark_fired():
                continue
            tracer_id = f"auto-defense:{turret.id}:{target.id}:{turret.shot_sequence}"
            tracer_event_ids = getattr(self, "_tracer_event_ids", set())
            if tracer_id not in tracer_event_ids:
                tracer_event_ids.add(tracer_id)
                try:
                    self.scene.create_ground_tracer(
                        GroundTracerEffect(
                            id=tracer_id,
                            start_position=turret.position,
                            target_position=target.position,
                        )
                    )
                except Exception:
                    # Visual feedback is optional; the already-fired gameplay
                    # shot must still resolve exactly once.
                    pass
            if damage_crew_member(
                encounter,
                target.id,
                damage,
                self.session,
            ):
                self.scene.remove_crew_member(target.id)
                turret.release_target()
        self.scene.update_auto_defense_turrets(self.turrets)

    def _interact(self) -> None:
        """006 規定 E 完全無效果。"""

        return

    def _select_weapon(self, requested_weapon: WeaponKind) -> None:
        """切換已解鎖槽位；新流程不建立、拾取或丟棄實體。"""

        if self.session.profile is not None:
            previous_weapon = self.session.held_weapon
            if not self.session.select_weapon(requested_weapon):
                return
            if self.player.held_weapon == requested_weapon:
                return
            if previous_weapon != requested_weapon:
                # Every weapon-family change gets the same transient reset.
                # Active missiles intentionally survive; they are independent
                # projectiles and are cleared only at a terminal boundary.
                self._reset_airstrike_guidance(clear_missiles=False)
            self.player.held_weapon = requested_weapon
            self.player.aim_mode = requested_weapon.value
            if requested_weapon == WeaponKind.SNIPER and self.sniper is not None:
                self.sniper.scope_enabled = False
            self.scene.set_scope_enabled(False)
            return

        if not inventory_selection_allowed(self.session.phase, requested_weapon):
            return

        pickup = {
            WeaponKind.ANTI_AIRCRAFT: self.anti_aircraft,
            WeaponKind.SNIPER: self.sniper,
            WeaponKind.PISTOL: self.pistol,
        }.get(requested_weapon)
        if pickup is None:
            return

        if self.session.held_weapon == requested_weapon:
            return

        self._unequip_for_inventory_switch()
        pickup.available = True
        pickup.holder = None
        if not self.player.pick_up(pickup):
            return

        self.session.held_weapon = requested_weapon
        if requested_weapon == WeaponKind.ANTI_AIRCRAFT:
            self._reset_airstrike_guidance(clear_missiles=False)
            if self.scene.world is not None:
                self.scene.world.anti_aircraft_pickup.enabled = False
        elif requested_weapon == WeaponKind.SNIPER:
            self.sniper.scope_enabled = False
            self.player.aim_mode = "SNIPER"
            self.scene.set_scope_enabled(False)
            if self.scene.world is not None:
                self.scene.world.sniper_pickup.enabled = False
        else:
            self.player.aim_mode = "PISTOL"
            self.scene.set_scope_enabled(False)

    def _unequip_for_inventory_switch(self) -> None:
        """Release the current slot without spawning a physical ground pickup."""

        if self.session.held_weapon == WeaponKind.ANTI_AIRCRAFT and self.anti_aircraft is not None:
            self.anti_aircraft.available = True
            self.anti_aircraft.holder = None
        elif self.session.held_weapon == WeaponKind.SNIPER and self.sniper is not None:
            self.sniper.available = True
            self.sniper.holder = None
            self.sniper.scope_enabled = False
        elif self.session.held_weapon == WeaponKind.PISTOL and self.pistol is not None:
            self.pistol.available = True
            self.pistol.holder = None
        self.player.held_weapon = None
        self.player.aim_mode = "NONE"
        self.session.held_weapon = None
        self._reset_airstrike_guidance(clear_missiles=False)
        self.scene.set_scope_enabled(False)

    def _drop_weapon(self) -> None:
        """006 規定 G 完全無效果。"""

        return

    def _toggle_scope(self) -> None:
        if self.session.held_weapon in (
            WeaponKind.ANTI_AIRCRAFT,
            WeaponKind.MULTI_ANTI_AIRCRAFT,
        ):
            self._toggle_anti_air_scope()
        else:
            self._toggle_sniper_scope()

    def _toggle_anti_air_scope(self) -> None:
        if self.session.held_weapon not in (
            WeaponKind.ANTI_AIRCRAFT,
            WeaponKind.MULTI_ANTI_AIRCRAFT,
        ) or self.anti_aircraft is None:
            return
        enabled = not self.session.anti_air_scope_enabled
        self.session.set_anti_air_scope(enabled)
        self.lock_tracker.set_scope_enabled(enabled)
        self.scene.set_scope_enabled(enabled, anti_air=True)
        if not enabled:
            self._reset_airstrike_guidance(clear_missiles=False)

    def _toggle_sniper_scope(self) -> None:
        if self.session.held_weapon != WeaponKind.SNIPER or self.sniper is None:
            return
        self.sniper.toggle_scope()
        self.player.aim_mode = "SNIPER_SCOPE" if self.sniper.scope_enabled else "SNIPER"
        self.scene.set_scope_enabled(self.sniper.scope_enabled)

    def _fire_current_weapon(self) -> None:
        if self.session.profile is not None:
            if self.session.held_weapon in (
                WeaponKind.ANTI_AIRCRAFT,
                WeaponKind.MULTI_ANTI_AIRCRAFT,
            ):
                if self.session.held_weapon == WeaponKind.MULTI_ANTI_AIRCRAFT:
                    self._fire_multi_anti_aircraft()
                else:
                    self._fire_anti_aircraft()
            elif self.session.held_weapon == WeaponKind.SNIPER:
                self._fire_sniper()
            elif self.session.held_weapon == WeaponKind.PISTOL:
                self._fire_pistol()
            elif self.session.held_weapon == WeaponKind.RPG:
                self._fire_rpg()
            return
        if (
            self.session.phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT)
            and self.session.held_weapon == WeaponKind.ANTI_AIRCRAFT
        ):
            self._fire_anti_aircraft()
        elif (
            self.session.phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
            and self.session.held_weapon == WeaponKind.SNIPER
        ):
            self._fire_sniper()
        elif (
            self.session.phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
            and self.session.held_weapon == WeaponKind.PISTOL
        ):
            self._fire_pistol()

    def _fire_rpg(self) -> None:
        """以中心射線目標作為爆炸中心，對唯一敵人快照結算一次。"""

        if (
            self.session.phase not in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
            )
            or self.rpg is None
            or not self.rpg.can_fire()
        ):
            return
        # RunState is the authoritative aggregate for the profile flow.  Keep
        # a local reference so one explosion always resolves against the same
        # encounter even if a scene callback removes a visual entity midway
        # through the hit loop.
        encounter = self._current_ground_encounter()
        target_id = self.scene.crew_under_center(config.PISTOL_MAX_RANGE)
        target: Optional[object] = None
        if target_id is not None and encounter is not None:
            target = encounter.find(target_id)
        if target is None or not is_valid_target(
            WeaponKind.RPG,
            target,
            distance=distance_xz(self.scene.player_position(), getattr(target, "position", self.scene.player_position())),
            cooldown_remaining=self.rpg.fire_cooldown,
            ammo_remaining=self.rpg.ammo_remaining,
            max_range=config.PISTOL_MAX_RANGE,
        ):
            return
        center = tuple(float(value) for value in getattr(target, "position", (0.0, 0.0, 0.0)))
        self._rpg_explosion_sequence += 1
        explosion_id = f"rpg-{self._rpg_explosion_sequence:03d}"
        if not self.rpg.mark_fired(explosion_id):
            return
        self._create_rpg_projectile(explosion_id, center)
        if self.session.profile is not None:
            self.rpg.fire_cooldown = effective_cooldown(
                self.session.progression_config.rpg_cooldown_seconds,
                self.session.profile,
                config=self.session.progression_config,
            )
            runtime_state = getattr(self.session, "run_state", None)
            if runtime_state is not None:
                runtime_state.weapon_runtime[WeaponKind.RPG].mark_fired(
                    runtime_state.weapon_runtime[WeaponKind.RPG].cooldown_duration
                )
        enemies: list[object] = list(getattr(self, "aircrafts", {}).values())
        if encounter is not None:
            enemies.extend(encounter.crew)
        hit_ids = apply_rpg_explosion(
            center,
            enemies,
            radius=self.rpg.explosion_radius,
            damage=self.rpg.damage,
            explosion_id=explosion_id,
            hit_registry=self.rpg.explosion_hit_ids,
        )
        self.scene.create_rpg_explosion(center, self.rpg.explosion_radius)
        for hit_id in hit_ids:
            aircraft = getattr(self, "aircrafts", {}).get(hit_id)
            if aircraft is not None and aircraft.phase == AircraftPhase.DESTROYED:
                self._on_aircraft_destroyed(hit_id)
            if encounter is not None:
                member = encounter.find(hit_id)
                if member is not None and not member.alive:
                    self.session.stats.record_once(
                        f"enemy-defeated:{hit_id}",
                        "enemy_defeated",
                    )
                    encounter.record_crew_cleared(hit_id)
                    self.scene.remove_crew_member(hit_id)
        if encounter is not None:
            encounter.refresh_cleared()
        self._hit_feedback_seconds = 0.6 if hit_ids else 0.0
        # RPG can defeat the final ground batch in one callback.  Always run
        # the aggregate clear predicate after the batch is accounted for;
        # this also covers a previously cleared encounter waiting for the
        # last aircraft/drop decision.
        self._try_complete_encounter()

    def _create_rpg_projectile(
        self,
        explosion_id: str,
        target_position: tuple[float, float, float],
    ) -> None:
        """Create visual RPG feedback without changing the damage timeline."""

        camera_position = getattr(camera, "world_position", None)
        camera_forward = getattr(camera, "forward", None)
        if camera_position is None:
            camera_position = self.scene.player_position()
        try:
            if camera_forward is None:
                start_position = (
                    float(camera_position.x),
                    float(camera_position.y),
                    float(camera_position.z),
                )
            else:
                start_position = (
                    float(camera_position.x) + float(camera_forward.x) * 1.5,
                    float(camera_position.y) + float(camera_forward.y) * 1.5,
                    float(camera_position.z) + float(camera_forward.z) * 1.5,
                )
        except (AttributeError, TypeError, ValueError):
            player_position = self.scene.player_position()
            start_position = (
                float(player_position.x),
                float(player_position.y),
                float(player_position.z),
            )
        projectile = RPGProjectileEffect(
            id=f"{explosion_id}-projectile",
            start_position=start_position,
            target_position=target_position,
        )
        create_projectile = getattr(self.scene, "create_rpg_projectile", None)
        if not callable(create_projectile):
            return
        try:
            create_projectile(projectile)
        except Exception:
            # A visual adapter failure must never undo an already valid RPG
            # shot or make its gameplay damage happen twice.
            return

    def _fire_multi_anti_aircraft(self) -> None:
        """Revalidate the complete set, then create one guided missile per ID."""

        if self.multi_anti_aircraft is None or self.session.phase not in (
            GamePhase.AIRSTRIKE,
            GamePhase.HYBRID_COMBAT,
            GamePhase.GROUND_COMBAT,
        ):
            return
        if not self.session.anti_air_scope_enabled:
            return
        ready_ids = self.multi_lock_tracker.fireable_targets()
        if not ready_ids or self.multi_anti_aircraft.fire_cooldown > 0.0:
            return
        runtime_state = getattr(self.session, "run_state", None)
        runtime_weapon = (
            runtime_state.weapon_runtime.get(WeaponKind.MULTI_ANTI_AIRCRAFT)
            if runtime_state is not None
            else None
        )
        if runtime_weapon is not None and not runtime_weapon.can_fire:
            return
        targets = getattr(self, "aircrafts", {})
        player_position = self.scene.player_position()
        projections = getattr(self, "_aircraft_screen_targets", {})
        valid_ids: list[str] = []
        for target_id in ready_ids:
            target = targets.get(target_id)
            projection = projections.get(target_id) if hasattr(projections, "get") else None
            if (
                target is None
                or projection is None
                or not bool(getattr(projection, "visible", False))
                or not bool(getattr(projection, "in_lock_frame", False))
                or not bool(getattr(projection, "eligible", True))
                or not is_valid_target(
                WeaponKind.MULTI_ANTI_AIRCRAFT,
                target,
                distance=distance_xz(player_position, target.position),
                cooldown_remaining=self.multi_anti_aircraft.fire_cooldown,
                max_range=config.SNIPER_MAX_RANGE,
                )
            ):
                return
            valid_ids.append(target_id)
        if not valid_ids:
            return

        sequence_start = getattr(self, "_missile_sequence", 0) + 1
        volley_id = f"multi-volley-{sequence_start:03d}"
        created: list[GuidedMissile] = []
        try:
            for target_id in valid_ids:
                missile = self._create_guided_missile(target_id)
                created.append(missile)
                self.active_missiles[missile.id] = missile
                self.session.active_missile_ids.add(missile.id)
                self.scene.create_guided_missile(missile)
        except Exception:
            for missile in created:
                self.scene.remove_guided_missile(missile.id)
                self.active_missiles.pop(missile.id, None)
                self.session.active_missile_ids.discard(missile.id)
            return

        missile_pairs = tuple((target_id, missile.id) for target_id, missile in zip(valid_ids, created))
        volley = MissileVolley(
            volley_id=volley_id,
            weapon=WeaponKind.MULTI_ANTI_AIRCRAFT,
            target_ids=tuple(valid_ids),
            missile_ids=missile_pairs,
            cooldown_applied=True,
        )
        if not hasattr(self, "active_volleys"):
            self.active_volleys = {}
        self.active_volleys[volley_id] = volley
        self.multi_anti_aircraft.set_targets(valid_ids)
        self.multi_anti_aircraft.mark_fired(volley_id)
        if self.session.profile is not None:
            self.multi_anti_aircraft.fire_cooldown = effective_cooldown(
                config.AA_FIRE_COOLDOWN_SECONDS,
                self.session.profile,
                config=self.session.progression_config,
            )
            if runtime_state is not None:
                runtime_multi_weapon = runtime_state.weapon_runtime.get(
                    WeaponKind.MULTI_ANTI_AIRCRAFT
                )
                if runtime_multi_weapon is not None:
                    runtime_multi_weapon.mark_fired(runtime_multi_weapon.cooldown_duration)
        self.multi_lock_tracker.mark_fired(volley_id)

    def _create_guided_missile(self, target_id: str) -> GuidedMissile:
        """Create a target-bound missile shell without registering or firing it."""

        self._missile_sequence = getattr(self, "_missile_sequence", 0) + 1
        missile_id = f"{target_id}-missile-{self._missile_sequence:03d}"
        missile_start = camera.world_position + camera.forward * 1.5
        return GuidedMissile(
            id=missile_id,
            target_aircraft_id=target_id,
            position=(float(missile_start.x), float(missile_start.y), float(missile_start.z)),
            forward=(float(camera.forward.x), float(camera.forward.y), float(camera.forward.z)),
        )

    def _fire_anti_aircraft(self) -> None:
        aircrafts = getattr(self, "aircrafts", {})
        if not aircrafts and self.aircraft is not None:
            aircrafts = {self.aircraft.id: self.aircraft}
        target_id = self.lock_tracker.target_aircraft_id or (
            self.anti_aircraft.target_aircraft_id
            if self.anti_aircraft is not None
            else None
        )
        target_aircraft = aircrafts.get(target_id) if target_id is not None else None
        if (
            self.session.phase not in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
            )
            or self.anti_aircraft is None
            or not self.session.anti_air_scope_enabled
            or target_aircraft is None
        ):
            return
        if not can_fire_anti_air(
            self.anti_aircraft.lock_state,
            self.anti_aircraft.fire_cooldown,
            self.session.held_weapon,
            target_in_zone=self.lock_tracker.target_in_frame,
            target_aircraft_id=target_id,
            target_visible=self.lock_tracker.target_visible,
            target_in_frame=self.lock_tracker.target_in_frame,
            scope_enabled=self.session.anti_air_scope_enabled,
        ):
            return

        self._missile_sequence += 1
        missile_id = f"{target_id}-missile-{self._missile_sequence:03d}"
        missile_start = camera.world_position + camera.forward * 1.5
        missile = GuidedMissile(
            id=missile_id,
            target_aircraft_id=target_id,
            position=(float(missile_start.x), float(missile_start.y), float(missile_start.z)),
            forward=(float(camera.forward.x), float(camera.forward.y), float(camera.forward.z)),
        )
        self.active_missiles[missile_id] = missile
        self.session.active_missile_ids.add(missile_id)
        self.scene.create_guided_missile(missile)
        self.anti_aircraft.mark_fired()
        if self.session.profile is not None:
            self.anti_aircraft.fire_cooldown = effective_cooldown(
                config.AA_FIRE_COOLDOWN_SECONDS,
                self.session.profile,
                config=self.session.progression_config,
            )
            runtime_state = getattr(self.session, "run_state", None)
            if runtime_state is not None:
                runtime_state.weapon_runtime[WeaponKind.ANTI_AIRCRAFT].mark_fired(
                    runtime_state.weapon_runtime[WeaponKind.ANTI_AIRCRAFT].cooldown_duration
                )
        self._reset_lock_after_shot()

    def _fire_sniper(self) -> None:
        encounter = self._current_ground_encounter()
        if (
            self.session.phase not in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
            )
            or encounter is None
            or self.sniper is None
        ):
            return
        if not can_fire_sniper(self.sniper.fire_cooldown, self.session.held_weapon):
            return
        target_id = self.scene.crew_under_center(config.SNIPER_MAX_RANGE)
        if target_id is None:
            return
        target_entity = self.scene.crew_entities.get(target_id)
        if target_entity is None:
            return
        target_distance = distance_xz(
            self.scene.player_position(),
            target_entity.world_position,
        )
        if not can_fire_sniper(
            self.sniper.fire_cooldown,
            self.session.held_weapon,
            target_distance,
        ):
            return
        self.sniper.mark_fired(target_id)
        if self.session.profile is not None:
            self.sniper.fire_cooldown = effective_cooldown(
                config.SNIPER_FIRE_COOLDOWN_SECONDS,
                self.session.profile,
                config=self.session.progression_config,
            )
            runtime_state = getattr(self.session, "run_state", None)
            if runtime_state is not None:
                runtime_state.weapon_runtime[WeaponKind.SNIPER].mark_fired(
                    runtime_state.weapon_runtime[WeaponKind.SNIPER].cooldown_duration
                )
        if target_id is None:
            return
        self._hit_feedback_seconds = 0.6
        if damage_crew_member(encounter, target_id, 1, self.session):
            self.scene.remove_crew_member(target_id)
            if encounter.cleared:
                self._complete_encounter()

    def _fire_pistol(self) -> None:
        encounter = self._current_ground_encounter()
        if (
            self.session.phase not in (
                GamePhase.AIRSTRIKE,
                GamePhase.HYBRID_COMBAT,
                GamePhase.GROUND_COMBAT,
            )
            or encounter is None
            or self.pistol is None
        ):
            return
        target_id = self.scene.crew_under_center(config.PISTOL_MAX_RANGE)
        if target_id is None:
            return
        target_entity = self.scene.crew_entities.get(target_id)
        if target_entity is None:
            return
        target_distance = distance_xz(
            self.scene.player_position(),
            target_entity.world_position,
        )
        if not can_fire_pistol(
            self.pistol.fire_cooldown,
            target_distance,
            self.session.held_weapon,
        ):
            return
        self.pistol.mark_fired(target_id)
        if self.session.profile is not None:
            self.pistol.fire_cooldown = effective_cooldown(
                config.PISTOL_FIRE_COOLDOWN_SECONDS,
                self.session.profile,
                config=self.session.progression_config,
            )
            runtime_state = getattr(self.session, "run_state", None)
            if runtime_state is not None:
                runtime_state.weapon_runtime[WeaponKind.PISTOL].mark_fired(
                    runtime_state.weapon_runtime[WeaponKind.PISTOL].cooldown_duration
                )
        if damage_crew_member(encounter, target_id, 1, self.session):
            self.scene.remove_crew_member(target_id)
        self._hit_feedback_seconds = 0.6
        if encounter.cleared:
            self._complete_encounter()

    def _current_ground_encounter(self) -> Optional[GroundEncounter]:
        """Return the active encounter from the controller or RunState."""

        run_state = getattr(self.session, "run_state", None)
        candidate = getattr(run_state, "ground_encounter", None)
        if isinstance(candidate, GroundEncounter):
            # RunState is authoritative for the profile flow.  Repair the
            # controller cache as soon as a stale or missing visual reference
            # is observed so every ground path follows the same encounter.
            self.encounter = candidate
            return candidate
        encounter = getattr(self, "encounter", None)
        if not isinstance(encounter, GroundEncounter):
            return None
        if run_state is not None:
            run_state.ground_encounter = encounter
        return encounter

    def _try_complete_encounter(self) -> bool:
        """Refresh ground state and settle when the whole wave is clear."""

        encounter = self._current_ground_encounter()
        if encounter is not None:
            encounter.refresh_cleared()
        if not self._wave_clear_ready():
            return False
        self._complete_encounter()
        return True

    def _wave_clear_ready(self) -> bool:
        """Return the single named predicate used by every clear boundary."""

        runtime = self.session.wave_runtime
        if runtime is None:
            return False
        encounter = self._current_ground_encounter()
        ground_cleared = encounter is None or encounter.cleared
        return runtime.can_complete_wave(ground_cleared)

    def _clear_current_wave_visuals(self) -> None:
        """Remove current-wave combat entities while preserving short effects."""

        self._reset_airstrike_guidance(clear_missiles=True)
        self.scene.clear_dynamic(clear_effects=False)
        self.encounter = None
        self.aircraft = None
        self.aircrafts.clear()
        getattr(self, "turrets", []).clear()
        self._aircraft_screen_target = None
        getattr(self, "_aircraft_screen_targets", {}).clear()
        getattr(self, "_tracer_event_ids", set()).clear()
        self.lock_tracker.set_scope_enabled(False)
        if self.sniper is not None:
            self.sniper.scope_enabled = False
        self.scene.set_scope_enabled(False)
        self.reset_weapon_cooldowns()
        if self.scene.world is not None:
            self.scene.world.sniper_pickup.enabled = False

    def _complete_encounter(self) -> None:
        if self.session.profile is not None and self.session.run_state is not None:
            if not self._wave_clear_ready():
                return
            settlement = self.session.complete_sublevel_once(
                self.session.run_state.attempt_id
            )
            self._clear_current_wave_visuals()
            self.scene.set_gameplay_enabled(False)
            self.hud.update_profile_summary(
                self.session.profile,
                next_level=self.session.session_progress.next_play_level,
            )
            self.hud.show_main_menu()
            if settlement is not None:
                self.hud.update_shop_details(
                    self.session.profile,
                    result_message=f"小關 {settlement.level_key} 完成，獲得 {settlement.awarded_coins} 金幣",
                )
            return
        runtime = self.session.wave_runtime
        if runtime is not None:
            if not self._wave_clear_ready():
                return
            encounter_id = (
                self.encounter.id
                if self.encounter is not None
                else runtime.ground_encounter_id
            )
            event_id = f"wave-cleared:{runtime.wave.wave_number}"
            final_wave = self.wave_director.is_final_wave(runtime.wave.wave_number)
            next_plan = None if final_wave else self.wave_director.plan_wave(runtime.wave.wave_number + 1)
            self._clear_current_wave_visuals()
            self.session.transition(
                SessionEvent.WAVE_CLEARED,
                event_id=event_id,
                encounter_id=encounter_id,
                wave_plan=next_plan,
                ground_cleared=True,
            )
            if self.session.phase == GamePhase.VICTORY:
                self._present_victory()
                return
            if self.session.phase == GamePhase.AIRSTRIKE:
                if self.session.held_weapon != WeaponKind.ANTI_AIRCRAFT:
                    self.scene.move_weapon_pickup(
                        "anti_aircraft",
                        config.DEFENSE_POINT_POSITION,
                        enabled=True,
                    )
                self._spawn_current_aircraft()
            return

        if self.encounter is None:
            return

        # Legacy single-aircraft transition retained for callers that do not
        # initialize a keyed WaveRuntime.
        self._reset_airstrike_guidance(clear_missiles=True)
        encounter_id = self.encounter.id
        next_plan = (
            self.wave_director.plan_wave(self.session.wave.wave_number + 1)
            if self.session.wave.is_last_aircraft
            else None
        )
        self.session.transition(
            SessionEvent.CREW_CLEARED,
            encounter_id=encounter_id,
            wave_plan=next_plan,
        )
        self.scene.clear_dynamic(clear_effects=False)
        self.encounter = None
        self.aircraft = None
        self._aircraft_screen_target = None
        self.lock_tracker.set_scope_enabled(False)
        if self.sniper is not None:
            self.sniper.scope_enabled = False
        self.scene.set_scope_enabled(False)
        if self.scene.world is not None:
            self.scene.world.sniper_pickup.enabled = False
        if self.session.held_weapon != WeaponKind.ANTI_AIRCRAFT:
            self.scene.move_weapon_pickup(
                "anti_aircraft",
                config.DEFENSE_POINT_POSITION,
                enabled=True,
            )
        if self.session.phase == GamePhase.AIRSTRIKE:
            self._spawn_current_aircraft()

    def _present_game_over(self) -> None:
        if self.session.phase != GamePhase.GAME_OVER or self._game_over_presented:
            return
        self._game_over_presented = True
        self._game_over_snapshot = self.session.stats.snapshot()
        self._reset_airstrike_guidance(clear_missiles=True)
        self.reset_weapon_cooldowns()
        self._aircraft_screen_target = None
        getattr(self, "_aircraft_screen_targets", {}).clear()
        getattr(self, "_tracer_event_ids", set()).clear()
        if hasattr(self.scene, "clear_ground_tracers"):
            self.scene.clear_ground_tracers()
        if hasattr(self.scene, "clear_dynamic"):
            self.scene.clear_dynamic(clear_effects=False)
        getattr(self, "aircrafts", {}).clear()
        self.aircraft = None
        self.encounter = None
        self.scene.set_gameplay_enabled(False)
        self.scene.set_scope_enabled(False)
        self.hud.show_game_over(self.session.stats)

    def _finish_profile_failure(self, reason: str) -> None:
        """將新流程的死亡結果整理後返回同一存檔主選單。"""

        self._reset_airstrike_guidance(clear_missiles=True)
        self.scene.clear_dynamic(clear_effects=False)
        self.aircrafts.clear()
        self.aircraft = None
        self.encounter = None
        self._aircraft_screen_target = None
        self._aircraft_screen_targets.clear()
        self._tracer_event_ids.clear()
        self.scene.set_scope_enabled(False)
        self.scene.set_gameplay_enabled(False)
        self.hud.update_profile_summary(
            self.session.profile,
            warning=f"本局已結束：{reason}；重生資格已開放。",
            next_level=self.session.session_progress.next_play_level,
        )
        self.hud.show_main_menu()

    def _present_victory(self) -> None:
        if self.session.phase != GamePhase.VICTORY or self._victory_presented:
            return
        self._victory_presented = True
        self._game_over_snapshot = self.session.stats.snapshot()
        self._reset_airstrike_guidance(clear_missiles=True)
        self.reset_weapon_cooldowns()
        self._aircraft_screen_target = None
        getattr(self, "_aircraft_screen_targets", {}).clear()
        getattr(self, "_tracer_event_ids", set()).clear()
        if hasattr(self.scene, "clear_ground_tracers"):
            self.scene.clear_ground_tracers()
        if hasattr(self.scene, "clear_dynamic"):
            self.scene.clear_dynamic(clear_effects=False)
        getattr(self, "aircrafts", {}).clear()
        self.aircraft = None
        self.encounter = None
        self.scene.set_gameplay_enabled(False)
        self.scene.set_scope_enabled(False)
        self.hud.show_victory(self.session.stats)

    def _refresh_hud(self) -> None:
        active_projection = self._aircraft_screen_target
        visible = bool(active_projection is not None and active_projection.visible)
        target_position = active_projection.hud_position if active_projection is not None else None
        target_radius = active_projection.screen_radius if active_projection is not None else 0.008
        runtime = self.session.wave_runtime
        wave_view = build_wave_status_view(
            runtime,
            active_target_id=self.lock_tracker.target_aircraft_id,
        )

        prompt = ""
        if self.session.phase == GamePhase.AIRSTRIKE:
            if self.session.held_weapon is None:
                prompt = "按數字鍵選擇已解鎖武器"
            elif self.session.held_weapon not in (WeaponKind.ANTI_AIRCRAFT, WeaponKind.MULTI_ANTI_AIRCRAFT):
                prompt = "目前只能以防空武器攻擊飛機；可隨時切換槽位"
            elif self.session.lock_state == LockState.GREEN_READY:
                prompt = "綠框已鎖定，按左鍵發射"
            else:
                prompt = "將白框對準戰鬥機完成鎖定"
        elif self.session.phase == GamePhase.HYBRID_COMBAT:
            if self.session.held_weapon in (WeaponKind.ANTI_AIRCRAFT, WeaponKind.MULTI_ANTI_AIRCRAFT):
                prompt = (
                    "綠框已鎖定，按左鍵發射；其他武器可攻擊地面敵人"
                    if self.session.lock_state == LockState.GREEN_READY
                    else "防空炮可繼續鎖定；其他武器可攻擊地面敵人"
                )
            elif self.session.held_weapon == WeaponKind.PISTOL:
                prompt = "手槍近距離射擊；可隨時切換其他武器"
            elif self.session.held_weapon == WeaponKind.SNIPER:
                prompt = "右鍵瞄準，左鍵射擊；可隨時切換其他武器"
            elif self.session.held_weapon == WeaponKind.RPG:
                prompt = "RPG 只攻擊爆炸範圍內地面敵人，不攻擊飛機；可隨時切換其他武器"
            else:
                prompt = "可隨時切換已解鎖武器"
        elif self.session.phase == GamePhase.GROUND_COMBAT:
            if self.session.held_weapon is None:
                prompt = "按數字鍵選擇已解鎖武器"
            elif self.session.held_weapon in (WeaponKind.ANTI_AIRCRAFT, WeaponKind.MULTI_ANTI_AIRCRAFT):
                prompt = "防空炮只能攻擊飛機；可切換地面武器"
            elif self.session.held_weapon == WeaponKind.PISTOL:
                prompt = "手槍近距離射擊；可隨時切換其他武器"
            elif self.session.held_weapon == WeaponKind.RPG:
                prompt = "RPG 只攻擊爆炸範圍內地面敵人，不攻擊飛機；可隨時切換其他武器"
            else:
                prompt = "右鍵瞄準，左鍵射擊；可隨時切換其他武器"

        aircrafts = getattr(self, "aircrafts", {})
        if not aircrafts and self.aircraft is not None:
            aircrafts = {self.aircraft.id: self.aircraft}
        impact_times = [
            aircraft.estimated_impact_seconds()
            for aircraft in aircrafts.values()
            if aircraft.phase not in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED)
        ]
        warning = bool(
            self.session.phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT)
            and impact_times
            and warning_active(min(impact_times))
        )
        hit_feedback = "命中！" if self._hit_feedback_seconds > 0 else ""
        run_state = getattr(self.session, "run_state", None)
        level_key = run_state.level if run_state is not None else None
        ammo_text = None
        locked_target_ids = None
        turret_count = None
        if run_state is not None and self.session.held_weapon in run_state.weapon_runtime:
            weapon_runtime = run_state.weapon_runtime[self.session.held_weapon]
            ammo_text = (
                f"彈藥 {weapon_runtime.ammo_remaining}"
                if weapon_runtime.ammo_remaining is not None
                else "彈藥 ∞"
            )
        if self.session.held_weapon == WeaponKind.MULTI_ANTI_AIRCRAFT:
            locked_target_ids = self.multi_lock_tracker.target_ids
        multi_lock_views = (
            self.multi_lock_tracker.build_views(self._aircraft_screen_targets)
            if self.session.held_weapon == WeaponKind.MULTI_ANTI_AIRCRAFT
            else ()
        )
        if getattr(self, "turrets", None):
            turret_count = len(self.turrets)
        active_aircraft_type = wave_view.selected_aircraft_type or self.session.active_aircraft_type
        boss_health = None
        boss_max_health = None
        boss_label = None
        if self.session.wave.is_boss_wave:
            if (
                self.session.phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT)
                and aircrafts
            ):
                boss_aircraft = next(
                    (candidate for candidate in aircrafts.values()
                     if candidate.aircraft_type == AircraftType.ARMORED_BOSS
                     and candidate.phase not in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED)),
                    None,
                )
                if boss_aircraft is not None:
                    boss_health = boss_aircraft.health
                    boss_max_health = boss_aircraft.max_health
                    boss_label = "裝甲飛機 HP"
            if (
                boss_health is None
                and self.session.phase in (GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
                and self.encounter is not None
                and self.encounter.boss_id is not None
            ):
                boss = self.encounter.find(self.encounter.boss_id)
                if boss is not None:
                    boss_health = boss.health
                    boss_max_health = boss.max_health
                    boss_label = "大魔王 HP"
        self.hud.update_session(
            self.session.health,
            self.session.stats,
            self.session.held_weapon,
            phase=self.session.phase,
            warning=warning,
            prompt=prompt,
            hit_feedback=hit_feedback,
            scope_enabled=bool(
                self.session.held_weapon == WeaponKind.SNIPER
                and self.sniper is not None
                and self.sniper.scope_enabled
            ),
            anti_air_scope_enabled=(
                self.session.phase in (GamePhase.AIRSTRIKE, GamePhase.HYBRID_COMBAT, GamePhase.GROUND_COMBAT)
                and self.session.held_weapon in (WeaponKind.ANTI_AIRCRAFT, WeaponKind.MULTI_ANTI_AIRCRAFT)
                and self.session.anti_air_scope_enabled
            ),
            lock_state=self.session.lock_state,
            lock_visible=visible,
            lock_progress=self.lock_tracker.progress,
            lock_target_position=target_position,
            lock_target_radius=target_radius,
            lock_completion_flash=(
                self.lock_tracker.state == LockState.GREEN_READY
                and self.lock_tracker.flash_visible()
            ),
            fps=self._fps_value,
            wave_number=self.session.wave.wave_number,
            aircraft_index=self.session.wave.aircraft_index,
            aircraft_count=self.session.wave.aircraft_count,
            aircraft_type=active_aircraft_type,
            city_health=self.session.city_health,
            boss_health=boss_health,
            boss_max_health=boss_max_health,
            boss_label=boss_label,
            player_view=build_player_status_view(
                self.session.health,
                self.session.max_health,
            ),
            city_view=build_city_status_view(
                self.session.city_health,
                self.session.max_city_health,
            ),
            wave_view=wave_view,
            level_key=level_key,
            maximum_aircraft_count=(self.session.profile.max_aircraft_count if self.session.profile is not None else None),
            profile=self.session.profile,
            ammo_text=ammo_text,
            locked_target_ids=locked_target_ids,
            turret_count=turret_count,
            cooldown_view=weapon_cooldown_view(
                self.session.held_weapon,
                {
                    WeaponKind.ANTI_AIRCRAFT: self.anti_aircraft,
                    WeaponKind.SNIPER: self.sniper,
                    WeaponKind.PISTOL: self.pistol,
                    WeaponKind.RPG: self.rpg,
                    WeaponKind.MULTI_ANTI_AIRCRAFT: self.multi_anti_aircraft,
                },
                gameplay=self.session.phase in (
                    GamePhase.AIRSTRIKE,
                    GamePhase.HYBRID_COMBAT,
                    GamePhase.GROUND_COMBAT,
                ),
                profile=self.session.profile,
                progression_config=self.session.progression_config,
            ),
            multi_lock_views=multi_lock_views,
            anti_air_gui_mode=getattr(
                self,
                "anti_air_gui_mode",
                AntiAirGuiMode.NEW,
            ),
        )

    def _spawn_current_aircraft(self) -> None:
        if self.session.phase != GamePhase.AIRSTRIKE:
            return
        runtime = self.session.wave_runtime
        if runtime is None:
            aircraft_id = self.session.active_aircraft_id or "aircraft-next"
            aircraft_type = self.session.active_aircraft_type or AircraftType.NORMAL
            self.aircraft = Aircraft(
                id=aircraft_id,
                aircraft_type=aircraft_type,
            )
            self.aircrafts = {aircraft_id: self.aircraft}
            self.scene.create_aircraft(self.aircraft)
            return

        self.aircrafts.clear()
        count = len(runtime.aircraft_ids)
        center = (count - 1) / 2.0
        for index, aircraft_id in enumerate(runtime.aircraft_ids):
            aircraft_type = runtime.aircraft_types[aircraft_id]
            offset = (index - center) * config.AIRCRAFT_FORMATION_HORIZONTAL_SPACING
            start = (
                config.AIRCRAFT_START_POSITION[0] + offset,
                config.AIRCRAFT_START_POSITION[1],
                config.AIRCRAFT_START_POSITION[2],
            )
            target = (
                config.AIRCRAFT_TARGET_POSITION[0] + offset,
                config.AIRCRAFT_TARGET_POSITION[1],
                config.AIRCRAFT_TARGET_POSITION[2],
            )
            aircraft = Aircraft(
                id=aircraft_id,
                aircraft_type=aircraft_type,
                start_position=start,
                target_position=target,
            )
            self.aircrafts[aircraft_id] = aircraft
            self.scene.create_aircraft(aircraft)
        active_id = runtime.alive_aircraft_ids[0]
        self.aircraft = self.aircrafts[active_id]
        self.session.active_aircraft_id = active_id
        self.session.active_aircraft_type = runtime.aircraft_types[active_id]


def create_application() -> tuple[Ursina, AirDefenseGame]:
    # Ursina 8.3.0 still calls ``make_editor_gui`` for an onscreen window even
    # when editor_ui_enabled=False.  Some packaged Ursina distributions omit
    # the optional cog texture/font assets, so bypass that editor-only setup
    # while constructing the game window.
    original_make_editor_gui = window.make_editor_gui

    def make_disabled_editor_gui() -> None:
        # Keep the container expected by Ursina's aspect-ratio callback, but
        # omit its optional cog/menu widgets.
        from ursina import Entity

        window.editor_ui = Entity(parent=camera.ui, eternal=True, enabled=False)

    window.make_editor_gui = make_disabled_editor_gui
    icon_path = Path(application.package_folder) / "textures" / "ursina.ico"
    try:
        app = Ursina(
            title=config.APP_TITLE,
            icon=icon_path.as_posix() if icon_path.is_file() else "textures/ursina.ico",
            size=(config.WINDOW_WIDTH, config.WINDOW_HEIGHT),
            fullscreen=False,
            development_mode=False,
            editor_ui_enabled=False,
        )
    finally:
        window.make_editor_gui = original_make_editor_gui
    configure_ui_font()
    window.title = config.APP_TITLE
    window.size = (config.WINDOW_WIDTH, config.WINDOW_HEIGHT)
    window.vsync = config.TARGET_FPS
    if hasattr(window, "fps_counter"):
        window.fps_counter.enabled = True
    if hasattr(window, "exit_button"):
        window.exit_button.visible = True
    camera.clip_plane_far = max(config.MAP_LENGTH, 360.0)
    controller = AirDefenseGame(app)

    def game_input_bridge(key: str) -> None:
        # Ursina's low-level button event uses mouse1/mouse3 names, while the
        # game controller uses the public input names used by its rules.
        normalized_key = {
            "mouse1": "left mouse down",
            "mouse3": "right mouse down",
        }.get(key, key)
        controller.input(normalized_key)

    def game_update_task(task: Task):
        controller.update()
        return task.cont

    # Register directly with Ursina instead of assigning app.input/app.update:
    # Ursina stores its callbacks during construction, so later assignment of
    # those attributes does not replace the stored window callbacks.
    app.accept("buttonDown", game_input_bridge)
    app.taskMgr.add(game_update_task, "air_defense_game_update")
    return app, controller


def configure_ui_font() -> None:
    """Prefer a local Traditional Chinese system font for the HUD."""

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


def main() -> None:
    app, _ = create_application()
    app.run()


if __name__ == "__main__":
    main()
