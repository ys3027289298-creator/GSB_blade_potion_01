import builtins
import io
import random
import unittest
from contextlib import redirect_stdout
from unittest import mock

import game


class GameTestCase(unittest.TestCase):
    def setUp(self):
        # Remove typing-effect delays and silence printed output for all tests.
        self._sleep_patch = mock.patch.object(game.time, "sleep", lambda *a, **k: None)
        self._sleep_patch.start()

    def tearDown(self):
        self._sleep_patch.stop()

    def _inputs(self, values, raises_eof=False):
        seq = list(values)

        def fake_input(prompt=""):
            if seq:
                return seq.pop(0)
            if raises_eof:
                raise EOFError
            return "1"

        return fake_input

    def _run_quietly(self, fn, *args, **kwargs):
        with redirect_stdout(io.StringIO()):
            return fn(*args, **kwargs)

    # --- consecutive attacks: a dead enemy must never act -----------------
    def test_consecutive_attacks_enemy_never_counters_after_death(self):
        random.seed(0)
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 5, "attack": 10})

        hits = []
        original = player.take_damage

        def record(damage):
            hits.append(enemy.is_alive())
            return original(damage)

        with mock.patch.object(builtins, "input", self._inputs(["1", "1", "1"])), \
                mock.patch.object(player, "take_damage", side_effect=record):
            result = self._run_quietly(game.battle, player, enemy)

        self.assertTrue(result)
        self.assertFalse(enemy.is_alive())
        self.assertEqual(enemy.hp, 0)
        # Every counter-attack happened while the enemy was still alive.
        self.assertTrue(all(hits), f"enemy countered while dead: {hits}")

    def test_three_consecutive_attack_choices_resolve(self):
        random.seed(1)
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 40, "attack": 10})
        start_hp = player.hp
        with mock.patch.object(builtins, "input", self._inputs(["1", "1", "1"])):
            for _ in range(3):
                self._run_quietly(game.player_turn, player, enemy, None)
        self.assertTrue(player.is_alive())
        # Three direct turns mean three player hits and no counter phase
        # (counter-attacks live in battle()), so only enemy HP changed.
        self.assertLessEqual(enemy.hp, 40 - 3 * 5)
        self.assertEqual(player.hp, start_hp)

    # --- rollback: full-HP heal and invalid inputs must not mutate state ---
    def test_heal_at_full_hp_rolls_back(self):
        player = game.Player("Hero")
        before = (player.hp, list(player.inventory))
        self._run_quietly(player.heal)
        self.assertEqual((player.hp, list(player.inventory)), before)

    def test_heal_damaged_consumes_one_and_caps(self):
        player = game.Player("Hero")
        player.hp = 95
        self._run_quietly(player.heal)
        self.assertEqual(player.hp, 100)
        self.assertEqual(player.inventory.count("Potion"), 2)

        player.hp = 50
        self._run_quietly(player.heal)
        self.assertEqual(player.hp, 70)
        self.assertEqual(player.inventory.count("Potion"), 1)

    def test_heal_without_potions_does_nothing(self):
        player = game.Player("Hero")
        player.inventory = []
        player.hp = 30
        self._run_quietly(player.heal)
        self.assertEqual(player.hp, 30)

    def test_invalid_menu_input_does_not_change_state(self):
        random.seed(2)
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
        # Boundary inputs: garbage, empty, out-of-range, spaces around valid.
        values = ["abc", "", "0", "4", " 1 "]
        with mock.patch.object(builtins, "input", self._inputs(values)):
            self._run_quietly(game.player_turn, player, enemy, None)
        self.assertEqual(player.hp, 100)
        self.assertEqual(player.inventory.count("Potion"), 3)
        self.assertLess(enemy.hp, 30)

    def test_eof_on_action_prompt_does_not_crash(self):
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
        with mock.patch.object(builtins, "input", self._inputs([], raises_eof=True)):
            self._run_quietly(game.player_turn, player, enemy, None)
        self.assertTrue(player.is_alive())
        self.assertLess(enemy.hp, 30)

    def test_eof_on_restart_prompt_quits(self):
        choice = game.read_choice(["y", "n"], "err")
        self.assertIsNone(choice)

    # --- ally lifecycle ----------------------------------------------------
    def test_dead_ally_does_not_assist(self):
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
        ally = game.Ally("Shivansh")
        ally.hp = 0
        with mock.patch.object(builtins, "input", self._inputs(["3"])):
            self._run_quietly(game.player_turn, player, enemy, ally)
        self.assertEqual(enemy.hp, 30)  # no assist damage

    def test_ally_resets_for_each_battle(self):
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 5, "attack": 10})
        ally = game.Ally("Shivansh")
        ally.hp = 10  # leftover damage from a previous battle
        with mock.patch.object(builtins, "input", self._inputs(["1"])):
            self._run_quietly(game.battle, player, enemy, ally)
        self.assertEqual(ally.hp, ally.max_hp)
        self.assertEqual(ally.max_hp, 50)

    def test_ally_does_not_stack_across_battles(self):
        player = game.Player("Hero")
        ally = game.Ally("Shivansh")
        with mock.patch.object(builtins, "input", self._inputs(["1"])):
            self._run_quietly(
                game.battle, player, game.Enemy("Goblin", {"hp": 5, "attack": 5}), ally
            )
            # A second battle must start with the ally fully restored.
            self._run_quietly(
                game.battle, player, game.Enemy("Orc", {"hp": 5, "attack": 5}), ally
            )
        self.assertEqual(ally.hp, ally.max_hp)

    # --- achievements ------------------------------------------------------
    def test_achievement_is_idempotent(self):
        player = game.Player("Hero")
        self.assertTrue(player.add_achievement("Defeated Goblin"))
        self.assertFalse(player.add_achievement("Defeated Goblin"))
        self.assertEqual(player.achievements, {"Defeated Goblin"})

    def test_defeat_grants_single_achievement(self):
        random.seed(3)
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 5, "attack": 5})
        with mock.patch.object(builtins, "input", self._inputs(["1"])):
            self._run_quietly(game.battle, player, enemy)
        self.assertEqual(
            list(player.achievements).count("Defeated Goblin"), 1
        )

    # --- full-game restart lifecycle: two restarts, zero leakage -----------
    def _capture_first_battle_states(self):
        """Snapshot the lifecycle state seen on the first battle of a run."""
        seen = {}
        original_battle = game.battle

        def capture(player, enemy, ally=None, is_final=False):
            if not seen:  # snapshot before any damage happens
                seen["player_obj"] = player
                seen["ally_obj"] = ally
                seen["hp"] = player.hp
                seen["max_hp"] = player.max_hp
                seen["inventory"] = list(player.inventory)
                seen["achievements"] = set(player.achievements)
                seen["ally_hp"] = ally.hp if ally else None
                seen["ally_max_hp"] = ally.max_hp if ally else None
            return original_battle(player, enemy, ally, is_final=is_final)

        return seen, capture

    def test_two_restarts_use_fresh_state(self):
        random.seed(4)
        snapshots = []
        with mock.patch.object(builtins, "input", self._inputs([])):
            for _ in range(2):  # restart twice (two full new games)
                seen, capture = self._capture_first_battle_states()
                with mock.patch.object(game, "battle", capture):
                    self._run_quietly(game.play_game, "Hero")
                snapshots.append(seen)

        first, second = snapshots
        self.assertIsNot(first["player_obj"], second["player_obj"])
        self.assertIsNot(first["ally_obj"], second["ally_obj"])
        for seen in snapshots:
            # Every new game begins with exactly the initial lifecycle state.
            self.assertEqual(seen["hp"], 100)
            self.assertEqual(seen["max_hp"], 100)
            self.assertEqual(seen["inventory"], ["Potion"] * 3)
            self.assertEqual(seen["achievements"], set())
            self.assertEqual(seen["ally_hp"], seen["ally_max_hp"])

    def test_death_does_not_leak_into_next_game(self):
        random.seed(5)
        # Run 1: never attack, so the Hero eventually dies in battle 1.
        with mock.patch.object(builtins, "input", self._inputs([])):
            dead_input = lambda *a: "2"
            with mock.patch.object(builtins, "input", dead_input):
                self._run_quietly(game.play_game, "Hero")

        # Run 2: capture the freshly constructed state.
        seen, capture = self._capture_first_battle_states()
        with mock.patch.object(builtins, "input", self._inputs([])), \
                mock.patch.object(game, "battle", capture):
            self._run_quietly(game.play_game, "Hero")
        self.assertEqual(seen["hp"], 100)
        self.assertEqual(seen["max_hp"], 100)
        self.assertEqual(seen["inventory"], ["Potion"] * 3)
        self.assertEqual(seen["achievements"], set())
        self.assertEqual(seen["ally_hp"], seen["ally_max_hp"])

    def test_dead_enemy_object_is_not_reused(self):
        random.seed(6)
        created = []
        original_init = game.Enemy.__init__

        def track_init(self, name, stats):
            created.append(self)
            return original_init(self, name, stats)

        with mock.patch.object(builtins, "input", self._inputs([])), \
                mock.patch.object(game.Enemy, "__init__", track_init):
            self._run_quietly(game.play_game, "Hero")
        self.assertEqual(len(created), 3)
        self.assertEqual(len({id(e) for e in created}), 3)

    def test_main_eof_throughout_does_not_crash(self):
        random.seed(7)
        argv = ["game.py", "Hero"]
        with mock.patch.object(builtins, "input", self._inputs([], raises_eof=True)), \
                mock.patch.object(game.sys, "argv", argv):
            self._run_quietly(game.main)


if __name__ == "__main__":
    unittest.main()
