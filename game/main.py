"""Main menu for The House Is You.

The supplied 1920x1080 image owns the complete casino composition. This module
only renders and handles the interactive menu layer above it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pygame

VIRTUAL_SIZE = (1920, 1080)
VIRTUAL_WIDTH, VIRTUAL_HEIGHT = VIRTUAL_SIZE
FPS = 60
FADE_IN_MS = 420
PRESS_MS = 100

GOLD = (201, 151, 46)
HIGHLIGHT_GOLD = (241, 210, 119)
CREAM = (255, 229, 157)
NORMAL_FILL_TOP = (25, 13, 12)
NORMAL_FILL_BOTTOM = (11, 7, 7)
SELECTED_FILL_TOP = (132, 10, 25)
SELECTED_FILL_BOTTOM = (65, 4, 13)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def background_path() -> Path:
    root = project_root()
    # The first path is the requested location; the second matches this repo's
    # current asset layout, so either layout works without changing the UI.
    for relative in (Path("assets/menu/main_menu_background.png"),
                     Path("static/assets/main_menu_background.png")):
        candidate = root / relative
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not find assets/menu/main_menu_background.png")


def serif_font(size: int, bold: bool = False) -> pygame.font.Font:
    """Use a classic serif without downloading or adding a font dependency."""
    for name in ("Georgia", "Baskerville", "Times New Roman", "serif"):
        path = pygame.font.match_font(name, bold=bold)
        if path:
            return pygame.font.Font(path, size)
    return pygame.font.Font(None, size)


def diamond(surface: pygame.Surface, center: tuple[int, int], size: int,
            fill: tuple[int, int, int], outline: tuple[int, int, int]) -> None:
    x, y = center
    points = ((x, y - size), (x + size, y), (x, y + size), (x - size, y))
    pygame.draw.polygon(surface, fill, points)
    pygame.draw.polygon(surface, outline, points, 2)


def rounded_gradient(size: tuple[int, int], top: tuple[int, int, int],
                    bottom: tuple[int, int, int], radius: int) -> pygame.Surface:
    """Create one reusable rounded vertical gradient for a button state."""
    width, height = size
    surface = pygame.Surface(size, pygame.SRCALPHA)
    for y in range(height):
        amount = y / max(1, height - 1)
        color = tuple(int(top[index] * (1 - amount) + bottom[index] * amount)
                      for index in range(3))
        pygame.draw.line(surface, color, (0, y), (width, y))
    mask = pygame.Surface(size, pygame.SRCALPHA)
    pygame.draw.rect(mask, (255, 255, 255, 255), mask.get_rect(), border_radius=radius)
    surface.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
    return surface


class MenuButton:
    """One menu choice with cached visuals and a small tactile press response."""

    def __init__(self, label: str, center_y: int, font: pygame.font.Font):
        self.label = label
        self.base_rect = pygame.Rect(690, center_y - 45, 540, 90)
        self.font = font
        self.selected = False
        self.hovered = False
        self.pressed_until = 0
        self.normal_fill = rounded_gradient(self.base_rect.size, NORMAL_FILL_TOP,
                                            NORMAL_FILL_BOTTOM, 15)
        self.selected_fill = rounded_gradient(self.base_rect.size, SELECTED_FILL_TOP,
                                              SELECTED_FILL_BOTTOM, 15)
        self.label_image = font.render(label, True, CREAM)
        self.label_shadow = font.render(label, True, (0, 0, 0))
        self.glow = self._make_glow()

    def _make_glow(self) -> pygame.Surface:
        glow = pygame.Surface((self.base_rect.width + 70, self.base_rect.height + 70),
                              pygame.SRCALPHA)
        for inset, alpha in ((30, 8), (22, 12), (15, 20), (9, 28)):
            rect = glow.get_rect().inflate(-inset * 2, -inset * 2)
            pygame.draw.rect(glow, (*GOLD, alpha), rect, width=5, border_radius=20)
        return glow

    def contains_point(self, point: tuple[int, int]) -> bool:
        return self.base_rect.collidepoint(point)

    def update(self, now: int) -> None:
        self.pressed_until = max(0, self.pressed_until)

    def press(self, now: int) -> None:
        self.pressed_until = now + PRESS_MS

    def draw(self, surface: pygame.Surface, now: int) -> None:
        is_pressed = now < self.pressed_until
        selected = self.selected or self.hovered
        scale = 0.985 if is_pressed else (1.015 if selected else 1.0)
        width = int(self.base_rect.width * scale)
        height = int(self.base_rect.height * scale)
        rect = pygame.Rect(0, 0, width, height)
        rect.center = self.base_rect.center
        if is_pressed:
            rect.y += 2

        if selected and not is_pressed:
            glow_rect = self.glow.get_rect(center=rect.center)
            surface.blit(self.glow, glow_rect, special_flags=pygame.BLEND_RGBA_ADD)

        fill = self.selected_fill if selected else self.normal_fill
        if fill.get_size() != rect.size:
            fill = pygame.transform.smoothscale(fill, rect.size)
        surface.blit(fill, rect)

        outer_color = HIGHLIGHT_GOLD if selected else GOLD
        pygame.draw.rect(surface, (0, 0, 0, 125), rect.move(0, 6), width=5, border_radius=15)
        pygame.draw.rect(surface, outer_color, rect, width=3, border_radius=15)
        pygame.draw.rect(surface, (247, 211, 121, 165) if selected else (150, 107, 32, 175),
                         rect.inflate(-7, -7), width=1, border_radius=11)

        text_x = rect.centerx - self.label_image.get_width() // 2
        text_y = rect.centery - self.label_image.get_height() // 2 + (2 if is_pressed else 0)
        surface.blit(self.label_shadow, (text_x + 2, text_y + 2))
        text = self.font.render(self.label, True, HIGHLIGHT_GOLD if selected else CREAM)
        surface.blit(text, (text_x, text_y))
        if selected:
            ornament_y = rect.centery + (2 if is_pressed else 0)
            diamond(surface, (text_x - 43, ornament_y), 11, (177, 18, 31), HIGHLIGHT_GOLD)
            diamond(surface, (text_x + self.label_image.get_width() + 43, ornament_y),
                    11, (177, 18, 31), HIGHLIGHT_GOLD)


class MainMenu:
    """Virtual-resolution menu presentation and input handling."""

    def __init__(self, screen: pygame.Surface):
        self.screen = screen
        self.ui_canvas = pygame.Surface(VIRTUAL_SIZE, pygame.SRCALPHA)
        self.background = pygame.image.load(background_path()).convert_alpha()
        if self.background.get_size() != VIRTUAL_SIZE:
            self.background = pygame.transform.smoothscale(self.background, VIRTUAL_SIZE)
        self.background_scaled: pygame.Surface | None = None
        self.viewport = pygame.Rect(0, 0, *VIRTUAL_SIZE)
        label_font = serif_font(34, True)
        self.buttons = [
            MenuButton("PLAY GAME", 675, label_font),
            MenuButton("OPTIONS", 790, label_font),
            MenuButton("QUIT GAME", 900, label_font),
        ]
        self.selected_index = 0
        self.buttons[0].selected = True
        self.started_at = pygame.time.get_ticks()

    def update_viewport(self) -> None:
        screen_width, screen_height = self.screen.get_size()
        scale = min(screen_width / VIRTUAL_WIDTH, screen_height / VIRTUAL_HEIGHT)
        width = max(1, round(VIRTUAL_WIDTH * scale))
        height = max(1, round(VIRTUAL_HEIGHT * scale))
        self.viewport = pygame.Rect((screen_width - width) // 2,
                                    (screen_height - height) // 2, width, height)
        if self.background_scaled is None or self.background_scaled.get_size() != (width, height):
            self.background_scaled = pygame.transform.smoothscale(self.background, (width, height))

    def screen_to_virtual(self, point: tuple[int, int]) -> tuple[int, int] | None:
        if not self.viewport.collidepoint(point):
            return None
        x = round((point[0] - self.viewport.left) * VIRTUAL_WIDTH / self.viewport.width)
        y = round((point[1] - self.viewport.top) * VIRTUAL_HEIGHT / self.viewport.height)
        return x, y

    def choose(self, index: int) -> None:
        self.selected_index = index % len(self.buttons)
        for button_index, button in enumerate(self.buttons):
            button.selected = button_index == self.selected_index

    def move_selection(self, amount: int) -> None:
        self.choose(self.selected_index + amount)

    def activate(self, now: int) -> bool:
        """Return False only for Quit; Play/Options retain their current no-op behavior."""
        button = self.buttons[self.selected_index]
        button.press(now)
        if button.label == "QUIT GAME":
            return False
        return True

    def handle_event(self, event: pygame.event.Event, now: int) -> bool:
        if event.type == pygame.VIDEORESIZE:
            self.update_viewport()
        elif event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_UP, pygame.K_w):
                self.move_selection(-1)
            elif event.key in (pygame.K_DOWN, pygame.K_s):
                self.move_selection(1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE):
                return self.activate(now)
            elif event.key in (pygame.K_ESCAPE, pygame.K_q):
                return False
        elif event.type == pygame.MOUSEMOTION:
            point = self.screen_to_virtual(event.pos)
            for index, button in enumerate(self.buttons):
                button.hovered = point is not None and button.contains_point(point)
                if button.hovered:
                    self.choose(index)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            point = self.screen_to_virtual(event.pos)
            for index, button in enumerate(self.buttons):
                if point is not None and button.contains_point(point):
                    self.choose(index)
                    return self.activate(now)
        return True

    def draw(self, now: int) -> None:
        self.update_viewport()
        self.ui_canvas.fill((0, 0, 0, 0))
        for button in self.buttons:
            button.update(now)
            button.draw(self.ui_canvas, now)

        # The background is a cached viewport surface. Only the interactive UI
        # layer is scaled each frame for hover/press animation.
        self.screen.fill((8, 4, 5))
        self.screen.blit(self.background_scaled, self.viewport.topleft)
        ui_scaled = pygame.transform.smoothscale(self.ui_canvas, self.viewport.size)
        self.screen.blit(ui_scaled, self.viewport.topleft)

        # Fade the complete composition during the first appearance.
        elapsed = now - self.started_at
        fade_progress = max(0.0, min(1.0, elapsed / FADE_IN_MS))
        if fade_progress < 1.0:
            overlay = pygame.Surface(self.viewport.size, pygame.SRCALPHA)
            overlay.fill((0, 0, 0, round(255 * (1 - fade_progress))))
            self.screen.blit(overlay, self.viewport.topleft)


def run() -> None:
    pygame.init()
    pygame.display.set_caption("The House Is You")
    screen = pygame.display.set_mode(VIRTUAL_SIZE, pygame.RESIZABLE)
    menu = MainMenu(screen)
    clock = pygame.time.Clock()
    running = True
    while running:
        now = pygame.time.get_ticks()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif not menu.handle_event(event, now):
                running = False
        menu.draw(now)
        pygame.display.flip()
        clock.tick(FPS)
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    run()
