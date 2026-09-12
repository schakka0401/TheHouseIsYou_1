"""The House Is You - procedural main menu recreation.

Run from the project root with ``python -m game.main``.
"""
from __future__ import annotations

import math
import random
import sys

import pygame

WIDTH, HEIGHT = 1680, 944
GOLD = (222, 164, 45)
BRIGHT_GOLD = (255, 220, 119)
CREAM = (255, 231, 157)
RED = (174, 20, 31)


def font(size: int, bold: bool = False) -> pygame.font.Font:
    for name in ("Georgia", "Baskerville", "Times New Roman", "serif"):
        match = pygame.font.match_font(name, bold=bold)
        if match:
            return pygame.font.Font(match, size)
    return pygame.font.Font(None, size)


def centered(surface, text, y, face, color, center_x=WIDTH // 2):
    image = face.render(text, True, color)
    surface.blit(image, (center_x - image.get_width() // 2, y))


def diamond(surface, center, size, color, outline=None):
    x, y = center
    points = [(x, y - size), (x + size, y), (x, y + size), (x - size, y)]
    pygame.draw.polygon(surface, color, points)
    if outline:
        pygame.draw.polygon(surface, outline, points, max(1, size // 8))


def draw_felt(surface):
    # Horizontal bands are much faster than setting every pixel individually,
    # while the small translucent flecks keep the felt from looking synthetic.
    for y in range(HEIGHT):
        dy = (y - HEIGHT * .42) / HEIGHT
        glow_y = max(0.0, 1.0 - abs(dy) * 1.7)
        pygame.draw.line(surface, (int(24 + 23 * glow_y), int(2 + 3 * glow_y),
                                   int(6 + 9 * glow_y)), (0, y), (WIDTH, y))
    flecks = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    for _ in range(28000):
        x, y = random.randrange(WIDTH), random.randrange(HEIGHT)
        pygame.draw.line(flecks, (130, 25, 33, random.randrange(3, 13)),
                         (x, y), (x + random.randrange(-4, 5), y), 1)
    surface.blit(flecks, (0, 0))


def draw_card(surface, rect, label, suit, angle):
    card = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(card, (55, 20, 15, 135), card.get_rect(), border_radius=20)
    pygame.draw.rect(card, (148, 85, 25, 160), card.get_rect(), width=4, border_radius=20)
    card.blit(font(45, True).render(label, True, (103, 50, 20, 160)), (30, 20))
    suit_image = font(125).render(suit, True, (105, 43, 17, 135))
    card.blit(suit_image, (rect.width // 2 - suit_image.get_width() // 2,
                           rect.height // 2 - suit_image.get_height() // 2))
    rotated = pygame.transform.rotate(card, angle)
    surface.blit(rotated, rotated.get_rect(center=rect.center))


def draw_chip_stack(surface, x, y, count, scale=.75):
    for index in range(count):
        cy = y - index * int(27 * scale)
        w, h = int(160 * scale), int(42 * scale)
        rect = pygame.Rect(x - w // 2, cy - h // 2, w, h)
        pygame.draw.ellipse(surface, (37, 20, 15), rect)
        pygame.draw.ellipse(surface, (131, 71, 24), rect, max(2, int(4 * scale)))
        pygame.draw.ellipse(surface, (18, 12, 10), rect.inflate(-int(14 * scale), -int(8 * scale)), max(2, int(4 * scale)))
        pygame.draw.line(surface, (213, 132, 42), (rect.left + 12, cy), (rect.right - 12, cy), max(1, int(2 * scale)))


def draw_border(surface):
    outer = pygame.Rect(15, 16, WIDTH - 30, HEIGHT - 32)
    inner = pygame.Rect(41, 39, WIDTH - 82, HEIGHT - 78)
    pygame.draw.rect(surface, (112, 63, 15), outer, width=3, border_radius=39)
    pygame.draw.rect(surface, BRIGHT_GOLD, inner, width=2, border_radius=29)
    pygame.draw.rect(surface, (104, 56, 13), inner.inflate(-10, -10), width=1, border_radius=23)
    for x in range(88, WIDTH - 88, 52):
        pygame.draw.circle(surface, (255, 244, 214), (x, 28), 5)
        pygame.draw.circle(surface, (255, 244, 214), (x, HEIGHT - 28), 5)
    for y in range(91, HEIGHT - 91, 45):
        pygame.draw.circle(surface, (255, 244, 214), (29, y), 5)
        pygame.draw.circle(surface, (255, 244, 214), (WIDTH - 29, y), 5)
    for center, suit, color in [((50, 57), "♥", RED), ((WIDTH - 50, 57), "♦", RED),
                                ((50, HEIGHT - 56), "♣", (31, 31, 28)),
                                ((WIDTH - 50, HEIGHT - 56), "♠", RED)]:
        pygame.draw.circle(surface, (8, 8, 6), center, 34)
        pygame.draw.circle(surface, BRIGHT_GOLD, center, 37, 2)
        centered(surface, suit, center[1] - 27, font(58), color, center_x=center[0])
    diamond(surface, (WIDTH // 2, 35), 16, GOLD, CREAM)
    diamond(surface, (WIDTH // 2, HEIGHT - 35), 16, GOLD, CREAM)


def draw_logo(surface):
    center_x = WIDTH // 2
    plaque = pygame.Rect(center_x - 230, 161, 460, 270)
    pygame.draw.rect(surface, (5, 20, 29), plaque, border_radius=48)
    pygame.draw.rect(surface, BRIGHT_GOLD, plaque, width=5, border_radius=48)
    pygame.draw.rect(surface, (96, 45, 11), plaque.inflate(16, 16), width=3, border_radius=55)
    pygame.draw.arc(surface, BRIGHT_GOLD, pygame.Rect(center_x - 155, 99, 310, 120), .1, math.pi - .1, 6)
    diamond(surface, (center_x, 127), 24, GOLD, CREAM)
    centered(surface, "THE", 191, font(45, True), CREAM)
    centered(surface, "HOUSE", 224, font(91, True), (255, 195, 69))
    centered(surface, "IS YOU", 318, font(48, True), CREAM)
    pygame.draw.arc(surface, BRIGHT_GOLD, pygame.Rect(center_x - 160, 365, 320, 105), math.pi + .15, 2 * math.pi - .15, 5)
    diamond(surface, (center_x, 401), 11, RED, BRIGHT_GOLD)


def draw_button(surface, rect, label, selected):
    fill = (75, 3, 14) if selected else (25, 15, 13)
    border = (255, 226, 123) if selected else (178, 123, 21)
    pygame.draw.rect(surface, fill, rect, border_radius=17)
    pygame.draw.rect(surface, border, rect, width=3, border_radius=17)
    if selected:
        diamond(surface, (rect.left + 108, rect.centery), 13, RED, BRIGHT_GOLD)
        diamond(surface, (rect.right - 108, rect.centery), 13, RED, BRIGHT_GOLD)
    centered(surface, label, rect.centery - 17, font(28, True), CREAM)


def run():
    pygame.init()
    pygame.display.set_caption("The House Is You")
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    background = pygame.Surface((WIDTH, HEIGHT))
    random.seed(7)
    draw_felt(background)
    draw_card(background, pygame.Rect(110, 292, 260, 380), "A", "♠", 12)
    draw_card(background, pygame.Rect(WIDTH - 370, 296, 260, 380), "K", "♥", -12)
    draw_chip_stack(background, 106, 784, 5)
    draw_chip_stack(background, 1574, 783, 6)
    draw_border(background)

    selected = 0
    labels = ("PLAY GAME", "OPTIONS", "QUIT GAME")
    clock = pygame.time.Clock()
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_UP, pygame.K_w):
                    selected = (selected - 1) % len(labels)
                elif event.key in (pygame.K_DOWN, pygame.K_s):
                    selected = (selected + 1) % len(labels)
                elif event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
        view = pygame.transform.smoothscale(background, screen.get_size())
        screen.blit(view, (0, 0))
        menu = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pygame.draw.line(menu, GOLD, (578, 493), (1102, 493), 3)
        diamond(menu, (840, 493), 14, GOLD, CREAM)
        draw_logo(menu)
        for index, label in enumerate(labels):
            draw_button(menu, pygame.Rect(603, 550 + index * 98, 466, 80), label, index == selected)
        screen.blit(pygame.transform.smoothscale(menu, screen.get_size()), (0, 0))
        pygame.display.flip()
        clock.tick(60)
    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    run()
