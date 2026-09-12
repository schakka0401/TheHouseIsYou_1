"""The House Is You: explore rooms, deal cards, and play blackjack."""

from pathlib import Path
import random

import pygame

from game.menu import MainMenu


WINDOW_SIZE = (1280, 720)
CARD_SIZE = (150, 210)
PLAYER_SIZE = (96, 96)
PLAYER_DISPLAY_SIZE = (72, 96)
PLAYER_SPEED = 300
PLAYER_ANIMATION_FRAME_DURATION = 0.12
HAND_SIZE = 5
ASSETS = Path(__file__).resolve().parent.parent / "static" / "assets"
CARD_DIRECTORY = ASSETS / "cards"
PLAYER_SPRITE_DIRECTORY = ASSETS / "sprites"
CASINO_DIRECTORY = ASSETS / "2D Top Down Pixel Art Tileset Casino"
CASINO_TILESET = CASINO_DIRECTORY / "2D_TopDown_Tileset_Casino_1024x512.png"
TABLE = pygame.Rect(465, 250, 350, 220)


def load_player_animations() -> dict[str, list[pygame.Surface]]:
    """Load the two right-facing frames and cache their left-facing flips."""
    right_frames: list[pygame.Surface] = []
    for frame_index in range(2):
        path = PLAYER_SPRITE_DIRECTORY / f"player_right{frame_index}.png"
        if not path.exists():
            raise FileNotFoundError(f"Missing player sprite: {path}")
        image = pygame.image.load(path).convert_alpha()
        # Keep the existing on-screen size regardless of source PNG dimensions.
        right_frames.append(pygame.transform.scale(image, PLAYER_DISPLAY_SIZE))

    left_frames = [pygame.transform.flip(frame, True, False) for frame in right_frames]
    return {"right": right_frames, "left": left_frames}


def load_cards() -> list[tuple[str, pygame.Surface]]:
    cards = []
    for path in sorted(CARD_DIRECTORY.glob("*.png")):
        if path.stem in {"card_back_1", "joker"}:
            continue
        image = pygame.image.load(path).convert_alpha()
        cards.append((path.stem.replace("_", " ").title(), pygame.transform.smoothscale(image, CARD_SIZE)))
    if not cards:
        raise FileNotFoundError(f"No card PNGs found in {CARD_DIRECTORY}")
    return cards


