"""Texas Hold'em-style poker table integrated with the shared casino bankroll."""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
import random

import pygame

from game.player_state import PlayerState

CHIP_VALUES = (1, 5, 10, 25, 50, 100)
CHIP_COLORS = ("white", "red", "blue", "green", "black", "purple")
CHIP_SIZE = (44, 44)
BET_CHIP_SIZE = (40, 40)
RANKS = ("2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A")
SUITS = ("clubs", "diamonds", "hearts", "spades")
RANK_VALUES = {rank: index + 2 for index, rank in enumerate(RANKS)}
HAND_NAMES = (
    "High Card",
    "One Pair",
    "Two Pair",
    "Three of a Kind",
    "Straight",
    "Flush",
    "Full House",
    "Four of a Kind",
    "Straight Flush",
)


class PokerGame:
    """A compact Hold'em round with wager, fold, board reveals, and showdown."""

    def __init__(self, screen: pygame.Surface, player_state: PlayerState, seed: int | None = None):
        self.screen = screen
        self.player_state = player_state
        self.random = random.Random(seed)
        self.card_images: dict[tuple[str, str], pygame.Surface] = {}
        self.chip_images: dict[tuple[str, str], pygame.Surface] = {}
        self.chip_rects: list[tuple[pygame.Rect, int]] = []
        self.selected_chip_rects: list[tuple[pygame.Rect, int]] = []
        self.selected_chips: list[int] = []
        self.wager_street = "preflop"
        self.visible_board_count = 0
        self.title_font = pygame.font.Font(None, 42)
        self.font = pygame.font.Font(None, 27)
        self.small_font = pygame.font.Font(None, 22)
        self._load_assets()
        self._start_round()

    @property
    def asset_root(self) -> Path:
        return Path(__file__).resolve().parents[1] / "static" / "assets"

    def _load_assets(self) -> None:
        card_root = self.asset_root / "cards"
        for path in card_root.glob("*.png"):
            if path.stem in {"card_back_1", "joker"}:
                continue
            parts = path.stem.split("_of_")
            if len(parts) != 2:
                continue
            rank = {"ace": "A", "jack": "J", "queen": "Q", "king": "K"}.get(parts[0], parts[0])
            image = pygame.image.load(path).convert_alpha()
            self.card_images[(rank, parts[1])] = pygame.transform.smoothscale(image, (88, 124))

        chip_root = self.asset_root / "Card_Game_GFX" / "Chips"
        for color in CHIP_COLORS:
            for style in ("stacked", "flat"):
                path = chip_root / f"chips_{style}_{color}.png"
                image = pygame.image.load(path).convert_alpha()
                self.chip_images[(style, color)] = pygame.transform.smoothscale(image, CHIP_SIZE)

    def _start_round(self) -> None:
        self.deck = [(rank, suit) for suit in SUITS for rank in RANKS]
        self.random.shuffle(self.deck)
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.board: list[tuple[str, str]] = []
        self.phase = "wager" if self.player_state.chips > 0 else "results"
        self.current_bet = 0
        self.wager_street = "preflop"
        self.wager_text = ""
        self.selected_chips.clear()
        self.result_text = ""
        self.selected_chip_rects = []
        self.visible_board_count = 0

    def _restart_round(self) -> None:
        self._start_round()

    def _valid_wager(self) -> bool:
        try:
            amount = int(self.wager_text)
        except (TypeError, ValueError):
            return False
        return 1 <= amount <= max(0, self.player_state.chips - self.current_bet)

    def _add_chip(self, value: int) -> None:
        if sum(self.selected_chips) + value <= max(0, self.player_state.chips - self.current_bet):
            self.selected_chips.append(value)
            self.wager_text = str(sum(self.selected_chips))

    def _remove_chip(self, position: tuple[int, int]) -> bool:
        for rect, _ in self.selected_chip_rects:
            if rect.collidepoint(position):
                self.selected_chips.pop()
                self.wager_text = str(sum(self.selected_chips)) if self.selected_chips else ""
                return True
        return False

    def _prepare_next_wager(self, next_phase: str) -> None:
        self.selected_chips.clear()
        self.wager_text = ""
        if self.player_state.chips > self.current_bet:
            self.wager_street = next_phase
            self.phase = "wager"
        else:
            self.phase = next_phase

    def _deal_next_street(self) -> None:
        if self.phase == "preflop":
            self.board.extend([self.deck.pop(), self.deck.pop(), self.deck.pop()])
            self.visible_board_count = len(self.board)
            self._prepare_next_wager("flop")
        elif self.phase == "flop":
            self.board.append(self.deck.pop())
            self.visible_board_count = len(self.board)
            self._prepare_next_wager("turn")
        elif self.phase == "turn":
            self.board.append(self.deck.pop())
            self.visible_board_count = len(self.board)
            self._prepare_next_wager("river")
        elif self.phase == "river":
            self._settle("showdown")

    @staticmethod
    def _evaluate_five(cards: list[tuple[str, str]]) -> tuple[int, tuple[int, ...]]:
        values = sorted((RANK_VALUES[rank] for rank, _ in cards), reverse=True)
        suits = [suit for _, suit in cards]
        counts: dict[int, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        groups = sorted(((count, value) for value, count in counts.items()), reverse=True)
        unique = sorted(set(values), reverse=True)
        straight_high = unique[0] if len(unique) == 5 and unique[0] - unique[-1] == 4 else 0
        if unique == [14, 5, 4, 3, 2]:
            straight_high = 5
        flush = len(set(suits)) == 1
        if flush and straight_high:
            return 8, (straight_high,)
        if groups[0][0] == 4:
            return 7, (groups[0][1], groups[1][1])
        if groups[0][0] == 3 and groups[1][0] == 2:
            return 6, (groups[0][1], groups[1][1])
        if flush:
            return 5, tuple(values)
        if straight_high:
            return 4, (straight_high,)
        if groups[0][0] == 3:
            return 3, (groups[0][1],) + tuple(sorted((v for v, count in counts.items() if count == 1), reverse=True))
        pairs = sorted((value for value, count in counts.items() if count == 2), reverse=True)
        if len(pairs) == 2:
            kicker = max(value for value, count in counts.items() if count == 1)
            return 2, (pairs[0], pairs[1], kicker)
        if len(pairs) == 1:
            kickers = sorted((value for value, count in counts.items() if count == 1), reverse=True)
            return 1, (pairs[0],) + tuple(kickers)
        return 0, tuple(values)

    @classmethod
    def _best_hand(cls, cards: list[tuple[str, str]]) -> tuple[int, tuple[int, ...]]:
        return max(cls._evaluate_five(list(hand)) for hand in combinations(cards, 5))

    def _settle(self, reason: str) -> None:
        if reason == "fold":
            result = "loss"
        else:
            player_score = self._best_hand(self.player_hand + self.board)
            dealer_score = self._best_hand(self.dealer_hand + self.board)
            if player_score > dealer_score:
                result = "win"
            elif player_score < dealer_score:
                result = "loss"
            else:
                result = "push"
        if result == "win":
            self.player_state.chips += self.current_bet
        elif result == "loss":
            self.player_state.chips -= self.current_bet
        if reason == "fold":
            self.result_text = "FOLDED — YOU LOSE"
        elif result == "push":
            self.result_text = "PUSH — TIE"
        else:
            score = self._best_hand(self.player_hand + self.board)
            self.result_text = f"{result.upper()} — {HAND_NAMES[score[0]]}"
        self.phase = "result"

    def handle_event(self, event: pygame.event.Event) -> str | None:
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            return "room"
        replay_keys = (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE)

        if self.phase == "wager":
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self._remove_chip(event.pos):
                    return None
                for rect, value in self.chip_rects:
                    if rect.collidepoint(event.pos):
                        self._add_chip(value)
                        return None
            if event.type == pygame.KEYDOWN:
                if pygame.K_0 <= event.key <= pygame.K_9 and len(self.wager_text) < 6:
                    self.selected_chips.clear()
                    self.wager_text += str(event.key - pygame.K_0)
                elif event.key == pygame.K_BACKSPACE:
                    self.selected_chips.clear()
                    self.wager_text = self.wager_text[:-1]
                elif event.key in replay_keys and self._valid_wager():
                    self.current_bet += int(self.wager_text)
                    self.selected_chips.clear()
                    self.wager_text = ""
                    self.phase = self.wager_street
            return None

        if self.phase in {"preflop", "flop", "turn", "river"}:
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_f, pygame.K_LEFT):
                    self._settle("fold")
                elif event.key in replay_keys:
                    self._deal_next_street()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if pygame.Rect(330, 620, 190, 55).collidepoint(event.pos):
                    self._settle("fold")
                elif pygame.Rect(545, 620, 240, 55).collidepoint(event.pos):
                    self._deal_next_street()
            return None

        if self.phase == "result" and event.type == pygame.KEYDOWN and event.key in replay_keys:
            if self.player_state.chips > 0:
                self._restart_round()
            else:
                return "room"
        return None

    def _text(self, text: str, position: tuple[int, int], size: int = 27, color: str = "#f5e9be") -> None:
        self.screen.blit(pygame.font.Font(None, size).render(text, True, color), position)

    def _draw_card(self, card: tuple[str, str], position: tuple[int, int], hidden: bool = False) -> None:
        if hidden:
            rect = pygame.Rect(*position, 88, 124)
            pygame.draw.rect(self.screen, "#8b2020", rect, border_radius=8)
            pygame.draw.rect(self.screen, "#f7e9b9", rect, width=2, border_radius=8)
        else:
            self.screen.blit(self.card_images[card], position)

    def _draw_chips(self) -> None:
        self.chip_rects = []
        for index, (value, color) in enumerate(zip(CHIP_VALUES, CHIP_COLORS)):
            rect = pygame.Rect(300 + index * 120, 610, *CHIP_SIZE)
            self.chip_rects.append((rect, value))
            self.screen.blit(self.chip_images[("stacked", color)], rect)
            self._text(str(value), (rect.right + 8, rect.centery - 11), 23, "#f1d277")

    def _draw_selected_stack(self) -> None:
        self.selected_chip_rects = []
        if not self.selected_chips:
            return
        size = BET_CHIP_SIZE
        base = pygame.Rect(900, 500, *size)
        visible = min(len(self.selected_chips), 20)
        top = base.move(0, -(visible - 1) * 3)
        hitbox = pygame.Rect(base.x, top.y, base.width, base.height + (visible - 1) * 3)
        self.selected_chip_rects.append((hitbox, self.selected_chips[-1]))
        for index, value in enumerate(self.selected_chips[-visible:]):
            color = CHIP_COLORS[CHIP_VALUES.index(value)]
            chip = pygame.transform.smoothscale(self.chip_images[("stacked", color)], size)
            self.screen.blit(chip, base.move(0, -index * 3))
        if len(self.selected_chips) > 1:
            self._text(f"x{len(self.selected_chips)}", (base.x - 2, base.bottom + 8), 19, "#f1d277")

    def draw(self) -> None:
        self.screen.fill("#154734")
        self.screen.blit(self.title_font.render("POKER TABLE", True, "#f7e9b9"), (35, 25))
        self._text(f"Bankroll: {self.player_state.chips} chips", (35, 80))

        self._text("DEALER", (90, 125), 25)
        for index, card in enumerate(self.dealer_hand):
            self._draw_card(card, (90 + index * 100, 155), hidden=self.phase not in {"result"})

        self._text("BOARD", (485, 125), 25)
        board_x = 390
        for index, card in enumerate(self.board):
            self._draw_card(card, (board_x + index * 100, 155), hidden=index >= self.visible_board_count)

        self._text("YOUR HAND", (90, 350), 25)
        for index, card in enumerate(self.player_hand):
            self._draw_card(card, (90 + index * 100, 380))

        if self.phase == "wager":
            street = self.wager_street.title()
            self._text(f"{street} betting — add chips or type an amount, then press ENTER", (275, 520), 23)
            self._text(f"New wager: {self.wager_text or '_'} chips", (500, 565), 34, "#f1d277")
            self._draw_selected_stack()
            self._draw_chips()
        elif self.phase in {"preflop", "flop", "turn", "river"}:
            street = {"preflop": "Pre-flop", "flop": "Flop", "turn": "Turn", "river": "River"}[self.phase]
            self._text(f"{street} — Total bet: {self.current_bet} chips", (420, 535), 27, "#f1d277")
            pygame.draw.rect(self.screen, "#8b2020", (330, 620, 190, 55), border_radius=8)
            pygame.draw.rect(self.screen, "#286db2", (545, 620, 240, 55), border_radius=8)
            self._text("FOLD", (395, 637), 27)
            self._text("CHECK / CONTINUE", (565, 637), 23)
        elif self.phase == "result":
            self._text(self.result_text, (420, 535), 30, "#f1d277")
            self._text("Press ENTER to play again", (445, 585), 25)
            if len(self.board) < 5:
                self._text("Folded hands end immediately", (445, 610), 20, "#d8d0b8")
        self._text("ESC: return to room", (35, 680), 22, "#d8d0b8")
