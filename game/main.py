"""The House Is You: explore rooms, deal cards, and play blackjack."""

from pathlib import Path
import random

import pygame

from game.menu import MainMenu
from game.blackjack_game import BlackjackGame
from game.player_state import PlayerState


WINDOW_SIZE = (1280, 720)
CARD_SIZE = (150, 210)
PLAYER_SIZE = (96, 96)
PLAYER_COLLISION_SIZE = (32, 32)
PLAYER_DISPLAY_SIZE = (72, 96)
BARTENDER_DISPLAY_SIZE = (48, 72)
PLAYER_SPEED = 300
PLAYER_ANIMATION_FRAME_DURATION = 0.12
SLOT_MACHINE_ANIMATION_FRAME_DURATION = 0.15
HAND_SIZE = 5
ASSETS = Path(__file__).resolve().parent.parent / "static" / "assets"
CARD_DIRECTORY = ASSETS / "cards"
PLAYER_SPRITE_DIRECTORY = ASSETS / "sprites"
CASINO_DIRECTORY = ASSETS / "2D Top Down Pixel Art Tileset Casino"
BARTENDER_IMAGE = ASSETS / "bartender.png"
CASINO_TILESET = CASINO_DIRECTORY / "2D_TopDown_Tileset_Casino_1024x512.png"
SLOT_MACHINE_SHEET = CASINO_DIRECTORY / "Animated Sprite Sheets" / "SlotMachinesAnimationSheet_0.png"
TABLE = pygame.Rect(465, 250, 350, 220)
CARD_TABLE_CENTER = pygame.Vector2(300, 450)
CENTER_TABLE_CENTER = pygame.Vector2(640, 235)
BLACKJACK_TABLE_CENTER = pygame.Vector2(980, 450)
SLOT_MACHINE_CENTERS = (
    pygame.Vector2(100, 100),
    pygame.Vector2(250, 100),
    pygame.Vector2(400, 100),
    pygame.Vector2(900, 100),
    pygame.Vector2(1050, 100),
    pygame.Vector2(1200, 100),
)
TABLE_INTERACTION_DISTANCE = 190
SLOT_MACHINE_INTERACTION_DISTANCE = 120


def load_player_animations() -> dict[str, list[pygame.Surface]]:
    """Load the two right-facing frames and cache their left-facing flips."""
    right_frames: list[pygame.Surface] = []
    for frame_index in range(2):
        path = PLAYER_SPRITE_DIRECTORY / f"player_right{frame_index}.png"
        if not path.exists():
            raise FileNotFoundError(f"Missing player sprite: {path}")
        image = pygame.image.load(path).convert_alpha()
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


def load_slot_machine_animation() -> list[pygame.Surface]:
    sheet = pygame.image.load(SLOT_MACHINE_SHEET).convert_alpha()
    frame_width, frame_height = 32, 48
    frames = []
    for frame_index in range(8):
        frame = sheet.subsurface((frame_index * frame_width, 0, frame_width, frame_height)).copy()
        frames.append(pygame.transform.scale(frame, (96, 144)))
    return frames


def load_bartender() -> pygame.Surface:
    image = pygame.image.load(BARTENDER_IMAGE).convert()
    image.set_colorkey((0, 0, 0))
    cropped = image.subsurface((95, 100, 220, 415)).copy()
    cropped.set_colorkey((0, 0, 0))
    return pygame.transform.scale(cropped, BARTENDER_DISPLAY_SIZE)


def player_rect(position: pygame.Vector2) -> pygame.Rect:
    rect = pygame.Rect(0, 0, *PLAYER_COLLISION_SIZE)
    rect.center = (round(position.x), round(position.y))
    return rect


def furniture_collision_rect(
    surface: pygame.Surface,
    center: pygame.Vector2,
    horizontal_margin: int,
    vertical_margin: int,
) -> pygame.Rect:
    rect = surface.get_rect(center=center)
    return rect.inflate(-horizontal_margin, -vertical_margin)


def move_player(
    player: pygame.Vector2,
    movement: pygame.Vector2,
    delta_time: float,
    obstacles: list[pygame.Rect],
) -> None:
    displacement = movement * PLAYER_SPEED * delta_time
    for axis in ("x", "y"):
        candidate = player.copy()
        setattr(candidate, axis, getattr(candidate, axis) + getattr(displacement, axis))
        if not any(player_rect(candidate).colliderect(obstacle) for obstacle in obstacles):
            setattr(player, axis, getattr(candidate, axis))


