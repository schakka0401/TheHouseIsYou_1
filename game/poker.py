import pygame
import random
import sys
from collections import Counter

# --- Constants & Setup ---
SCREEN_WIDTH = 900
SCREEN_HEIGHT = 650
FPS = 60

# Colors
GREEN_FELT = (28, 107, 45)
CARD_WHITE = (250, 250, 250)
CARD_BORDER = (40, 40, 40)
CARD_BACK = (160, 30, 30)
RED = (200, 30, 30)
BLACK = (20, 20, 20)
TEXT_COLOR = (240, 240, 240)
ACCENT_COLOR = (240, 200, 70)
BTN_BG = (50, 60, 75)
BTN_HOVER = (70, 85, 105)

SUITS = ['♠', '♥', '♦', '♣']
RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
RANK_VALUES = {r: i + 2 for i, r in enumerate(RANKS)}


# --- Game Engine Classes ---

class Card:
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit
        self.value = RANK_VALUES[rank]
        self.color = RED if suit in ['♥', '♦'] else BLACK
        self.selected = False

    def __repr__(self):
        return f"{self.rank}{self.suit}"


class Deck:
    def __init__(self):
        self.cards = [Card(r, s) for s in SUITS for r in RANKS]
        random.shuffle(self.cards)

    def draw(self, count=1):
        return [self.cards.pop() for _ in range(count)]


# --- Hand Evaluator ---

HAND_NAMES = {
    8: "Straight Flush",
    7: "Four of a Kind",
    6: "Full House",
    5: "Flush",
    4: "Straight",
    3: "Three of a Kind",
    2: "Two Pair",
    1: "One Pair",
    0: "High Card"
}


def evaluate_5card(hand):
    values = sorted([c.value for c in hand], reverse=True)
    suits = [c.suit for c in hand]
    val_counts = Counter(values)
    counts_sorted = sorted(val_counts.items(), key=lambda item: (item[1], item[0]), reverse=True)

    is_flush = len(set(suits)) == 1

    # Check for straight (handle A-2-3-4-5 wheel)
    unique_vals = sorted(list(set(values)), reverse=True)
    is_straight = False
    straight_high = 0
    if len(unique_vals) == 5:
        if unique_vals[0] - unique_vals[4] == 4:
            is_straight = True
            straight_high = unique_vals[0]
        elif unique_vals == [14, 5, 4, 3, 2]:
            is_straight = True
            straight_high = 5

    # Evaluation ranks: (hand_category, tiebreak_tuple)
    if is_flush and is_straight:
        return (8, (straight_high,))
    if counts_sorted[0][1] == 4:
        return (7, (counts_sorted[0][0], counts_sorted[1][0]))
    if counts_sorted[0][1] == 3 and counts_sorted[1][1] == 2:
        return (6, (counts_sorted[0][0], counts_sorted[1][0]))
    if is_flush:
        return (5, tuple(values))
    if is_straight:
        return (4, (straight_high,))
    if counts_sorted[0][1] == 3:
        kickers = tuple(v for v, _ in counts_sorted[1:])
        return (3, (counts_sorted[0][0],) + kickers)
    if counts_sorted[0][1] == 2 and counts_sorted[1][1] == 2:
        high_pair = max(counts_sorted[0][0], counts_sorted[1][0])
        low_pair = min(counts_sorted[0][0], counts_sorted[1][0])
        kicker = counts_sorted[2][0]
        return (2, (high_pair, low_pair, kicker))
    if counts_sorted[0][1] == 2:
        pair_val = counts_sorted[0][0]
        kickers = tuple(v for v, _ in counts_sorted[1:])
        return (1, (pair_val,) + kickers)
    return (0, tuple(values))


# --- UI Helper Components ---

class Button:
    def __init__(self, rect, text):
        self.rect = pygame.Rect(rect)
        self.text = text

    def draw(self, surface, font):
        mouse_pos = pygame.mouse.get_pos()
        color = BTN_HOVER if self.rect.collidepoint(mouse_pos) else BTN_BG
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        pygame.draw.rect(surface, ACCENT_COLOR, self.rect, width=2, border_radius=8)

        lbl = font.render(self.text, True, TEXT_COLOR)
        lbl_rect = lbl.get_rect(center=self.rect.center)
        surface.blit(lbl, lbl_rect)

    def is_clicked(self, pos):
        return self.rect.collidepoint(pos)


def draw_card(surface, card, rect, font, small_font, face_up=True):
    # Card base
    pygame.draw.rect(surface, CARD_WHITE if face_up else CARD_BACK, rect, border_radius=6)
    pygame.draw.rect(surface, CARD_BORDER, rect, width=2, border_radius=6)

    if not face_up:
        # Pattern for card back
        inner = rect.inflate(-10, -10)
        pygame.draw.rect(surface, (120, 20, 20), inner, border_radius=4)
        return

    # Text rendering
    val_surf = font.render(card.rank, True, card.color)
    suit_surf = font.render(card.suit, True, card.color)
    center_suit = font.render(card.suit, True, card.color)

    # Top-left corner
    surface.blit(val_surf, (rect.x + 8, rect.y + 6))
    surface.blit(suit_surf, (rect.x + 8, rect.y + 28))

    # Center suit
    c_rect = center_suit.get_rect(center=rect.center)
    surface.blit(center_suit, c_rect)


