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
    GroundEncounter,
    Pistol,
    Player,
    SniperRifle,
    TargetBuilding,
)
from .hud import GameHUD
from .rules import (
    EncounterFactory,
    LockOnTracker,
    advance_crew_behavior,
    apply_city_damage,
    apply_enemy_hit,
    can_fire_anti_air,
    can_fire_pistol,
    can_fire_sniper,
    damage_crew_member,
    inventory_selection_allowed,
    resolve_aircraft_outcome,
    WaveDirector,
    warning_active,
)
from .scene import AirDefenseScene, distance_xz
from .state import (
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

    def __init__(self, app: Ursina) -> None:
        self.app = app
        self.session = GameSession()
        self.player = Player()
        self.scene = AirDefenseScene()
        self.hud = GameHUD()
        self.lock_tracker = LockOnTracker()
        self.encounter_factory = EncounterFactory()
        self.wave_director = WaveDirector()
        self.aircraft: Optional[Aircraft] = None
        self.encounter: Optional[GroundEncounter] = None
        self.city = TargetBuilding()
        self.anti_aircraft: Optional[AntiAircraftGun] = None
        self.sniper: Optional[SniperRifle] = None
        self.pistol: Optional[Pistol] = None
        self._game_over_presented = False
        self._hit_feedback_seconds = 0.0
        self._fps_sample_elapsed = 0.0
        self._fps_sample_frames = 0
        self._fps_value: Optional[float] = None

        self.hud.bind_menu_actions(self.start_game, self.quit_game)
        self.hud.bind_return_action(self.return_to_menu)
        self.hud.show_main_menu()
        self.scene.set_gameplay_enabled(False)

    def start_game(self) -> None:
        if self.session.phase != GamePhase.MAIN_MENU:
            return
        self.scene.clear_world()
        first_plan = self.wave_director.plan_wave(1)
        self.session.transition(SessionEvent.START_GAME, wave_plan=first_plan)
        self.player = Player()
        self.city = TargetBuilding()
        self.anti_aircraft = AntiAircraftGun(world_position=config.DEFENSE_POINT_POSITION)
        self.sniper = SniperRifle(world_position=config.WEAPON_RACK_POSITION)
        self.pistol = Pistol(world_position=config.WEAPON_RACK_POSITION)
        self.lock_tracker.reset()
        self.encounter = None
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

    def quit_game(self) -> None:
        application.quit()

    def return_to_menu(self) -> None:
        if self.session.phase == GamePhase.GAME_OVER:
            self.session.transition(SessionEvent.RETURN_TO_MENU)
        self.scene.clear_world()
        self.aircraft = None
        self.encounter = None
        self.city = TargetBuilding()
        self.anti_aircraft = None
        self.sniper = None
        self.pistol = None
        self.lock_tracker.reset()
        self.scene.set_scope_enabled(False)
        self._game_over_presented = False
        self.hud.show_main_menu()
        self.scene.set_gameplay_enabled(False)

    def input(self, key: str) -> None:
        """Process input before the next object/rule update."""

        if self.session.phase == GamePhase.MAIN_MENU:
            if key in ("enter", "space"):
                self.start_game()
            elif key in ("q", "escape"):
                self.quit_game()
            elif key == "left mouse down":
                # Keep menu actions working even when a window/input backend
                # delivers the click to the game bridge before Ursina's
                # Button mouse handler.
                if self.hud.start_button.hovered:
                    self.start_game()
                elif self.hud.quit_button.hovered:
                    self.quit_game()
            return

        if self.session.phase == GamePhase.GAME_OVER:
            if key in ("enter", "escape"):
                self.return_to_menu()
            elif key == "left mouse down" and self.hud.return_button.hovered:
                self.return_to_menu()
            return

        if key == "e":
            self._interact()
        elif key == "g":
            self._drop_weapon()
        elif key == "1":
            self._select_weapon(WeaponKind.ANTI_AIRCRAFT)
        elif key == "2":
            self._select_weapon(WeaponKind.SNIPER)
        elif key == "3":
            self._select_weapon(WeaponKind.PISTOL)
        elif key == "left mouse down":
            self._fire_current_weapon()
        elif key == "right mouse down":
            self._toggle_sniper_scope()

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
        self._tick_weapon_cooldowns(delta_seconds)

        if self.session.phase in (GamePhase.AIRSTRIKE, GamePhase.GROUND_COMBAT):
            self.session.tick(delta_seconds)

        if self.session.phase == GamePhase.AIRSTRIKE:
            self._update_airstrike(delta_seconds)
        elif self.session.phase == GamePhase.GROUND_COMBAT:
            self._update_ground_combat(delta_seconds)
        elif self.session.phase == GamePhase.GAME_OVER:
            self._present_game_over()

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

    def _update_airstrike(self, delta_seconds: float) -> None:
        if self.aircraft is None:
            return
        self.aircraft.advance(delta_seconds)
        self.scene.update_aircraft(self.aircraft)

        if self.aircraft.path_progress >= 1.0:
            if self.aircraft.phase in (AircraftPhase.DESTROYED, AircraftPhase.IMPACTED):
                return
            self.aircraft.impact()
            self.session.transition(
                SessionEvent.BUILDING_IMPACT,
                aircraft_id=self.aircraft.id,
            )
            self.scene.remove_aircraft()
            self._present_game_over()
            return

        has_anti_air = self.session.held_weapon == WeaponKind.ANTI_AIRCRAFT
        target_visible = has_anti_air and self.scene.aircraft_is_visible(self.scene.aircraft_entity)
        lock_state = self.lock_tracker.update(target_visible, delta_seconds)
        if self.anti_aircraft is not None:
            self.anti_aircraft.lock_state = lock_state
            self.anti_aircraft.lock_elapsed = self.lock_tracker.lock_elapsed
            self.anti_aircraft.target_aircraft_id = self.aircraft.id if target_visible else None
        self.session.lock_state = lock_state
        self.session.lock_elapsed = self.lock_tracker.lock_elapsed
        if lock_state == LockState.GREEN_READY:
            self.aircraft.mark_locked()

    def _update_ground_combat(self, delta_seconds: float) -> None:
        if self.encounter is None:
            return
        advance_crew_behavior(self.encounter, delta_seconds)
        self.scene.update_crew(self.encounter)
        city_destroyed = apply_city_damage(self.encounter, self.city, delta_seconds)
        self.session.city_health = self.city.health
        if city_destroyed:
            self.session.transition(SessionEvent.CITY_DESTROYED)
            self._present_game_over()
            return
        player_position = self.scene.player_position()
        for member in self.encounter.crew:
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
            if apply_enemy_hit(self.session, config.CREW_DAMAGE):
                self._present_game_over()
                return
        self.scene.update_crew(self.encounter)

    def _interact(self) -> None:
        preferred_kind = (
            "anti_aircraft"
            if self.session.phase == GamePhase.AIRSTRIKE
            else "sniper"
        )
        entity = self.scene.interactable_under_center(preferred_kind=preferred_kind)
        if entity is None or self.scene.world is None:
            return
        if entity is self.scene.world.anti_aircraft_pickup:
            if self.session.phase != GamePhase.AIRSTRIKE or self.anti_aircraft is None:
                return
            if not self.scene.is_near(entity.world_position, 3.5):
                return
            if self.player.pick_up(self.anti_aircraft):
                self.session.held_weapon = WeaponKind.ANTI_AIRCRAFT
                entity.enabled = False
            return

        if entity is self.scene.world.sniper_pickup or entity is self.scene.world.weapon_rack:
            if self.session.phase != GamePhase.GROUND_COMBAT or self.sniper is None:
                return
            if not self.scene.is_near(self.scene.world.weapon_rack.world_position, 3.5):
                return
            if self.player.pick_up(self.sniper):
                self.session.held_weapon = WeaponKind.SNIPER
                self.scene.world.sniper_pickup.enabled = False

    def _select_weapon(self, requested_weapon: WeaponKind) -> None:
        """Equip a weapon directly from the three-slot inventory bar."""

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
            self.lock_tracker.reset()
            self.session.lock_state = LockState.WHITE
            self.session.lock_elapsed = 0.0
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
        self.scene.set_scope_enabled(False)

    def _drop_weapon(self) -> None:
        if self.session.held_weapon is None:
            return
        position = self.scene.player_position()
        drop_position = (position.x, max(0.45, position.y - 0.55), position.z)
        dropped = self.player.drop_weapon(drop_position)
        if dropped is None:
            return
        kind = self.session.held_weapon
        self.session.held_weapon = None
        if kind == WeaponKind.ANTI_AIRCRAFT:
            self.anti_aircraft = AntiAircraftGun(world_position=drop_position)
            self.scene.move_weapon_pickup("anti_aircraft", drop_position)
            self.lock_tracker.reset()
            self.session.lock_state = LockState.WHITE
            self.session.lock_elapsed = 0.0
        elif kind == WeaponKind.SNIPER:
            self.sniper = SniperRifle(world_position=drop_position)
            self.scene.move_weapon_pickup("sniper", drop_position)
            self.scene.set_scope_enabled(False)
        elif kind == WeaponKind.PISTOL:
            self.pistol = Pistol(world_position=drop_position)
            self.scene.set_scope_enabled(False)

    def _toggle_sniper_scope(self) -> None:
        if self.session.held_weapon != WeaponKind.SNIPER or self.sniper is None:
            return
        self.sniper.toggle_scope()
        self.player.aim_mode = "SNIPER_SCOPE" if self.sniper.scope_enabled else "SNIPER"
        self.scene.set_scope_enabled(self.sniper.scope_enabled)

    def _fire_current_weapon(self) -> None:
        if (
            self.session.phase == GamePhase.AIRSTRIKE
            and self.session.held_weapon == WeaponKind.ANTI_AIRCRAFT
        ):
            self._fire_anti_aircraft()
        elif (
            self.session.phase == GamePhase.GROUND_COMBAT
            and self.session.held_weapon == WeaponKind.SNIPER
        ):
            self._fire_sniper()
        elif (
            self.session.phase == GamePhase.GROUND_COMBAT
            and self.session.held_weapon == WeaponKind.PISTOL
        ):
            self._fire_pistol()

    def _fire_anti_aircraft(self) -> None:
        if (
            self.session.phase != GamePhase.AIRSTRIKE
            or self.aircraft is None
            or self.anti_aircraft is None
        ):
            return
        if not can_fire_anti_air(
            self.anti_aircraft.lock_state,
            self.anti_aircraft.fire_cooldown,
            self.session.held_weapon,
        ):
            return
        aircraft_destroyed = self.aircraft.take_damage(1)
        self.anti_aircraft.mark_fired()
        self.lock_tracker.reset()
        self.session.lock_state = LockState.WHITE
        self.session.lock_elapsed = 0.0
        if not aircraft_destroyed:
            self._hit_feedback_seconds = 0.35
            return
        aircraft_id = self.aircraft.id
        aircraft_type = self.aircraft.aircraft_type
        self.scene.remove_aircraft(crash=True)
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

    def _fire_sniper(self) -> None:
        if (
            self.session.phase != GamePhase.GROUND_COMBAT
            or self.encounter is None
            or self.sniper is None
        ):
            return
        if not can_fire_sniper(self.sniper.fire_cooldown, self.session.held_weapon):
            return
        target_id = self.scene.crew_under_center(config.SNIPER_MAX_RANGE)
        target_entity = self.scene.crew_entities.get(target_id)
        target_distance = (
            distance_xz(self.scene.player_position(), target_entity.world_position)
            if target_entity is not None
            else None
        )
        if not can_fire_sniper(
            self.sniper.fire_cooldown,
            self.session.held_weapon,
            target_distance,
        ):
            return
        self.sniper.mark_fired(target_id)
        if target_id is None:
            return
        self._hit_feedback_seconds = 0.6
        if damage_crew_member(self.encounter, target_id, 1, self.session):
            self.scene.remove_crew_member(target_id)
            if self.encounter.cleared:
                self._complete_encounter()

    def _fire_pistol(self) -> None:
        if (
            self.session.phase != GamePhase.GROUND_COMBAT
            or self.encounter is None
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
        if damage_crew_member(self.encounter, target_id, 1, self.session):
            self.scene.remove_crew_member(target_id)
        self._hit_feedback_seconds = 0.6
        if self.encounter.cleared:
            self._complete_encounter()

    def _complete_encounter(self) -> None:
        if self.encounter is None:
            return
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
        self.scene.clear_dynamic()
        self.encounter = None
        self.aircraft = None
        self.lock_tracker.reset()
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
        self.scene.set_gameplay_enabled(False)
        self.scene.set_scope_enabled(False)
        self.hud.show_game_over(self.session.stats)

    def _refresh_hud(self) -> None:
        if self.session.phase == GamePhase.AIRSTRIKE:
            visible = self.lock_tracker.flash_visible()
            self.hud.update_lock(
                self.session.lock_state,
                visible,
                active=self.session.held_weapon == WeaponKind.ANTI_AIRCRAFT,
            )
        else:
            self.hud.update_lock(LockState.WHITE, True, active=False)

        prompt = ""
        if self.session.phase == GamePhase.AIRSTRIKE:
            if self.session.held_weapon is None:
                prompt = "物品欄按 1 裝備防空炮"
            elif self.session.held_weapon != WeaponKind.ANTI_AIRCRAFT:
                prompt = "物品欄按 1 切換防空炮"
            elif self.session.lock_state == LockState.GREEN_READY:
                prompt = "綠框已鎖定，按左鍵發射"
            else:
                prompt = "將白框對準戰鬥機完成鎖定"
        elif self.session.phase == GamePhase.GROUND_COMBAT:
            if self.session.held_weapon is None:
                prompt = "物品欄按 2 裝備狙擊槍，或按 3 裝備手槍"
            elif self.session.held_weapon == WeaponKind.ANTI_AIRCRAFT:
                prompt = "物品欄按 2 切換狙擊槍，或按 3 切換手槍"
            elif self.session.held_weapon == WeaponKind.PISTOL:
                prompt = "手槍近距離射擊；按 2 切換狙擊槍"
            else:
                prompt = "右鍵瞄準，左鍵射擊；清除全部敵人"

        warning = bool(
            self.aircraft is not None
            and self.session.phase == GamePhase.AIRSTRIKE
            and warning_active(self.aircraft.estimated_impact_seconds())
        )
        hit_feedback = "命中！" if self._hit_feedback_seconds > 0 else ""
        active_aircraft_type = (
            self.aircraft.aircraft_type
            if self.aircraft is not None
            else self.session.active_aircraft_type
        )
        boss_health = None
        boss_max_health = None
        boss_label = None
        if self.session.wave.is_boss_wave:
            if (
                self.session.phase == GamePhase.AIRSTRIKE
                and self.aircraft is not None
                and self.aircraft.aircraft_type == AircraftType.ARMORED_BOSS
            ):
                boss_health = self.aircraft.health
                boss_max_health = self.aircraft.max_health
                boss_label = "裝甲飛機 HP"
            elif (
                self.session.phase == GamePhase.GROUND_COMBAT
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
            fps=self._fps_value,
            wave_number=self.session.wave.wave_number,
            aircraft_index=self.session.wave.aircraft_index,
            aircraft_count=self.session.wave.aircraft_count,
            aircraft_type=active_aircraft_type,
            city_health=self.session.city_health,
            boss_health=boss_health,
            boss_max_health=boss_max_health,
            boss_label=boss_label,
        )

    def _spawn_current_aircraft(self) -> None:
        if self.session.phase != GamePhase.AIRSTRIKE:
            return
        aircraft_id = self.session.active_aircraft_id or "aircraft-next"
        aircraft_type = self.session.active_aircraft_type or AircraftType.NORMAL
        self.aircraft = Aircraft(
            id=aircraft_id,
            aircraft_type=aircraft_type,
        )
        self.scene.create_aircraft(self.aircraft)


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
