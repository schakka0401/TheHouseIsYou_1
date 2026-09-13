"""The House Is You: explore rooms, deal cards, and play blackjack."""

from pathlib import Path

import pygame

from game.menu import AnimatedImageButton, MainMenu, MenuButton, PRESS_MS, SettingsMenu, serif_font
from game.blackjack_game import BlackjackGame
from game.poker_game import PokerGame
from game.player_state import PlayerState
from game.audio import AudioManager, FOOTSTEP_INTERVAL_MS


WINDOW_SIZE = (1280, 720)
CARD_SIZE = (150, 210)
PLAYER_SIZE = (96, 96)
PLAYER_COLLISION_SIZE = (32, 32)
PLAYER_DISPLAY_SIZE = (72, 96)
SLOT_PLAYER_DISPLAY_SIZE = (54, 72)
DEALER_DISPLAY_SIZE = (54, 72)
BARTENDER_DISPLAY_SIZE = (54, 81)
STOOL_DISPLAY_SIZE = (42, 59)
BEER_DISPLAY_SIZE = (18, 23)
CUP_DISPLAY_SIZE = (16, 22)
PLAYER_SPEED = 300
PLAYER_ANIMATION_FRAME_DURATION = 0.12
SLOT_MACHINE_ANIMATION_FRAME_DURATION = 0.15
HAND_SIZE = 5
ASSETS = Path(__file__).resolve().parent.parent / "static" / "assets"
CARD_DIRECTORY = ASSETS / "cards"
PLAYER_SPRITE_DIRECTORY = ASSETS / "sprites"
IMAGE_DIRECTORY = ASSETS / "images"
CASINO_DIRECTORY = ASSETS / "2D Top Down Pixel Art Tileset Casino"
BARTENDER_IMAGE = ASSETS / "bartender.png"
STOOL_IMAGE = ASSETS / "stool.png"
BEER_IMAGE = ASSETS / "beer.png"
CUP_IMAGE = ASSETS / "cup.png"
DEALER_IMAGE = ASSETS / "dealer.png"
BARTENDER_PORTRAIT_IMAGE = ASSETS / "bartender_portrait.png"
BARTENDER_BACKGROUND_IMAGE = ASSETS / "bartender_background.png"
POKER_TABLE_IMAGE = ASSETS / "poker_table_clean.png"
BLACKJACK_TABLE_IMAGE = ASSETS / "blackjack_table_clean.png"
CHARACTER_SHEET = ASSETS / "2D Top Down Pixel Art Characters" / "000.png"
CASINO_TILESET = CASINO_DIRECTORY / "2D_TopDown_Tileset_Casino_1024x512.png"
SLOT_MACHINE_SHEET = CASINO_DIRECTORY / "Animated Sprite Sheets" / "SlotMachinesAnimationSheet_0.png"
SLOT_PLAYER_IMAGE = ASSETS / "slot_player.png"
SLOT_PLAYER_RIGHT_IMAGE = ASSETS / "slot_player_right.png"
BARTENDER_INTERACTION_DISTANCE = 125
TABLE = pygame.Rect(465, 250, 350, 220)
DEBUG_MENU_HITBOXES = False

def find_image_asset(stem: str) -> Path:
    matches = sorted(IMAGE_DIRECTORY.glob(f"{stem}.*"))
    if not matches:
        raise FileNotFoundError(f"Missing image asset: {IMAGE_DIRECTORY / (stem + '.*')}")
    return matches[0]


def load_ui_assets() -> tuple[pygame.Surface, pygame.Surface, pygame.Surface]:
    """Load the supplied UI artwork once during game initialization."""
    home_button = pygame.image.load(find_image_asset("home_button")).convert_alpha()
    # The current supplied file is options.png; accept options_menu.* too so
    # the loader follows the asset's semantic name without assuming an extension.
    options_matches = sorted(IMAGE_DIRECTORY.glob("options_menu.*")) or sorted(IMAGE_DIRECTORY.glob("options.*"))
    if not options_matches:
        raise FileNotFoundError(f"Missing image asset: {IMAGE_DIRECTORY / 'options_menu.*'}")
    options_menu = pygame.image.load(options_matches[0]).convert_alpha()
    settings_menu = pygame.image.load(find_image_asset("settings")).convert_alpha()
    return home_button, options_menu, settings_menu