# --- Main Game Loop ---

def main():
    pygame.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("5-Card Draw Poker")
    clock = pygame.time.Clock()

    font = pygame.font.SysFont("Segoe UI", 24, bold=True)
    large_font = pygame.font.SysFont("Segoe UI", 32, bold=True)
    small_font = pygame.font.SysFont("Segoe UI", 18)

    card_width, card_height = 80, 115
    action_btn = Button((SCREEN_WIDTH // 2 - 80, 560, 160, 45), "Next Scenario")

    # Game States: "DISCARD", "SHOWDOWN"
    state = "DISCARD"
    deck = Deck()
    player_hand = deck.draw(5)
    dealer_hand = deck.draw(5)
    result_text = ""

    def reset_round():
        nonlocal deck, player_hand, dealer_hand, state, result_text
        deck = Deck()
        player_hand = deck.draw(5)
        dealer_hand = deck.draw(5)
        state = "DISCARD"
        action_btn.text = "Next Scenario"
        result_text = ""

    running = True
    while running:
        # 1. Event Handling
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mouse_pos = event.pos

                if state == "DISCARD":
                    # Check card selections
                    start_x = (SCREEN_WIDTH - (5 * 100 - 20)) // 2
                    for i, card in enumerate(player_hand):
                        c_rect = pygame.Rect(start_x + i * 100, 390 - (15 if card.selected else 0), card_width,
                                             card_height)
                        if c_rect.collidepoint(mouse_pos):
                            card.selected = not card.selected

                    # Clicked Action Button
                    if action_btn.is_clicked(mouse_pos):
                        # Replace selected cards
                        for i in range(len(player_hand)):
                            if player_hand[i].selected:
                                player_hand[i] = deck.draw(1)[0]

                        # AI simple draw logic (discards cards not part of pairs/trips)
                        d_vals = Counter([c.value for c in dealer_hand])
                        for i in range(len(dealer_hand)):
                            if d_vals[dealer_hand[i].value] == 1 and dealer_hand[i].value < 11:
                                dealer_hand[i] = deck.draw(1)[0]

                        # Determine Winner
                        p_score = evaluate_5card(player_hand)
                        d_score = evaluate_5card(dealer_hand)

                        # if p_score > d_score:
                        #     result_text = f"You Win! ({HAND_NAMES[p_score[0]]} vs {HAND_NAMES[d_score[0]]})"
                        # elif d_score > p_score:
                        #     result_text = f"Dealer Wins! ({HAND_NAMES[d_score[0]]} vs {HAND_NAMES[p_score[0]]})"
                        # else:
                        #     result_text = "It's a Tie!"

                        state = "SHOWDOWN"
                        action_btn.text = "Play Again"
                        reset_round()

                elif state == "SHOWDOWN":
                    if action_btn.is_clicked(mouse_pos):
                        reset_round()

        # 2. Render Screen
        screen.fill(GREEN_FELT)

        # Draw Table accents
        pygame.draw.ellipse(screen, (35, 125, 55), (60, 40, SCREEN_WIDTH - 120, SCREEN_HEIGHT - 80), width=4)

        # Dealer Section
        d_label = font.render("Dealer's Hand", True, TEXT_COLOR)
        screen.blit(d_label, (40, 40))
        start_x = (SCREEN_WIDTH - (5 * 100 - 20)) // 2
        for i, card in enumerate(dealer_hand):
            c_rect = pygame.Rect(start_x + i * 100, 80, card_width, card_height)
            draw_card(screen, card, c_rect, font, small_font, face_up=(state == "SHOWDOWN"))

        # Player Section
        p_label = font.render("Your Hand", True, TEXT_COLOR)
        screen.blit(p_label, (40, 340))
        for i, card in enumerate(player_hand):
            # Elevate selected cards
            y_pos = 390 - (18 if card.selected and state == "DISCARD" else 0)
            c_rect = pygame.Rect(start_x + i * 100, y_pos, card_width, card_height)
            draw_card(screen, card, c_rect, font, small_font, face_up=True)

        # Prompts & Results
        if state == "DISCARD":
            inst = small_font.render("Click the cards you would discard", True, ACCENT_COLOR)
            screen.blit(inst, inst.get_rect(center=(SCREEN_WIDTH // 2, 530)))
        else:
            res = large_font.render(result_text, True, ACCENT_COLOR)
            screen.blit(res, res.get_rect(center=(SCREEN_WIDTH // 2, 280)))

        # Action Button
        action_btn.draw(screen, font)

        pygame.display.flip()
        clock.tick(FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()