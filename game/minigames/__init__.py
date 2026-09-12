import pygame
import random
import sys

# --------------------------------------------------
# Constants & Colors
# --------------------------------------------------
SCREEN_WIDTH = 900
SCREEN_HEIGHT = 650

TABLE_GREEN = (24, 114, 59)
BORDER_GREEN = (15, 80, 40)
WHITE = (255, 255, 255)
BLACK = (20, 20, 20)
CARD_BG = (250, 250, 250)
CARD_BACK = (160, 30, 30)
RED = (200, 30, 30)
GOLD = (235, 185, 50)
GRAY = (180, 180, 180)
DARK_GRAY = (80, 80, 80)
BLUE = (45, 110, 190)

# Card Suits and Ranks
SUITS = ["♠", "♥", "♦", "♣"]
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]


# --------------------------------------------------
# Card & Game Logic
# --------------------------------------------------
class Card:
    def __init__(self, suit, rank):
        self.suit = suit
        self.rank = rank

    def get_value(self):
        if self.rank in ["J", "Q", "K"]:
            return 10
        elif self.rank == "A":
            return 11
        return int(self.rank)


def create_deck():
    deck = [Card(suit, rank) for suit in SUITS for rank in RANKS]
    random.shuffle(deck)
    return deck


def calculate_hand_value(hand):
    total = sum(card.get_value() for card in hand)
    aces = sum(1 for card in hand if card.rank == "A")
    # Convert Ace value from 11 to 1 if over 21
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1
    return total


# --------------------------------------------------
# UI Elements
# --------------------------------------------------
class Button:
    def __init__(self, rect, text, bg_color, hover_color, text_color=WHITE):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.bg_color = bg_color
        self.hover_color = hover_color
        self.text_color = text_color
        self.is_hovered = False

    def draw(self, surface, font):
        color = self.hover_color if self.is_hovered else self.bg_color
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        pygame.draw.rect(surface, WHITE, self.rect, width=2, border_radius=8)

        text_surf = font.render(self.text, True, self.text_color)
        text_rect = text_surf.get_rect(center=self.rect.center)
        surface.blit(text_surf, text_rect)

    def check_hover(self, pos):
        self.is_hovered = self.rect.collidepoint(pos)

    def is_clicked(self, pos, event):
        return event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.rect.collidepoint(pos)