def load_bartender_dialogue_assets() -> tuple[pygame.Surface, pygame.Surface]:
    if BARTENDER_PORTRAIT_IMAGE.exists() and BARTENDER_BACKGROUND_IMAGE.exists():
        background = pygame.image.load(BARTENDER_PORTRAIT_IMAGE).convert()
        portrait = pygame.image.load(BARTENDER_BACKGROUND_IMAGE).convert()
        return (
            pygame.transform.smoothscale(background, WINDOW_SIZE),
            pygame.transform.smoothscale(portrait, (390, 390)),
        )

    # Dialogue artwork is optional in this checkout. Keep the interaction
    # available with a simple generated backdrop and the already-loaded bar
    # character instead of failing during application startup.
    background = pygame.Surface(WINDOW_SIZE)
    background.fill("#17233b")
    portrait = pygame.transform.smoothscale(load_bartender(), (390, 390))
    return background, portrait


def scaled_options_menu(image: pygame.Surface, screen_size: tuple[int, int]) -> pygame.Surface:
    """Scale the complete menu artwork proportionally to fit the screen."""
    screen_width, screen_height = screen_size
    scale = min((screen_width * 0.72) / image.get_width(), (screen_height * 0.90) / image.get_height())
    size = (max(1, round(image.get_width() * scale)), max(1, round(image.get_height() * scale)))
    return pygame.transform.smoothscale(image, size)


def visible_asset_rect(image: pygame.Surface) -> pygame.Rect:
    """Return the main visible component, excluding transparent canvas padding."""
    components = pygame.mask.from_surface(image, threshold=32).get_bounding_rects()
    return max(components, key=lambda rect: rect.width * rect.height) if components else image.get_rect()


def scale_asset_rect(source_rect: pygame.Rect, source_size: tuple[int, int], destination_rect: pygame.Rect) -> pygame.Rect:
    """Map a source-image rectangle into the image's displayed screen rectangle."""
    scale_x = destination_rect.width / source_size[0]
    scale_y = destination_rect.height / source_size[1]
    return pygame.Rect(
        destination_rect.left + round(source_rect.left * scale_x),
        destination_rect.top + round(source_rect.top * scale_y),
        round(source_rect.width * scale_x),
        round(source_rect.height * scale_y),
    )


def make_options_buttons(panel_rect: pygame.Rect, face: pygame.font.Font) -> list[MenuButton]:
    """Create the in-game buttons relative to the visible decorative frame."""
    pw = panel_rect.width
    ph = panel_rect.height
    cx = panel_rect.centerx
    py = panel_rect.top
    button_width = int(pw * 0.68)
    button_height = int(ph * 0.105)
    center_ys = (py + ph * 0.39, py + ph * 0.59, py + ph * 0.79)
    labels = ("RESUME", "SETTINGS", "MAIN MENU")
    buttons = []
    for label, center_y in zip(labels, center_ys):
        button_rect = pygame.Rect(0, 0, button_width, button_height)
        button_rect.center = (cx, round(center_y))
        buttons.append(MenuButton(label, 0, face, button_rect))
    return buttons


def select_options_button(buttons: list[MenuButton], index: int, menu_audio, play_sound: bool = True) -> int:
    if not buttons:
        return 0
    index %= len(buttons)
    old_index = next((i for i, button in enumerate(buttons) if button.selected), 0)
    changed = index != old_index
    for button_index, button in enumerate(buttons):
        button.selected = button_index == index
    if changed and play_sound:
        # MenuAudio owns the already-loaded main-menu UI sound objects.
        menu_audio.switch()
    return index
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
BEVERAGE_POSITIONS = ((585, 255), (640, 245), (695, 255))
STOOL_POSITIONS = (
    (145, 550),
    (300, 590),
    (455, 550),
    (560, 345),
    (640, 365),
    (720, 345),
    (860, 555),
    (980, 575),
    (1100, 555),
)


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


def load_slot_player(image_path: Path) -> pygame.Surface:
    # Some asset checkouts do not include the optional slot-player renders.
    # Fall back to the already-required player sprites so the casino scene
    # remains launchable while preserving the intended slot-machine layout.
    if not image_path.exists():
        fallback_name = "player_right1.png" if "right" in image_path.stem.lower() else "player_right0.png"
        image_path = PLAYER_SPRITE_DIRECTORY / fallback_name
        image = pygame.image.load(image_path).convert_alpha()
        return pygame.transform.smoothscale(image, SLOT_PLAYER_DISPLAY_SIZE)

    image = pygame.image.load(image_path).convert()
    image.set_colorkey((0, 0, 0))
    cropped = image.subsurface(visible_asset_rect(image)).copy()
    cropped.set_colorkey((0, 0, 0))
    return pygame.transform.scale(cropped, SLOT_PLAYER_DISPLAY_SIZE)