def make_casino_room(tileset: pygame.Surface, room: int) -> pygame.Surface:
    """Build a full-sized casino room from the supplied pixel-art tileset."""
    background = pygame.Surface(WINDOW_SIZE)
    background.fill("#64162c")

    red_carpet = pygame.transform.scale(tileset.subsurface((0, 0, 32, 32)), (48, 48))
    blue_carpet = pygame.transform.scale(tileset.subsurface((0, 128, 32, 32)), (48, 48))

    def tile(surface: pygame.Surface, image: pygame.Surface, area: pygame.Rect) -> None:
        for y in range(area.top, area.bottom, image.get_height()):
            for x in range(area.left, area.right, image.get_width()):
                surface.blit(image, (x, y))

    # A solid color beneath the transparent tile art prevents sheet-padding from
    # showing up as distracting black seams.
    tile(background, red_carpet, pygame.Rect(0, 48, WINDOW_SIZE[0], WINDOW_SIZE[1] - 48))
    floor = pygame.Rect(96, 112, WINDOW_SIZE[0] - 192, WINDOW_SIZE[1] - 176)
    background.fill("#192c78", floor)
    tile(background, blue_carpet, floor)

    # Use two unscaled, deliberate strips from the pack instead of a collage of furniture.
    slot_bank = pygame.transform.scale(tileset.subsurface((640, 0, 155, 70)), (310, 140))
    slot_bank.set_colorkey("#000000")
    background.blit(slot_bank, slot_bank.get_rect(midtop=(WINDOW_SIZE[0] // 2, 105)))
    side_slots = pygame.transform.scale(tileset.subsurface((795, 0, 120, 70)), (240, 140))
    side_slots.set_colorkey("#000000")
    background.blit(side_slots, (115, 505))
    background.blit(side_slots, (WINDOW_SIZE[0] - 355, 505))
    return background


def load_casino_scenes() -> tuple[list[pygame.Surface], list[pygame.Surface]]:
    """Load casino-room backgrounds plus the pack's roulette and blackjack tables."""
    tileset = pygame.image.load(CASINO_TILESET).convert_alpha()
    rooms = [make_casino_room(tileset, 0), make_casino_room(tileset, 1)]
    roulette_table = tileset.subsurface((870, 263, 154, 105))
    blackjack_table = tileset.subsurface((880, 194, 144, 65))
    tables = [
        pygame.transform.scale(roulette_table, (350, 238)),
        pygame.transform.scale(blackjack_table, (390, 176)),
    ]
    return rooms, tables


def card_value(name: str) -> int:
    """Return a blackjack card value; aces start as 11."""
    rank = name.split()[0]
    if rank == "Ace":
        return 11
    if rank in {"King", "Queen", "Jack"}:
        return 10
    return int(rank)


def hand_value(hand: list[tuple[str, pygame.Surface]]) -> int:
    value = sum(card_value(name) for name, _ in hand)
    aces = sum(name.startswith("Ace ") for name, _ in hand)
    while value > 21 and aces:
        value -= 10
        aces -= 1
    return value


def draw_room(
    screen: pygame.Surface,
    player: pygame.Vector2,
    image: pygame.Surface,
    font: pygame.font.Font,
    room: int,
    backgrounds: list[pygame.Surface],
    tables: list[pygame.Surface],
) -> None:
    screen.blit(backgrounds[room], (0, 0))
    table = tables[room]
    screen.blit(table, table.get_rect(center=TABLE.center))

    room_name = "Card Room" if room == 0 else "Blackjack Room"
    screen.blit(font.render(f"THE HOUSE IS YOU  —  {room_name}", True, "#ffffff"), (40, 30))
    screen.blit(image, image.get_rect(center=player))

    if player.distance_to(pygame.Vector2(TABLE.center)) < 190:
        action = "play blackjack" if room else "sit at the table"
        prompt = font.render(f"Press E to {action}", True, "#ffffff")
        screen.blit(prompt, prompt.get_rect(center=(TABLE.centerx, TABLE.bottom + 45)))
    else:
        exit_hint = "A: return to card room" if room else "D: enter blackjack room"
        hint = font.render(f"WASD: move     {exit_hint}", True, "#ffffff")
        screen.blit(hint, (40, 650))


def draw_card_game(screen: pygame.Surface, hand: list[tuple[str, pygame.Surface]], title_font: pygame.font.Font, font: pygame.font.Font) -> None:
    screen.fill("#154734")
    title = title_font.render("Card Table", True, "#f7e9b9")
    hint = font.render("SPACE: deal a new hand     ESC: return to room", True, "#ffffff")
    screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0] // 2, 70)))
    screen.blit(hint, hint.get_rect(center=(WINDOW_SIZE[0] // 2, 125)))

    total_width = len(hand) * CARD_SIZE[0] + (len(hand) - 1) * 24
    first_x = (WINDOW_SIZE[0] - total_width) // 2
    for index, (name, image) in enumerate(hand):
        x = first_x + index * (CARD_SIZE[0] + 24)
        y = 255
        screen.blit(image, (x, y))
        label = font.render(name, True, "#ffffff")
        screen.blit(label, label.get_rect(center=(x + CARD_SIZE[0] // 2, y + CARD_SIZE[1] + 25)))


def draw_blackjack(
    screen: pygame.Surface,
    player_hand: list[tuple[str, pygame.Surface]],
    dealer_hand: list[tuple[str, pygame.Surface]],
    status: str,
    title_font: pygame.font.Font,
    font: pygame.font.Font,
) -> None:
    screen.fill("#154734")
    screen.blit(title_font.render("Blackjack", True, "#f7e9b9"), (50, 35))
    hint = "H: hit    S: stand    N: new round    ESC: return to room"
    screen.blit(font.render(hint, True, "#ffffff"), (50, 100))
    screen.blit(font.render(f"Dealer: {hand_value(dealer_hand)}", True, "#ffffff"), (50, 165))
    screen.blit(font.render(f"You: {hand_value(player_hand)}", True, "#ffffff"), (50, 430))
    if status:
        message = title_font.render(status, True, "#f7e9b9")
        screen.blit(message, message.get_rect(center=(WINDOW_SIZE[0] // 2, 130)))

    for y, hand in ((205, dealer_hand), (470, player_hand)):
        for index, (_, image) in enumerate(hand):
            screen.blit(image, (50 + index * (CARD_SIZE[0] + 24), y))


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode(WINDOW_SIZE, pygame.RESIZABLE)
    pygame.display.set_caption("The House Is You")
    clock = pygame.time.Clock()
    menu = MainMenu(screen)
    title_font = pygame.font.Font(None, 54)
    font = pygame.font.Font(None, 30)

    try:
        player_animations = load_player_animations()
        deck = load_cards()
        casino_backgrounds, casino_tables = load_casino_scenes()
    except FileNotFoundError as error:
        pygame.quit()
        raise SystemExit(error) from error

    player = pygame.Vector2(170, 520)
    facing = "right"
    animation_frame = 0
    animation_timer = 0.0
    mode = "menu"
    room = 0
    hand = random.sample(deck, min(HAND_SIZE, len(deck)))
    blackjack_player: list[tuple[str, pygame.Surface]] = []
    blackjack_dealer: list[tuple[str, pygame.Surface]] = []
    blackjack_status = "Press N to deal"
    running = True

    def new_blackjack_round() -> None:
        nonlocal blackjack_player, blackjack_dealer, blackjack_status
        blackjack_player = [random.choice(deck), random.choice(deck)]
        blackjack_dealer = [random.choice(deck), random.choice(deck)]
        blackjack_status = ""
        if hand_value(blackjack_player) == 21:
            blackjack_status = "Blackjack! Press N for a new round."

    while running:
        delta_time = clock.tick(60) / 1000
        now = pygame.time.get_ticks()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue
            if mode == "menu":
                action = menu.handle_event(event, now)
                if action == "quit":
                    running = False
                elif action == "play":
                    menu.audio.stop()
                    mode = "room"
                # Options is intentionally retained as the existing no-op
                # until an options screen is added to the project.
                continue
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    mode = "room"
                elif mode == "cards" and event.key == pygame.K_SPACE:
                    hand = random.sample(deck, min(HAND_SIZE, len(deck)))
                elif mode == "blackjack":
                    if event.key == pygame.K_n:
                        new_blackjack_round()
                    elif event.key == pygame.K_h and not blackjack_status:
                        blackjack_player.append(random.choice(deck))
                        if hand_value(blackjack_player) > 21:
                            blackjack_status = "Bust! Dealer wins. Press N for a new round."
                    elif event.key == pygame.K_s and not blackjack_status:
                        while hand_value(blackjack_dealer) < 17:
                            blackjack_dealer.append(random.choice(deck))
                        player_score = hand_value(blackjack_player)
                        dealer_score = hand_value(blackjack_dealer)
                        if dealer_score > 21 or player_score > dealer_score:
                            blackjack_status = "You win! Press N for a new round."
                        elif player_score < dealer_score:
                            blackjack_status = "Dealer wins. Press N for a new round."
                        else:
                            blackjack_status = "Push (tie). Press N for a new round."
                elif mode == "room" and event.key == pygame.K_e and player.distance_to(pygame.Vector2(TABLE.center)) < 190:
                    if room == 0:
                        mode = "cards"
                    else:
                        mode = "blackjack"
                        new_blackjack_round()

        if mode == "menu":
            menu.draw(now)
        elif mode == "cards":
            draw_card_game(screen, hand, title_font, font)
        elif mode == "blackjack":
            draw_blackjack(screen, blackjack_player, blackjack_dealer, blackjack_status, title_font, font)
        else:
            keys = pygame.key.get_pressed()
            movement = pygame.Vector2(keys[pygame.K_d] - keys[pygame.K_a], keys[pygame.K_s] - keys[pygame.K_w])
            walking = movement.length_squared() > 0
            if walking:
                movement = movement.normalize()
                player += movement * PLAYER_SPEED * delta_time
                if room == 0 and player.x >= WINDOW_SIZE[0] - PLAYER_SIZE[0] // 2:
                    room = 1
                    player.x = PLAYER_SIZE[0] // 2
                elif room == 1 and player.x <= PLAYER_SIZE[0] // 2:
                    room = 0
                    player.x = WINDOW_SIZE[0] - PLAYER_SIZE[0] // 2
                else:
                    player.x = max(PLAYER_SIZE[0] // 2, min(WINDOW_SIZE[0] - PLAYER_SIZE[0] // 2, player.x))
                player.y = max(130, min(WINDOW_SIZE[1] - PLAYER_SIZE[1] // 2, player.y))
                # Only horizontal movement changes facing. Vertical movement
                # keeps the last left/right orientation, including diagonals.
                if movement.x > 0:
                    next_facing = "right"
                elif movement.x < 0:
                    next_facing = "left"
                else:
                    next_facing = facing
                if next_facing != facing:
                    facing = next_facing
                    animation_frame = 0
                    animation_timer = 0.0
                animation_timer += delta_time
                while animation_timer >= PLAYER_ANIMATION_FRAME_DURATION:
                    animation_timer -= PLAYER_ANIMATION_FRAME_DURATION
                    animation_frame = (animation_frame + 1) % 2
            else:
                # Keep the last horizontal facing direction while idle.
                animation_frame = 0
                animation_timer = 0.0

            frame = player_animations[facing][animation_frame]
            draw_room(screen, player, frame, font, room, casino_backgrounds, casino_tables)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
