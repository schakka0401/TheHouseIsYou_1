"""Main menu presentation and input for The House Is You."""
from __future__ import annotations

from pathlib import Path

import pygame

VIRTUAL_SIZE = (1920, 1080)
VIRTUAL_WIDTH, VIRTUAL_HEIGHT = VIRTUAL_SIZE
FADE_IN_MS = 420
PRESS_MS = 100
MENU_MUSIC_VOLUME = 0.35
UI_SWITCH_VOLUME = 0.45
UI_CLICK_VOLUME = 0.60
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
    def __init__(self):
        self.available = False
        self.switch_sound = None
        self.click_sound = None
        self.music_path = None
        try:
            if pygame.mixer.get_init() is None:
                pygame.mixer.init()
            self.switch_sound = pygame.mixer.Sound(asset_path("audio", "ui_button_switch"))
            self.click_sound = pygame.mixer.Sound(asset_path("audio", "ui_button_click"))
            self.switch_sound.set_volume(UI_SWITCH_VOLUME)
            self.click_sound.set_volume(UI_CLICK_VOLUME)
            self.music_path = asset_path("audio", "main_menu_theme")
            self.available = True
        except (pygame.error, FileNotFoundError):
            pass

    def start(self):
        if self.available and not pygame.mixer.music.get_busy():
            try:
                pygame.mixer.music.load(self.music_path)
                pygame.mixer.music.set_volume(MENU_MUSIC_VOLUME)
                pygame.mixer.music.play(-1)
            except pygame.error:
                self.available = False

    def stop(self):
        if self.available:
            pygame.mixer.music.fadeout(350)

    def switch(self):
        if self.available and self.switch_sound:
            self.switch_sound.play()

    def click(self):
        if self.available and self.click_sound:
            self.click_sound.play()


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
    def __init__(self, label, center_y, face):
        self.label = label
        self.rect = pygame.Rect(690, center_y - 45, 540, 90)
        self.face = face
        self.selected = False
        self.pressed_until = 0
        self.normal = gradient(self.rect.size, (25, 13, 12), (11, 7, 7))
        self.selected_fill = gradient(self.rect.size, (132, 10, 25), (65, 4, 13))
        self.text_shadow = face.render(label, True, (0, 0, 0))
        self.text = face.render(label, True, CREAM)

    def contains(self, point):
        return self.rect.collidepoint(point)

    def press(self, now):
        self.pressed_until = now + PRESS_MS

    def draw(self, surface, now):
        pressed = now < self.pressed_until
        scale = 0.985 if pressed else (1.015 if self.selected else 1.0)
        rect = pygame.Rect(0, 0, int(self.rect.width * scale), int(self.rect.height * scale))
        rect.center = self.rect.center
        if pressed:
            rect.y += 2
        if self.selected and not pressed:
            glow = pygame.Surface(rect.inflate(70, 70).size, pygame.SRCALPHA)
            for inset, alpha in ((30, 8), (22, 12), (15, 20), (9, 28)):
                pygame.draw.rect(glow, (*GOLD, alpha), glow.get_rect().inflate(-inset * 2, -inset * 2), 5, 20)
            surface.blit(glow, glow.get_rect(center=rect.center), special_flags=pygame.BLEND_RGBA_ADD)
        fill = self.selected_fill if self.selected else self.normal
        if fill.get_size() != rect.size:
            fill = pygame.transform.smoothscale(fill, rect.size)
        surface.blit(fill, rect)
        pygame.draw.rect(surface, (0, 0, 0, 125), rect.move(0, 6), 5, 15)
        pygame.draw.rect(surface, HIGHLIGHT_GOLD if self.selected else GOLD, rect, 3, 15)
        pygame.draw.rect(surface, (247, 211, 121, 165) if self.selected else (150, 107, 32, 175), rect.inflate(-7, -7), 1, 11)
        text = self.face.render(self.label, True, HIGHLIGHT_GOLD if self.selected else CREAM)
        x = rect.centerx - text.get_width() // 2
        y = rect.centery - text.get_height() // 2 + (2 if pressed else 0)
        surface.blit(self.text_shadow, (x + 2, y + 2))
        surface.blit(text, (x, y))
        if self.selected:
            diamond(surface, (x - 43, rect.centery), 11, (177, 18, 31), HIGHLIGHT_GOLD)
            diamond(surface, (x + text.get_width() + 43, rect.centery), 11, (177, 18, 31), HIGHLIGHT_GOLD)


class MainMenu:
    """Menu that returns ``play``, ``options``, or ``quit`` activation actions."""

    def __init__(self, screen):
        self.screen = screen
        self.audio = MenuAudio()
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