def load_bartender() -> pygame.Surface:
    if BARTENDER_IMAGE.exists():
        image = pygame.image.load(BARTENDER_IMAGE).convert()
        image.set_colorkey((0, 0, 0))
        cropped = image.subsurface((95, 100, 220, 415)).copy()
    else:
        # The pulled asset set contains the character sheet but not the
        # bartender.png referenced by the pulled loader. Use one sheet cell as
        # a safe fallback so the merged game still starts and renders the bar.
        image = pygame.image.load(CHARACTER_SHEET).convert()
        cell_size = (image.get_width() // 4, image.get_height() // 6)
        cropped = image.subsurface((0, 0, *cell_size)).copy()
    cropped.set_colorkey((0, 0, 0))
    return pygame.transform.scale(cropped, BARTENDER_DISPLAY_SIZE)


def load_stool() -> pygame.Surface:
    image = pygame.image.load(STOOL_IMAGE).convert()
    image.set_colorkey((0, 0, 0))
    cropped = image.subsurface((400, 420, 450, 650)).copy()
    cropped.set_colorkey((0, 0, 0))
    return pygame.transform.scale(cropped, STOOL_DISPLAY_SIZE)


def load_dealer() -> pygame.Surface:
    if DEALER_IMAGE.exists():
        image = pygame.image.load(DEALER_IMAGE).convert()
        image.set_colorkey((0, 0, 0))
        cropped = image.subsurface((197, 191, 630, 1142)).copy()
    else:
        # The world dealer render is optional; use a character-sheet cell so
        # the casino remains launchable when that decorative asset is absent.
        image = pygame.image.load(CHARACTER_SHEET).convert()
        cell_width = image.get_width() // 4
        cell_height = image.get_height() // 6
        cropped = image.subsurface((cell_width, 0, cell_width, cell_height)).copy()
    cropped.set_colorkey((0, 0, 0))
    return pygame.transform.scale(cropped, DEALER_DISPLAY_SIZE)


def load_poker_table() -> pygame.Surface:
    image = pygame.image.load(POKER_TABLE_IMAGE).convert_alpha()
    return pygame.transform.scale(image, (390, 230))


def load_blackjack_table() -> pygame.Surface:
    image = pygame.image.load(BLACKJACK_TABLE_IMAGE).convert_alpha()
    return pygame.transform.scale(image, (390, 225))


def load_beer() -> pygame.Surface:
    image = pygame.image.load(BEER_IMAGE).convert_alpha()
    return pygame.transform.scale(image, BEER_DISPLAY_SIZE)


def load_cup() -> pygame.Surface:
    image = pygame.image.load(CUP_IMAGE).convert_alpha()
    return pygame.transform.scale(image, CUP_DISPLAY_SIZE)


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
    pygame.Surface,
    pygame.Surface,
    list[pygame.Surface],
    pygame.Surface,
    pygame.Surface,
    pygame.Surface,
    pygame.Surface,
]:
    """Load the room, tables, bartender, and drinks from the casino tileset."""
    tileset = pygame.image.load(CASINO_TILESET).convert_alpha()
    room = make_casino_room(tileset, 0)
    center_table = tileset.subsurface((512, 88, 112, 60))
    drink = tileset.subsurface((650, 410, 10, 25))
    tables = [
        load_poker_table(),
        pygame.transform.scale(center_table, (400, 215)),
        load_blackjack_table(),
    ]
    return (
        room,
        tables,
        load_bartender(),
        pygame.transform.scale(drink, (22, 45)),
        load_slot_machine_animation(),
        load_slot_player(SLOT_PLAYER_IMAGE),
        load_slot_player(SLOT_PLAYER_RIGHT_IMAGE),
        load_stool(),
        load_beer(),
        load_cup(),
        load_dealer(),
    )