# --------------------------------------------------
# Main Game Function
# --------------------------------------------------
def main():
    pygame.init()
    pygame.font.init()
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Pygame Blackjack")
    clock = pygame.time.Clock()

    # Fonts
    font_large = pygame.font.SysFont("Arial", 36, bold=True)
    font_medium = pygame.font.SysFont("Arial", 24, bold=True)
    font_small = pygame.font.SysFont("Arial", 18, bold=True)
    font_card = pygame.font.SysFont("Arial", 22, bold=True)

    # Buttons
    btn_hit = Button((280, 560, 150, 50), "Hit", BLUE, (70, 140, 230))
    btn_stand = Button((470, 560, 150, 50), "Stand", RED, (230, 70, 70))
    btn_new_game = Button((375, 560, 150, 50), "Deal Again", GOLD, (255, 210, 80), BLACK)

    def start_round():
        deck = create_deck()
        player_hand = [deck.pop(), deck.pop()]
        dealer_hand = [deck.pop(), deck.pop()]
        game_over = False
        message = ""
        # Check initial Blackjack
        if calculate_hand_value(player_hand) == 21:
            game_over = True
            if calculate_hand_value(dealer_hand) == 21:
                message = "Push! Both have Blackjack."
            else:
                message = "Blackjack! You win!"
        return deck, player_hand, dealer_hand, game_over, message

    deck, player_hand, dealer_hand, game_over, message = start_round()

    # Helper: Draw Card
    def draw_card(x, y, card, hidden=False):
        card_w, card_h = 80, 115
        rect = pygame.Rect(x, y, card_w, card_h)

        if hidden:
            # Draw face-down card
            pygame.draw.rect(screen, CARD_BACK, rect, border_radius=6)
            pygame.draw.rect(screen, WHITE, rect, width=2, border_radius=6)
            pattern_rect = rect.inflate(-12, -12)
            pygame.draw.rect(screen, (120, 20, 20), pattern_rect, border_radius=4)
            return

        # Draw face-up card
        pygame.draw.rect(screen, CARD_BG, rect, border_radius=6)
        pygame.draw.rect(screen, BLACK, rect, width=2, border_radius=6)

        color = RED if card.suit in ["♥", "♦"] else BLACK
        card_text = f"{card.rank}{card.suit}"

        # Corner label
        surf = font_card.render(card_text, True, color)
        screen.blit(surf, (x + 6, y + 4))

        # Center suit
        suit_surf = font_large.render(card.suit, True, color)
        suit_rect = suit_surf.get_rect(center=(x + card_w // 2, y + card_h // 2 + 6))
        screen.blit(suit_surf, suit_rect)

    # --------------------------------------------------
    # Game Loop
    # --------------------------------------------------
    running = True
    while running:
        mouse_pos = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if not game_over:
                # HIT Action
                if btn_hit.is_clicked(mouse_pos, event):
                    player_hand.append(deck.pop())
                    player_val = calculate_hand_value(player_hand)
                    if player_val > 21:
                        game_over = True
                        message = "Bust! Dealer wins."

                # STAND Action
                elif btn_stand.is_clicked(mouse_pos, event):
                    # Dealer draws until 17 or more
                    while calculate_hand_value(dealer_hand) < 17:
                        dealer_hand.append(deck.pop())

                    player_val = calculate_hand_value(player_hand)
                    dealer_val = calculate_hand_value(dealer_hand)

                    game_over = True
                    if dealer_val > 21:
                        test = 0
                        # The player is not overconfident
                    elif player_val > dealer_val:
                        test = 0
                        #  The player is not overconfident
                    elif player_val < dealer_val:
                        test = 1
                        # The player is overconfident
                    else:
                        test = 1
                        #  The player is not overconfident

            else:
                # NEW ROUND Action
                if btn_new_game.is_clicked(mouse_pos, event):
                    deck, player_hand, dealer_hand, game_over, message = start_round()

        # Update hover states
        btn_hit.check_hover(mouse_pos)
        btn_stand.check_hover(mouse_pos)
        btn_new_game.check_hover(mouse_pos)

        # --------------------------------------------------
        # Render
        # --------------------------------------------------
        screen.fill(TABLE_GREEN)
        pygame.draw.rect(screen, BORDER_GREEN, (15, 15, SCREEN_WIDTH - 30, SCREEN_HEIGHT - 30), width=5,
                         border_radius=15)

        # Draw Dealer Hand
        dealer_val = calculate_hand_value(dealer_hand)
        dealer_display_val = f"Dealer: {dealer_val}" if game_over else "Dealer: ?"
        val_surf = font_medium.render(dealer_display_val, True, WHITE)
        screen.blit(val_surf, (50, 50))

        start_x = 50
        for i, card in enumerate(dealer_hand):
            # First card is hidden while round is ongoing
            is_hidden = (i == 0 and not game_over)
            draw_card(start_x + i * 95, 90, card, hidden=is_hidden)

        # Draw Player Hand
        player_val = calculate_hand_value(player_hand)
        player_surf = font_medium.render(f"Player: {player_val}", True, WHITE)
        screen.blit(player_surf, (50, 270))

        for i, card in enumerate(player_hand):
            draw_card(start_x + i * 95, 310, card)

        # Draw Outcome Banner
        if game_over and message:
            msg_surf = font_large.render(message, True, GOLD)
            msg_rect = msg_surf.get_rect(center=(SCREEN_WIDTH // 2, 480))
            # Background plate behind banner
            plate_rect = msg_rect.inflate(40, 20)
            pygame.draw.rect(screen, (0, 0, 0, 180), plate_rect, border_radius=8)
            screen.blit(msg_surf, msg_rect)

        # Draw Buttons
        if not game_over:
            btn_hit.draw(screen, font_medium)
            btn_stand.draw(screen, font_medium)
            msg_surf = font_large.render("Will you hit or stand?", True, GOLD)
            msg_rect = msg_surf.get_rect(center=(SCREEN_WIDTH // 2, 480))
            # Background plate behind banner
            plate_rect = msg_rect.inflate(40, 20)
            pygame.draw.rect(screen, (0, 0, 0, 180), plate_rect, border_radius=8)
            screen.blit(msg_surf, msg_rect)
        else:
            btn_new_game.draw(screen, font_medium)

        pygame.display.flip()
        clock.tick(60)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