def draw_tutorial_path(
    screen: pygame.Surface,
    start: pygame.Vector2,
    end: pygame.Vector2,
) -> None:
    direction = end - start
    distance = direction.length()
    if distance == 0:
        return
    direction.normalize_ip()
    for offset in range(0, round(distance), 18):
        position = start + direction * offset
        pygame.draw.circle(screen, "#2b2410", position, 6)
        pygame.draw.circle(screen, "#f6d34a", position, 3)


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

    tile(background, red_carpet, pygame.Rect(0, 48, WINDOW_SIZE[0], WINDOW_SIZE[1] - 48))
    floor = pygame.Rect(96, 112, WINDOW_SIZE[0] - 192, WINDOW_SIZE[1] - 112)
    background.fill("#192c78", floor)
    tile(background, blue_carpet, floor)

    return background


def load_casino_scenes() -> tuple[
    pygame.Surface,
    list[pygame.Surface],
    pygame.Surface,
    pygame.Surface,
    list[pygame.Surface],
]:
    """Load the room, tables, bartender, and drinks from the casino tileset."""
    tileset = pygame.image.load(CASINO_TILESET).convert_alpha()
    room = make_casino_room(tileset, 0)
    poker_table = tileset.subsurface((912, 368, 112, 55))
    center_table = tileset.subsurface((512, 88, 112, 60))
    blackjack_table = tileset.subsurface((912, 197, 112, 55))
    drink = tileset.subsurface((650, 410, 10, 25))
    tables = [
        pygame.transform.scale(poker_table, (350, 190)),
        pygame.transform.scale(center_table, (400, 215)),
        pygame.transform.scale(blackjack_table, (390, 176)),
    ]
    return (
        room,
        tables,
        load_bartender(),
        pygame.transform.scale(drink, (22, 45)),
        load_slot_machine_animation(),
    )