def draw_room(
    screen: pygame.Surface,
    player: pygame.Vector2,
    image: pygame.Surface,
    font: pygame.font.Font,
    background: pygame.Surface,
    tables: list[pygame.Surface],
    bartender: pygame.Surface,
    stool: pygame.Surface,
    drink: pygame.Surface,
    slot_machine_frames: list[pygame.Surface],
    slot_player: pygame.Surface,
    slot_player_right: pygame.Surface,
    slot_machine_frame: int,
    show_tutorial: bool,
    beer: pygame.Surface,
    cup: pygame.Surface,
    dealer: pygame.Surface,
) -> None:
    screen.blit(background, (0, 0))
    slot_machine = slot_machine_frames[slot_machine_frame]
    for center in SLOT_MACHINE_CENTERS:
        screen.blit(slot_machine, slot_machine.get_rect(center=center))
    screen.blit(
        slot_player,
        slot_player.get_rect(midbottom=(SLOT_MACHINE_CENTERS[0].x - 18, 170)),
    )
    screen.blit(
        slot_player_right,
        slot_player_right.get_rect(midbottom=(SLOT_MACHINE_CENTERS[4].x - 18, 170)),
    )
    nearby_tables = [
        (player.distance_to(CARD_TABLE_CENTER), tables[0], CARD_TABLE_CENTER, "play poker"),
        (player.distance_to(BLACKJACK_TABLE_CENTER), tables[2], BLACKJACK_TABLE_CENTER, "play blackjack"),
    ]
    nearby_tables = [item for item in nearby_tables if item[0] < TABLE_INTERACTION_DISTANCE]
    for _, table, center, _ in nearby_tables:
        glow = pygame.Surface(WINDOW_SIZE, pygame.SRCALPHA)
        glow_rect = table.get_rect(center=center).inflate(18, 18)
        pygame.draw.ellipse(glow, (246, 211, 74, 130), glow_rect, width=8)
        screen.blit(glow, (0, 0))
    dealer_position = (CARD_TABLE_CENTER.x, CARD_TABLE_CENTER.y - 90)
    screen.blit(dealer, dealer.get_rect(midbottom=dealer_position))
    screen.blit(tables[0], tables[0].get_rect(center=CARD_TABLE_CENTER))
    screen.blit(bartender, bartender.get_rect(midbottom=(CENTER_TABLE_CENTER.x, CENTER_TABLE_CENTER.y + 20)))
    screen.blit(tables[1], tables[1].get_rect(center=CENTER_TABLE_CENTER))
    for index, position in enumerate(BEVERAGE_POSITIONS):
        beverage = beer if index == 1 else cup
        screen.blit(beverage, beverage.get_rect(center=position))
    dealer_position = (BLACKJACK_TABLE_CENTER.x, BLACKJACK_TABLE_CENTER.y - 80)
    screen.blit(dealer, dealer.get_rect(midbottom=dealer_position))
    screen.blit(tables[2], tables[2].get_rect(center=BLACKJACK_TABLE_CENTER))
    for position in STOOL_POSITIONS:
        screen.blit(stool, stool.get_rect(center=position))
    screen.blit(image, image.get_rect(center=player))
    nearby_interactions = [
        (distance, action)
        for distance, _, _, action in nearby_tables
    ]
    bartender_distance = player.distance_to(CENTER_TABLE_CENTER)
    if bartender_distance < BARTENDER_INTERACTION_DISTANCE:
        nearby_interactions.append((bartender_distance, "interact"))
    if nearby_interactions:
        _, action = min(nearby_interactions, key=lambda item: item[0])
        prompt = serif_font(30, True).render(f"Press E to {action}", True, "#f7e9b9")
        screen.blit(prompt, prompt.get_rect(center=(WINDOW_SIZE[0] // 2, 610)))


def draw_bartender_dialogue(
    screen: pygame.Surface,
    background: pygame.Surface,
    portrait: pygame.Surface,
    page: int,
) -> None:
    screen.blit(background, (0, 0))
    overlay = pygame.Surface(WINDOW_SIZE, pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 105))
    screen.blit(overlay, (0, 0))
    portrait_rect = portrait.get_rect(bottomright=(WINDOW_SIZE[0], WINDOW_SIZE[1]))
    screen.blit(portrait, portrait_rect)

    dialogue_box = pygame.Surface((890, 170), pygame.SRCALPHA)
    dialogue_box.fill((0, 0, 0, 190))
    pygame.draw.rect(dialogue_box, "#d29a32", dialogue_box.get_rect(), width=2, border_radius=10)
    screen.blit(dialogue_box, (0, 550))
    text_font = serif_font(28, True)
    message_lines = (
        ("Hey, nice to meet you.",)
        if page == 0
        else (
            "We have blackjack and poker for you to try out.",
            "Have fun and enjoy!",
        )
    )
    for line_index, line in enumerate(message_lines):
        message = text_font.render(line, True, "#f7e9b9")
        screen.blit(message, (30, 580 + line_index * 38))
    hint_text = "CLICK / ENTER: next     ESC: return to the casino floor" if page == 0 else "ESC: return to the casino floor"
    hint = serif_font(20).render(hint_text, True, "#d8d0b8")
    screen.blit(hint, (30, 685))


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
    audio = AudioManager()
    menu = MainMenu(screen, audio)
    player_state = PlayerState(chips=200)
    blackjack_game: BlackjackGame | None = None
    poker_game: PokerGame | None = None
    title_font = pygame.font.Font(None, 54)
    font = pygame.font.Font(None, 30)

    try:
        player_animations = load_player_animations()
        (
            casino_background,
            casino_tables,
            bartender,
            drink,
            slot_machine_frames,
            slot_player,
            slot_player_right,
            stool,
            beer,
            cup,
            dealer,
        ) = load_casino_scenes()
        home_button_image, options_menu_image, settings_menu_image = load_ui_assets()
        bartender_dialogue_background, bartender_portrait = load_bartender_dialogue_assets()
    except FileNotFoundError as error:
        pygame.quit()
        raise SystemExit(error) from error

    settings_screen = SettingsMenu(screen, settings_menu_image, audio, menu.audio)
    options_panel_source_rect = visible_asset_rect(options_menu_image)
    collision_rects = [
        furniture_collision_rect(casino_tables[0], CARD_TABLE_CENTER, 30, 45),
        furniture_collision_rect(casino_tables[2], BLACKJACK_TABLE_CENTER, 30, 40),
    ]
    center_table_rect = casino_tables[1].get_rect(center=CENTER_TABLE_CENTER)
    collision_rects.append(
        pygame.Rect(
            center_table_rect.centerx - 110,
            center_table_rect.bottom - 65,
            220,
            24,
        )
    )
    player = pygame.Vector2(80, 600)
    facing = "right"
    animation_frame = 0
    animation_timer = 0.0
    footstep_timer_ms = 0.0
    next_step = 0
    was_moving = False
    mode = "menu"
    game_menu_open = False
    home_button_rect = pygame.Rect(0, 0, 0, 0)
    menu_rect = pygame.Rect(0, 0, 0, 0)
    options_buttons: list[MenuButton] = []
    options_layout_rect: pygame.Rect | None = None
    options_selected_index = 0
    options_face = serif_font(34, True)
    home_image_button = AnimatedImageButton(home_button_image, pygame.Rect(0, 0, 0, 0), hover_scale=1.08)
    was_home_hovered = False
    last_options_mouse_pos = pygame.mouse.get_pos()
    cached_screen_size: tuple[int, int] | None = None
    cached_options_surface: pygame.Surface | None = None
    pending_home_open_at: int | None = None
    slot_machine_frame = 0
    slot_machine_timer = 0.0
    show_tutorial = True
    bartender_dialogue_page = 0
    running = True

    def open_game_options() -> None:
        nonlocal game_menu_open, options_selected_index, last_options_mouse_pos
        audio.stop_footsteps()
        game_menu_open = True
        options_selected_index = 0
        last_options_mouse_pos = pygame.mouse.get_pos()
        for button_index, button in enumerate(options_buttons):
            button.selected = button_index == options_selected_index

    def close_game_menu() -> None:
        nonlocal game_menu_open
        game_menu_open = False

    def activate_option(index: int, now: int) -> None:
        nonlocal mode, was_moving
        if not options_buttons:
            return
        options_buttons[index].press(now)
        menu.audio.click()
        if index == 0:
            close_game_menu()
        elif index == 1:
            settings_screen.open("game_menu")
            mode = "settings"
        else:
            close_game_menu()
            audio.stop_footsteps()
            was_moving = False
            audio.stop_music()
            menu.audio.start()
            mode = "menu"

    while running:
        delta_time = clock.tick(60) / 1000
        slot_machine_timer += delta_time
        while slot_machine_timer >= SLOT_MACHINE_ANIMATION_FRAME_DURATION:
            slot_machine_timer -= SLOT_MACHINE_ANIMATION_FRAME_DURATION
            slot_machine_frame = (slot_machine_frame + 1) % len(slot_machine_frames)
        now = pygame.time.get_ticks()
        screen_width, screen_height = screen.get_size()
        home_size = max(64, min(112, round(screen_height * 0.12)))
        home_button_rect = pygame.Rect(0, 0, home_size, home_size)
        home_button_rect.topright = (screen_width - 24, 24)
        home_image_button.rect = home_button_rect
        if pending_home_open_at is not None and now >= pending_home_open_at:
            pending_home_open_at = None
            open_game_options()
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
                continue
            if mode == "menu":
                action = menu.handle_event(event, now)
                if action == "quit":
                    running = False
                elif action == "play":
                    audio.stop_footsteps()
                    menu.audio.stop()
                    audio.play_music("main_game_theme")
                    mode = "room"
                elif action == "options":
                    settings_screen.open("main_menu")
                    mode = "settings"
                continue
            if mode == "settings":
                action = settings_screen.handle_event(event, now)
                if action == "back":
                    mode = "menu" if settings_screen.return_target == "main_menu" else "room"
                continue
            if mode == "blackjack" and blackjack_game is not None:
                action = blackjack_game.handle_event(event)
                if action == "room":
                    mode = "room"
                continue
            if mode == "poker" and poker_game is not None:
                action = poker_game.handle_event(event)
                if action == "room":
                    mode = "room"
                continue
            if mode == "bartender":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    mode = "room"
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    bartender_dialogue_page = min(1, bartender_dialogue_page + 1)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    bartender_dialogue_page = min(1, bartender_dialogue_page + 1)
                continue
            if mode == "slots":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    mode = "room"
                continue
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if mode == "room":
                        if game_menu_open:
                            close_game_menu()
                        else:
                            was_moving = False
                            open_game_options()
                    elif mode == "poker":
                        mode = "room"
                    else:
                        mode = "room"
                elif mode == "room" and game_menu_open and event.key in (pygame.K_w, pygame.K_UP, pygame.K_s, pygame.K_DOWN):
                    direction = -1 if event.key in (pygame.K_w, pygame.K_UP) else 1
                    options_selected_index = select_options_button(
                        options_buttons, options_selected_index + direction, menu.audio
                    )
                elif mode == "room" and game_menu_open and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                    activate_option(options_selected_index, now)
                elif mode == "room" and event.key == pygame.K_e:
                    interactions = (
                        (player.distance_to(CENTER_TABLE_CENTER), BARTENDER_INTERACTION_DISTANCE, "bartender"),
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
                    nearest = min(available_interactions, key=lambda item: item[0])
                    if nearest[2] == "poker":
                        audio.stop_footsteps()
                        poker_game = PokerGame(screen, player_state, menu_audio=menu.audio)
                        mode = "poker"
                    elif nearest[2] == "bartender":
                        audio.stop_footsteps()
                        bartender_dialogue_page = 0
                        mode = "bartender"
                    elif nearest[2] == "blackjack":
                        audio.stop_footsteps()
                        show_tutorial = False
                        blackjack_game = BlackjackGame(screen, player_state, menu_audio=menu.audio)
                        mode = "blackjack"
                    elif nearest[2] == "slots":
                        audio.stop_footsteps()
                        mode = "slots"
            elif mode == "room" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if game_menu_open:
                    clicked_index = next(
                        (index for index, button in enumerate(options_buttons) if button.contains(event.pos)),
                        None,
                    )
                    if clicked_index is not None:
                        options_selected_index = select_options_button(
                            options_buttons, clicked_index, menu.audio, False
                        )
                        activate_option(clicked_index, now)
                elif home_button_rect.collidepoint(event.pos):
                    home_image_button.press(now)
                    menu.audio.click()
                    audio.stop_footsteps()
                    was_moving = False
                    pending_home_open_at = now + PRESS_MS
                    was_home_hovered = False
            elif mode == "room" and game_menu_open and event.type == pygame.MOUSEMOTION:
                if event.pos != last_options_mouse_pos:
                    last_options_mouse_pos = event.pos
                    hovered_index = next(
                        (index for index, button in enumerate(options_buttons) if button.contains(event.pos)),
                        None,
                    )
                    if hovered_index is not None:
                        options_selected_index = select_options_button(options_buttons, hovered_index, menu.audio)
                    # Keep the current selection when the pointer leaves the
                    # panel, matching the main menu's persistent selection.
        if mode == "menu":
            menu.draw(now)
        elif mode == "settings":
            settings_screen.draw(now)
        elif mode == "poker" and poker_game is not None:
            poker_game.update()
            poker_game.draw()
        elif mode == "bartender":
            draw_bartender_dialogue(
                screen,
                bartender_dialogue_background,
                bartender_portrait,
                bartender_dialogue_page,
            )
        elif mode == "slots":
            draw_slot_machine_game(screen, slot_machine_frames[slot_machine_frame], title_font, font)
        elif mode == "blackjack" and blackjack_game is not None:
            blackjack_game.update()
            blackjack_game.draw()
        else:
            # The room remains visible beneath the pause panel, but no gameplay
            # input, interaction, animation, or footsteps run while paused.
            keys = pygame.key.get_pressed() if not game_menu_open and pending_home_open_at is None else None
            movement = pygame.Vector2(0, 0) if keys is None else pygame.Vector2(
                (keys[pygame.K_RIGHT] or keys[pygame.K_d]) - (keys[pygame.K_LEFT] or keys[pygame.K_a]),
                (keys[pygame.K_DOWN] or keys[pygame.K_s]) - (keys[pygame.K_UP] or keys[pygame.K_w])
            )
            walking_input = movement.length_squared() > 0
            old_position = player.copy()
            if walking_input:
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

            actual_movement = player.distance_to(old_position) > 0.01
            if actual_movement:
                if not was_moving:
                    # Make the first step audible immediately, then return to
                    # the normal timed rhythm.
                    audio.play_step(next_step)
                    next_step = 1 - next_step
                    footstep_timer_ms = 0.0
                else:
                    footstep_timer_ms += delta_time * 1000
                while footstep_timer_ms >= FOOTSTEP_INTERVAL_MS:
                    footstep_timer_ms -= FOOTSTEP_INTERVAL_MS
                    audio.play_step(next_step)
                    next_step = 1 - next_step
                was_moving = True
            else:
                footstep_timer_ms = 0.0
                audio.stop_footsteps()
                was_moving = False

            frame = player_animations[facing][animation_frame]
            draw_room(
                screen,
                player,
                frame,
                font,
                casino_background,
                casino_tables,
                bartender,
                stool,
                drink,
                slot_machine_frames,
                slot_player,
                slot_player_right,
                slot_machine_frame,
                show_tutorial,
                beer,
                cup,
                dealer,
            )

            screen_width, screen_height = screen.get_size()
            if cached_screen_size != (screen_width, screen_height):
                cached_screen_size = (screen_width, screen_height)
                home_size = max(64, min(112, round(screen_height * 0.12)))
                cached_options_surface = scaled_options_menu(options_menu_image, cached_screen_size)
            home_button_rect = pygame.Rect(0, 0, home_size, home_size)
            home_button_rect.topright = (screen_width - 24, 24)
            home_image_button.rect = home_button_rect

            if game_menu_open:
                audio.stop_footsteps()
                menu_surface = cached_options_surface
                menu_rect = menu_surface.get_rect(center=screen.get_rect().center)
                panel_rect = scale_asset_rect(
                    options_panel_source_rect,
                    options_menu_image.get_size(),
                    menu_rect,
                )
                if options_layout_rect != panel_rect:
                    options_buttons = make_options_buttons(panel_rect, options_face)
                    options_layout_rect = panel_rect.copy()
                    options_selected_index = select_options_button(
                        options_buttons, options_selected_index, menu.audio, False
                    )
                overlay = pygame.Surface(screen.get_size(), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 135))
                screen.blit(overlay, (0, 0))
                screen.blit(menu_surface, menu_rect)
                for button in options_buttons:
                    button.draw(screen, now)
                if DEBUG_MENU_HITBOXES:
                    pygame.draw.rect(screen, (255, 255, 255), panel_rect, 1)
                    for button in options_buttons:
                        pygame.draw.rect(screen, (0, 255, 0), button.rect, 1)
            else:
                options_buttons = []
                options_layout_rect = None
                home_hovered = home_button_rect.collidepoint(pygame.mouse.get_pos())
                if home_hovered and not was_home_hovered:
                    menu.audio.switch()
                was_home_hovered = home_hovered
                home_image_button.update(now, home_hovered)
                home_image_button.draw(screen, now)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
