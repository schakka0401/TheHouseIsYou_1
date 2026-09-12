"""Focused tests for local Blackjack dealer speech serialization."""
from __future__ import annotations

import unittest

import pygame

from game.dealer_voice import DealerVoiceManager, HIGH, LOW, MEDIUM, PRERECORDED_LINES


class FakeAudioManager:
    available = False

    def __init__(self, sfx_volume: float = 0.5) -> None:
        self.sfx_volume = sfx_volume


class FakeChannel:
    def __init__(self) -> None:
        self.busy = False
        self.plays: list[object] = []
        self.stop_count = 0
        self.volume = 0.0

    def get_busy(self) -> bool:
        return self.busy

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def play(self, sound: object) -> None:
        self.plays.append(sound)
        self.busy = True

    def stop(self) -> None:
        self.stop_count += 1
        self.busy = False

    def finish(self) -> None:
        self.busy = False


def make_manager() -> tuple[DealerVoiceManager, FakeAudioManager, FakeChannel]:
    audio = FakeAudioManager()
    channel = FakeChannel()
    sounds = {name: object() for name in PRERECORDED_LINES}
    manager = DealerVoiceManager(audio, channel=channel, preloaded_sounds=sounds)
    manager.clear_stale_dealer_lines("round:1")
    return manager, audio, channel


class DealerVoiceManagerTests(unittest.TestCase):
    def test_expected_sixteen_local_line_names_are_declared(self) -> None:
        self.assertEqual(len(PRERECORDED_LINES), 16)
        self.assertIn("dealer_push_1", PRERECORDED_LINES)
        self.assertNotIn("dealer_push", PRERECORDED_LINES)

    def test_busy_low_priority_chatter_is_dropped(self) -> None:
        manager, _, channel = make_manager()
        self.assertEqual(manager.play_dealer_line("dealer_round_1", LOW, context="round:1"), "played")
        self.assertEqual(manager.play_dealer_line("dealer_thought_1", LOW, context="round:1"), "dropped")
        self.assertEqual(len(channel.plays), 1)
        self.assertEqual(manager.queue, [])


class LocalDealerAssetTests(unittest.TestCase):
    def test_all_sixteen_real_mp3_files_preload_as_pygame_sounds(self) -> None:
        pygame.mixer.init()
        try:
            audio = FakeAudioManager()
            audio.available = True
            manager = DealerVoiceManager(audio)
            self.assertEqual(set(manager.sounds), set(PRERECORDED_LINES))
            manager.shutdown()
        finally:
            pygame.mixer.quit()

    def test_result_replaces_generic_line_without_overlap(self) -> None:
        manager, _, channel = make_manager()
        manager.play_dealer_line("dealer_round_1", LOW, context="round:1")
        outcome = manager.play_dealer_line("dealer_win_1", MEDIUM, context="round:1")
        self.assertEqual(outcome, "played")
        self.assertEqual(channel.stop_count, 1)
        self.assertEqual(channel.plays, [manager.sounds["dealer_round_1"], manager.sounds["dealer_win_1"]])
        self.assertEqual(manager.current.name, "dealer_win_1")

    def test_major_result_lines_play_sequentially(self) -> None:
        manager, _, channel = make_manager()
        manager.clear_stale_dealer_lines("results")
        self.assertEqual(manager.play_dealer_line("dealer_analysis", HIGH, context="results"), "played")
        self.assertEqual(manager.play_dealer_line("dealer_simulation", HIGH, context="results"), "queued")
        self.assertEqual(manager.play_dealer_line("dealer_rematch", HIGH, context="results"), "queued")
        self.assertEqual(len(channel.plays), 1)

        channel.finish()
        manager.update_dealer_voice()
        self.assertEqual(manager.current.name, "dealer_simulation")
        self.assertEqual(len(channel.plays), 2)

        channel.finish()
        manager.update_dealer_voice()
        self.assertEqual(manager.current.name, "dealer_rematch")
        self.assertEqual(len(channel.plays), 3)

    def test_stale_queued_gameplay_line_is_skipped(self) -> None:
        manager, _, channel = make_manager()
        manager.play_dealer_line("dealer_win_1", MEDIUM, context="round:1")
        manager.play_dealer_line("dealer_loss_1", MEDIUM, context="round:1")
        manager.clear_stale_dealer_lines("round:2")
        channel.finish()
        manager.update_dealer_voice()
        self.assertIsNone(manager.current)
        self.assertEqual(len(channel.plays), 1)

    def test_latest_sfx_volume_controls_active_voice(self) -> None:
        manager, audio, channel = make_manager()
        manager.play_dealer_line("dealer_intro", HIGH, context="round:1")
        self.assertAlmostEqual(channel.volume, 0.45)
        audio.sfx_volume = 0.2
        manager.update_dealer_voice()
        self.assertAlmostEqual(channel.volume, 0.18)

    def test_shutdown_stops_only_the_dedicated_channel(self) -> None:
        manager, _, channel = make_manager()
        manager.play_dealer_line("dealer_intro", HIGH, context="round:1")
        manager.play_dealer_line("dealer_analysis", HIGH, context="round:1")
        manager.shutdown()
        self.assertEqual(channel.stop_count, 1)
        self.assertFalse(channel.busy)
        self.assertIsNone(manager.current)
        self.assertEqual(manager.queue, [])


if __name__ == "__main__":
    unittest.main()