def draw_room(
    screen: pygame.Surface,
    player: pygame.Vector2,
    image: pygame.Surface,
    font: pygame.font.Font,
    background: pygame.Surface,
    tables: list[pygame.Surface],
    bartender: pygame.Surface,
    drink: pygame.Surface,
    slot_machine_frames: list[pygame.Surface],
    slot_machine_frame: int,
    show_tutorial: bool,
) -> None:
    screen.blit(background, (0, 0))
    if show_tutorial:
        draw_tutorial_path(screen, player, BLACKJACK_TABLE_CENTER)
    slot_machine = slot_machine_frames[slot_machine_frame]
    for center in SLOT_MACHINE_CENTERS:
        screen.blit(slot_machine, slot_machine.get_rect(center=center))
    screen.blit(tables[0], tables[0].get_rect(center=CARD_TABLE_CENTER))
    screen.blit(bartender, bartender.get_rect(midbottom=(CENTER_TABLE_CENTER.x, CENTER_TABLE_CENTER.y - 30)))
    screen.blit(tables[1], tables[1].get_rect(center=CENTER_TABLE_CENTER))
    for position in ((600, 220), (640, 205), (680, 220)):
        screen.blit(drink, drink.get_rect(center=position))
    screen.blit(tables[2], tables[2].get_rect(center=BLACKJACK_TABLE_CENTER))

    screen.blit(font.render("THE HOUSE IS YOU  —  CASINO FLOOR", True, "#ffffff"), (40, 30))
    screen.blit(image, image.get_rect(center=player))

    interactions = [
        (player.distance_to(CARD_TABLE_CENTER), CARD_TABLE_CENTER, TABLE_INTERACTION_DISTANCE, "play poker"),
        (player.distance_to(BLACKJACK_TABLE_CENTER), BLACKJACK_TABLE_CENTER, TABLE_INTERACTION_DISTANCE, "play blackjack"),
        *(
            (player.distance_to(center), center, SLOT_MACHINE_INTERACTION_DISTANCE, "use the slot machine")
            for center in SLOT_MACHINE_CENTERS
        ),
    ]
    available_interactions = [item for item in interactions if item[0] < item[2]]
    if available_interactions:
        _, _, _, action = min(
            available_interactions,
            key=lambda item: item[0],
        )
        prompt = font.render(f"Press E to {action}", True, "#ffffff")
        screen.blit(prompt, prompt.get_rect(center=(WINDOW_SIZE[0] // 2, WINDOW_SIZE[1] // 2)))
    else:
        hint = font.render("WASD: move     E: use the nearby game", True, "#ffffff")
        screen.blit(hint, (40, 650))


def draw_card_game(
    screen: pygame.Surface,
    hand: list[tuple[str, pygame.Surface]],
    title_font: pygame.font.Font,
    font: pygame.font.Font,
) -> None:
    screen.fill("#154734")
    title = title_font.render("Poker Table", True, "#f7e9b9")
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


def draw_slot_machine_game(
    screen: pygame.Surface,
    slot_machine: pygame.Surface,
    title_font: pygame.font.Font,
    font: pygame.font.Font,
) -> None:
    screen.fill("#111827")
    title = title_font.render("SLOT MACHINE", True, "#f7e9b9")
    hint = font.render("This machine is a preview for now     ESC: return to room", True, "#ffffff")
    screen.blit(title, title.get_rect(center=(WINDOW_SIZE[0] // 2, 90)))
    screen.blit(hint, hint.get_rect(center=(WINDOW_SIZE[0] // 2, 150)))
    machine = pygame.transform.scale(slot_machine, (192, 288))
    screen.blit(machine, machine.get_rect(center=(WINDOW_SIZE[0] // 2, 390)))


def main() -> None:
    pygame.init()
    screen = pygame.display.set_mode(WINDOW_SIZE, pygame.FULLSCREEN | pygame.SCALED)
    pygame.display.set_caption("The House Is You")
    clock = pygame.time.Clock()
    menu = MainMenu(screen)
    player_state = PlayerState(chips=200)
    blackjack_game: BlackjackGame | None = None
    title_font = pygame.font.Font(None, 54)
    font = pygame.font.Font(None, 30)

    try:
        player_animations = load_player_animations()
        deck = load_cards()
        casino_background, casino_tables, bartender, drink, slot_machine_frames = load_casino_scenes()
    except FileNotFoundError as error:
        pygame.quit()
        raise SystemExit(error) from error

    collision_rects = [
        furniture_collision_rect(casino_tables[0], CARD_TABLE_CENTER, 30, 45),
        furniture_collision_rect(casino_tables[2], BLACKJACK_TABLE_CENTER, 30, 40),
    ]
    player = pygame.Vector2(80, 600)
    facing = "right"
    animation_frame = 0
    animation_timer = 0.0
    slot_machine_frame = 0
    slot_machine_timer = 0.0
    mode = "menu"
    show_tutorial = True
    hand = random.sample(deck, min(HAND_SIZE, len(deck)))
    running = True

    while running:
        delta_time = clock.tick(60) / 1000
        slot_machine_timer += delta_time
        while slot_machine_timer >= SLOT_MACHINE_ANIMATION_FRAME_DURATION:
            slot_machine_timer -= SLOT_MACHINE_ANIMATION_FRAME_DURATION
            slot_machine_frame = (slot_machine_frame + 1) % len(slot_machine_frames)
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
                continue
            if mode == "blackjack" and blackjack_game is not None:
                action = blackjack_game.handle_event(event)
                if action == "room":
                    mode = "room"
                continue
            if mode == "slots":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    mode = "room"
                continue
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    mode = "room"
                elif mode == "cards" and event.key == pygame.K_SPACE:
                    hand = random.sample(deck, min(HAND_SIZE, len(deck)))
                elif mode == "room" and event.key == pygame.K_e:
                    interactions = (
                        (player.distance_to(CARD_TABLE_CENTER), TABLE_INTERACTION_DISTANCE, "poker"),
                        (player.distance_to(BLACKJACK_TABLE_CENTER), TABLE_INTERACTION_DISTANCE, "blackjack"),
                        *(
                            (player.distance_to(center), SLOT_MACHINE_INTERACTION_DISTANCE, "slots")
                            for center in SLOT_MACHINE_CENTERS
                        ),
                    )
                    available_interactions = [
                        interaction for interaction in interactions if interaction[0] < interaction[1]
                    ]
                    if not available_interactions:
                        continue
                    nearest = min(
                        available_interactions,
                        key=lambda item: item[0],
                    )
                    if nearest[2] == "poker":
                        mode = "cards"
                    elif nearest[2] == "blackjack":
                        show_tutorial = False
                        blackjack_game = BlackjackGame(screen, player_state)
                        mode = "blackjack"
                    elif nearest[2] == "slots":
                        mode = "slots"

        if mode == "menu":
            menu.draw(now)
        elif mode == "cards":
            draw_card_game(screen, hand, title_font, font)
        elif mode == "slots":
            draw_slot_machine_game(screen, slot_machine_frames[slot_machine_frame], title_font, font)
        elif mode == "blackjack" and blackjack_game is not None:
            blackjack_game.update()
            blackjack_game.draw()
        else:
            keys = pygame.key.get_pressed()
            movement = pygame.Vector2(keys[pygame.K_d] - keys[pygame.K_a], keys[pygame.K_s] - keys[pygame.K_w])
            walking = movement.length_squared() > 0
            if walking:
                movement = movement.normalize()
                move_player(player, movement, delta_time, collision_rects)
                player.x = max(PLAYER_SIZE[0] // 2, min(WINDOW_SIZE[0] - PLAYER_SIZE[0] // 2, player.x))
                player.y = max(130, min(WINDOW_SIZE[1] - PLAYER_SIZE[1] // 2, player.y))
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
                animation_frame = 0
                animation_timer = 0.0

            frame = player_animations[facing][animation_frame]
            draw_room(
                screen,
                player,
                frame,
                font,
                casino_background,
                casino_tables,
                bartender,
                drink,
                slot_machine_frames,
                slot_machine_frame,
                show_tutorial,
            )

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()