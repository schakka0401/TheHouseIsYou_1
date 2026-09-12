"""A small playable starting point for The House Is You.

Run from the project root with: py -m game.main
"""

from pathlib import Path
import random

import pygame


WINDOW_SIZE = (1280, 720)
CARD_SIZE = (150, 210)
HAND_SIZE = 5
ASSET_DIRECTORY = Path(__file__).resolve().parent.parent / "static" / "assets" / "cards"


def load_cards() -> list[tuple[str, pygame.Surface]]:
    """Load all card faces, excluding the card back."""
    cards = []
    for path in sorted(ASSET_DIRECTORY.glob("*.png")):
        if path.stem == "card_back_1":
            continue
        image = pygame.image.load(path).convert_alpha()
        image = pygame.transform.smoothscale(image, CARD_SIZE)
        cards.append((path.stem.replace("_", " ").title(), image))

    if not cards:
        raise FileNotFoundError(f"No PNG CARDS found in {ASSET_DIRECTORY}")
    return cards


def deal(cards: list[tuple[str, pygame.Surface]]) -> list[tuple[str, pygame.Surface]]:
    """Return a new hand without changing the full deck."""
    return random.sample(cards, min(HAND_SIZE, len(cards)))


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode(WINDOW_SIZE)
    pygame.display.set_caption("The House Is You")
    clock = pygame.time.Clock()
    title_font = pygame.font.Font(None, 54)
    help_font = pygame.font.Font(None, 30)

    try:
        deck = load_cards()
    except FileNotFoundError as error:
        pygame.quit()
        raise SystemExit(error) from error

    hand = deal(deck)
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    hand = deal(deck)

        screen.fill("#154734")
        title = title_font.render("The House Is You", True, "#f7e9b9")
        instructions = help_font.render(
            "SPACE: deal a new hand     ESC: quit", True, "#ffffff"
        )
        screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0] // 2, 70)))
        screen.blit(instructions, instructions.get_rect(center=(WINDOW_SIZE[0] // 2, 125)))

        total_width = len(hand) * CARD_SIZE[0] + (len(hand) - 1) * 24
        first_x = (WINDOW_SIZE[0] - total_width) // 2
        for index, (name, image) in enumerate(hand):
            x = first_x + index * (CARD_SIZE[0] + 24)
            y = 255
            screen.blit(image, (x, y))
            label = help_font.render(name, True, "#ffffff")
            screen.blit(label, label.get_rect(center=(x + CARD_SIZE[0] // 2, y + CARD_SIZE[1] + 25)))

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()


if __name__ == "__main__":
    main()