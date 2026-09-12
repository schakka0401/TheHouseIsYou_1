"""Main menu presentation and input for The House Is You."""
from __future__ import annotations

from pathlib import Path

import pygame

from game.audio import AudioManager

VIRTUAL_SIZE = (1920, 1080)
VIRTUAL_WIDTH, VIRTUAL_HEIGHT = VIRTUAL_SIZE
FADE_IN_MS = 420
PRESS_MS = 100
HOVER_SCALE = 1.015
PRESS_SCALE = 0.985
HOVER_ANIMATION_MS = 120
MENU_MUSIC_VOLUME = 0.35
UI_SWITCH_VOLUME = 0.60
UI_CLICK_VOLUME = 0.75
GOLD = (201, 151, 46)
HIGHLIGHT_GOLD = (241, 210, 119)
CREAM = (255, 229, 157)


def asset_path(folder: str, stem: str) -> Path:
    root = Path(__file__).resolve().parents[1]
    for relative in (Path("assets") / folder, Path("static/assets") / folder):
        matches = sorted((root / relative).glob(f"{stem}.*"))
        if matches:
            return matches[0]
    raise FileNotFoundError(f"Could not find {stem} in {folder}")


def serif_font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ("Georgia", "Baskerville", "Times New Roman", "serif"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


class MenuAudio:
    def __init__(self, manager: AudioManager | None = None):
        self.manager = manager or AudioManager()
        self.available = False
        self.switch_sound = None
        self.click_sound = None
        self.music_path = None
        try:
            if not self.manager.available:
                raise pygame.error("Audio unavailable")
            self.switch_sound = pygame.mixer.Sound(asset_path("audio", "ui_button_switch"))
            self.click_sound = pygame.mixer.Sound(asset_path("audio", "ui_button_click"))
            self.manager.register_sound(self.switch_sound, UI_SWITCH_VOLUME)
            self.manager.register_sound(self.click_sound, UI_CLICK_VOLUME)
            self.music_path = asset_path("audio", "main_menu_theme")
            self.available = True
        except (pygame.error, FileNotFoundError):
            pass

    def start(self):
        if self.available:
            try:
                self.manager.play_music("main_menu_theme")
            except pygame.error:
                self.available = False

    def stop(self):
        if self.available:
            self.manager.stop_music(350)

    def switch(self):
        if self.available and self.switch_sound:
            self.manager.play_ui(self.switch_sound)

    def click(self):
        if self.available and self.click_sound:
            self.manager.play_ui(self.click_sound)

    def apply_sfx_volume(self):
        self.manager.set_sfx_volume(self.manager.sfx_volume)


def gradient(size, top, bottom, radius=15):
    surface = pygame.Surface(size, pygame.SRCALPHA)
    for y in range(size[1]):
        amount = y / max(1, size[1] - 1)
        color = tuple(int(top[i] * (1 - amount) + bottom[i] * amount) for i in range(3))
        pygame.draw.line(surface, color, (0, y), (size[0], y))
    mask = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return surface


def diamond(surface, center, size, fill, outline):
    x, y = center
    points = ((x, y - size), (x + size, y), (x, y + size), (x - size, y))
    pygame.draw.polygon(surface, fill, points)
    pygame.draw.polygon(surface, outline, points, 2)


class MenuButton:
    def __init__(self, label, center_y, face, rect=None):
        self.label = label
        self.rect = rect or pygame.Rect(690, center_y - 45, 540, 90)
        self.face = face
        self.selected = False
        self.pressed_until = 0
        self.hover_progress = 0.0
        self.last_animation_time = None
        self.normal = gradient(self.rect.size, (25, 13, 12), (11, 7, 7))
        self.selected_fill = gradient(self.rect.size, (132, 10, 25), (65, 4, 13))
        self.text_shadow = face.render(label, True, (0, 0, 0))
        self.text = face.render(label, True, CREAM)

    def contains(self, point):
        return self.rect.collidepoint(point)

    def press(self, now):
        self.pressed_until = now + PRESS_MS

    def draw(self, surface, now):
        if self.last_animation_time is None:
            self.last_animation_time = now
        elapsed = max(0, now - self.last_animation_time)
        self.last_animation_time = now
        step = elapsed / HOVER_ANIMATION_MS
        if self.selected:
            self.hover_progress = min(1.0, self.hover_progress + step)
        else:
            self.hover_progress = max(0.0, self.hover_progress - step)
        eased_hover = self.hover_progress * self.hover_progress * (3.0 - 2.0 * self.hover_progress)
        pressed = now < self.pressed_until
        scale = PRESS_SCALE if pressed else 1.0 + (HOVER_SCALE - 1.0) * eased_hover
        rect = pygame.Rect(0, 0, int(self.rect.width * scale), int(self.rect.height * scale))
        rect.center = self.rect.center
        if pressed:
            rect.y += 2
        fill = self.selected_fill if self.selected else self.normal
        if fill.get_size() != rect.size:
            fill = pygame.transform.smoothscale(fill, rect.size)
        surface.blit(fill, rect)
        pygame.draw.rect(surface, (0, 0, 0, 125), rect.move(0, 6), 5, 15)
        pygame.draw.rect(surface, GOLD, rect, 3, 15)
        pygame.draw.rect(surface, (150, 107, 32, 175), rect.inflate(-7, -7), 1, 11)
        text = self.face.render(self.label, True, HIGHLIGHT_GOLD if self.selected else CREAM)
        x = rect.centerx - text.get_width() // 2
        y = rect.centery - text.get_height() // 2 + (2 if pressed else 0)
        surface.blit(self.text_shadow, (x + 2, y + 2))
        surface.blit(text, (x, y))
        if self.selected:
            diamond(surface, (x - 43, rect.centery), 11, (177, 18, 31), HIGHLIGHT_GOLD)
            diamond(surface, (x + text.get_width() + 43, rect.centery), 11, (177, 18, 31), HIGHLIGHT_GOLD)


class AnimatedImageButton:
    """Image-only button using the main menu's hover and press behavior."""

    def __init__(self, image, rect, hover_scale=HOVER_SCALE):
        self.image = image
        self.rect = rect
        self.hover_scale = hover_scale
        self.hover_progress = 0.0
        self.pressed_until = 0
        self.last_animation_time = None

    def update(self, now, hovered):
        if self.last_animation_time is None:
            self.last_animation_time = now
        elapsed = max(0, now - self.last_animation_time)
        self.last_animation_time = now
        step = elapsed / HOVER_ANIMATION_MS
        if hovered:
            self.hover_progress = min(1.0, self.hover_progress + step)
        else:
            self.hover_progress = max(0.0, self.hover_progress - step)

    def press(self, now):
        self.pressed_until = now + PRESS_MS

    def draw(self, surface, now):
        eased_hover = self.hover_progress * self.hover_progress * (3.0 - 2.0 * self.hover_progress)
        scale = PRESS_SCALE if now < self.pressed_until else 1.0 + (self.hover_scale - 1.0) * eased_hover
        size = (max(1, round(self.rect.width * scale)), max(1, round(self.rect.height * scale)))
        rendered = pygame.transform.smoothscale(self.image, size)
        surface.blit(rendered, rendered.get_rect(center=self.rect.center))


class SettingsMenu:
    """Reusable volume settings screen for both menu entry points."""

    def __init__(self, screen, panel, audio_manager, menu_audio):
        self.screen = screen
        self.panel = panel
        self.audio = audio_manager
        self.menu_audio = menu_audio
        self.music_volume = round(audio_manager.music_volume * 100)
        self.sfx_volume = round(audio_manager.sfx_volume * 100)
        self.selected_index = 2
        self.return_target = "main_menu"
        self.last_mouse_pos = pygame.mouse.get_pos()
        self.dragging_index = None
        self.active_slider = None
        self.face = serif_font(30, True)
        self.small_face = serif_font(25, True)
        self.back_button = None
        self.music_track = pygame.Rect(0, 0, 0, 0)
        self.sfx_track = pygame.Rect(0, 0, 0, 0)

    def open(self, return_target):
        self.return_target = return_target
        self.selected_index = 2
        self.last_mouse_pos = pygame.mouse.get_pos()
        self.dragging_index = None
        self.active_slider = None
        self.update_layout()
        self.back_button.selected = True

    def update_layout(self):
        width, height = self.screen.get_size()
        scale = min((width * 0.82) / self.panel.get_width(), (height * 0.90) / self.panel.get_height())
        size = (max(1, round(self.panel.get_width() * scale)), max(1, round(self.panel.get_height() * scale)))
        panel = pygame.transform.smoothscale(self.panel, size)
        panel_rect = panel.get_rect(center=self.screen.get_rect().center)
        track_width = round(panel_rect.width * 0.47)
        track_height = max(18, round(panel_rect.height * 0.045))
        py = panel_rect.top
        ph = panel_rect.height
        self.music_label_center_y = py + round(ph * 0.35)
        self.music_value_center_y = py + round(ph * 0.48)
        self.sfx_label_center_y = py + round(ph * 0.60)
        self.sfx_value_center_y = py + round(ph * 0.73)
        self.music_track = pygame.Rect(0, 0, track_width, track_height)
        self.music_track.center = (panel_rect.centerx, py + round(ph * 0.42))
        self.sfx_track = self.music_track.copy()
        self.sfx_track.center = (panel_rect.centerx, py + round(ph * 0.67))
        button_rect = pygame.Rect(0, 0, round(panel_rect.width * 0.42), round(panel_rect.height * 0.105))
        button_rect.center = (panel_rect.centerx, panel_rect.top + round(panel_rect.height * 0.855))
        if self.back_button is None or self.back_button.rect != button_rect:
            self.back_button = MenuButton("BACK", 0, self.face, button_rect)
            self.back_button.selected = self.selected_index == 2
        return panel, panel_rect

    def _set_value(self, index, value):
        value = max(0, min(100, int(value)))
        if index == 0:
            self.music_volume = value
            self.audio.set_music_volume(value / 100.0)
        else:
            self.sfx_volume = value
            self.audio.set_sfx_volume(value / 100.0)

    def _set_back_hover(self, hovered, play_sound=True):
        was_selected = self.back_button.selected
        self.back_button.selected = hovered
        if hovered and not was_selected and play_sound:
            self.menu_audio.switch()

    def _value_from_mouse(self, track, x):
        return round(max(0, min(1, (x - track.left) / track.width)) * 100)

    def handle_event(self, event, now):
        if event.type == pygame.VIDEORESIZE:
            self.update_layout()
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_w, pygame.K_UP, pygame.K_s, pygame.K_DOWN):
                pass
            elif event.key in (pygame.K_a, pygame.K_LEFT, pygame.K_d, pygame.K_RIGHT):
                if self.active_slider is not None:
                    direction = -5 if event.key in (pygame.K_a, pygame.K_LEFT) else 5
                    self._set_value(self.active_slider, (self.music_volume, self.sfx_volume)[self.active_slider] + direction)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_ESCAPE):
                if event.key == pygame.K_ESCAPE or self.back_button.selected:
                    if event.key != pygame.K_ESCAPE:
                        self.back_button.press(now)
                        self.menu_audio.click()
                    return "back"
        elif event.type == pygame.MOUSEMOTION and event.pos != self.last_mouse_pos:
            self.last_mouse_pos = event.pos
            if self.dragging_index is not None:
                track = (self.music_track, self.sfx_track)[self.dragging_index]
                self._set_value(self.dragging_index, self._value_from_mouse(track, event.pos[0]))
            self._set_back_hover(self.back_button.contains(event.pos))
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.music_track.inflate(24, 24).collidepoint(event.pos):
                self.active_slider = 0
                self.dragging_index = 0
                self._set_back_hover(False, False)
                self._set_value(0, self._value_from_mouse(self.music_track, event.pos[0]))
            elif self.sfx_track.inflate(24, 24).collidepoint(event.pos):
                self.active_slider = 1
                self.dragging_index = 1
                self._set_back_hover(False, False)
                self._set_value(1, self._value_from_mouse(self.sfx_track, event.pos[0]))
            elif self.back_button and self.back_button.contains(event.pos):
                self._set_back_hover(True, False)
                self.back_button.press(now)
                self.menu_audio.click()
                return "back"
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging_index = None
        return None

    def draw(self, now):
        panel, panel_rect = self.update_layout()
        self.screen.fill((8, 4, 5))
        self.screen.blit(panel, panel_rect)
        font = self.small_face
        for index, (label, track, value, label_y, value_y) in enumerate((
            ("MUSIC VOLUME", self.music_track, self.music_volume, self.music_label_center_y, self.music_value_center_y),
            ("SOUND EFFECTS", self.sfx_track, self.sfx_volume, self.sfx_label_center_y, self.sfx_value_center_y),
        )):
            text = font.render(label, True, CREAM)
            self.screen.blit(text, text.get_rect(center=(panel_rect.centerx, label_y)))
            pygame.draw.rect(self.screen, (35, 8, 12), track, border_radius=track.height // 2)
            pygame.draw.rect(self.screen, GOLD, track, 2, border_radius=track.height // 2)
            fill = track.copy()
            fill.width = round(track.width * value / 100)
            if fill.width:
                pygame.draw.rect(self.screen, (145, 18, 31), fill, border_radius=track.height // 2)
            knob_x = track.left + round(track.width * value / 100)
            pygame.draw.circle(self.screen, GOLD, (knob_x, track.centery), track.height // 2 + 3)
            value_text = font.render(str(value), True, CREAM)
            self.screen.blit(value_text, value_text.get_rect(center=(panel_rect.centerx, value_y)))
        self.back_button.draw(self.screen, now)


class MainMenu:
    """Menu that returns ``play``, ``options``, or ``quit`` activation actions."""

    def __init__(self, screen, audio_manager: AudioManager | None = None):
        self.screen = screen
        self.audio = MenuAudio(audio_manager)
        self.audio.start()
        self.background = pygame.image.load(asset_path("images", "main_menu_background")).convert_alpha()
        if self.background.get_size() != VIRTUAL_SIZE:
            self.background = pygame.transform.smoothscale(self.background, VIRTUAL_SIZE)
        self.background_scaled = None
        self.viewport = pygame.Rect(0, 0, *VIRTUAL_SIZE)
        face = serif_font(34, True)
        self.buttons = [MenuButton("PLAY GAME", 675, face), MenuButton("OPTIONS", 790, face), MenuButton("QUIT GAME", 900, face)]
        self.selected_index = 0
        self.buttons[0].selected = True
        self.input_mode = "mouse"
        self.previous_mouse_position = pygame.mouse.get_pos()
        self.started_at = pygame.time.get_ticks()

    def update_viewport(self):
        width, height = self.screen.get_size()
        scale = min(width / VIRTUAL_WIDTH, height / VIRTUAL_HEIGHT)
        size = (max(1, round(VIRTUAL_WIDTH * scale)), max(1, round(VIRTUAL_HEIGHT * scale)))
        self.viewport = pygame.Rect((width - size[0]) // 2, (height - size[1]) // 2, *size)
        if self.background_scaled is None or self.background_scaled.get_size() != size:
            self.background_scaled = pygame.transform.smoothscale(self.background, size)

    def to_virtual(self, point):
        if not self.viewport.collidepoint(point):
            return None
        return (round((point[0] - self.viewport.left) * VIRTUAL_WIDTH / self.viewport.width),
                round((point[1] - self.viewport.top) * VIRTUAL_HEIGHT / self.viewport.height))

    def choose(self, index):
        index %= len(self.buttons)
        if index != self.selected_index:
            self.selected_index = index
            self.audio.switch()
        for button_index, button in enumerate(self.buttons):
            button.selected = button_index == self.selected_index

    def activate(self, now):
        button = self.buttons[self.selected_index]
        button.press(now)
        self.audio.click()
        return ("play", "options", "quit")[self.selected_index]

    def handle_event(self, event, now):
        if event.type == pygame.VIDEORESIZE:
            self.update_viewport()
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self.input_mode = "keyboard"
                self.choose(self.selected_index - 1)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.input_mode = "keyboard"
                self.choose(self.selected_index + 1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return self.activate(now)
            elif event.key in (pygame.K_ESCAPE, pygame.K_q):
                return "quit"
        elif event.type == pygame.MOUSEMOTION:
            moved = event.pos != self.previous_mouse_position
            self.previous_mouse_position = event.pos
            if moved:
                self.input_mode = "mouse"
                point = self.to_virtual(event.pos)
                for index, button in enumerate(self.buttons):
                    if point is not None and button.contains(point):
                        self.choose(index)
                        break
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.previous_mouse_position = event.pos
            point = self.to_virtual(event.pos)
            for index, button in enumerate(self.buttons):
                if point is not None and button.contains(point):
                    self.input_mode = "mouse"
                    self.choose(index)
                    return self.activate(now)
        return None

    def draw(self, now):
        self.update_viewport()
        ui = pygame.Surface(VIRTUAL_SIZE, pygame.SRCALPHA)
        for button in self.buttons:
            button.draw(ui, now)
        self.screen.fill((8, 4, 5))
        self.screen.blit(self.background_scaled, self.viewport.topleft)
        self.screen.blit(pygame.transform.smoothscale(ui, self.viewport.size), self.viewport.topleft)
        progress = max(0.0, min(1.0, (now - self.started_at) / FADE_IN_MS))
        if progress < 1.0:
            overlay = pygame.Surface(self.viewport.size, pygame.SRCALPHA)
            overlay.fill((0, 0, 0, round(255 * (1 - progress))))
            self.screen.blit(overlay, self.viewport.topleft)
