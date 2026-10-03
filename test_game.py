"""State-lifecycle tests for game.py.

Covers: consecutive moves, rollback of rejected operations, restarting twice,
boundary/invalid input, and proof that no state leaks after death or restart.
Run with: python3 -m unittest test_game -v
"""
import io
import random
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import game

game.DELAY_SCALE = 0  # skip typing animation and pauses during tests


def silent(func, *args, **kwargs):
    """Run func with stdout captured; returns (result, output)."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        result = func(*args, **kwargs)
    return result, buf.getvalue()


def scripted(inputs):
    """Return an input() replacement feeding the given script."""
    it = iter(inputs)
    return lambda _prompt="": next(it)


class ConsecutiveMovesTest(unittest.TestCase):
    """连续出招: multi-round sequences keep the round state machine consistent."""

    def test_consecutive_attacks_until_enemy_dies(self):
        random.seed(7)
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
        with patch("builtins.input", scripted(["1"] * 50)):
            won, out = silent(game.battle, player, enemy)
        self.assertTrue(won)
        self.assertEqual(enemy.hp, 0)
        self.assertFalse(enemy.is_alive())
        # The enemy never counterattacks on the round it dies:
        # counterattacks == player hits - 1, and no strike after the killing blow.
        hits = out.count("Goblin takes")
        counters = out.count("Goblin strikes back")
        self.assertGreater(hits, 1)  # really a multi-round (consecutive) fight
        self.assertEqual(counters, hits - 1)
        self.assertLess(out.rfind("Goblin strikes back"), out.rfind("Goblin takes"))
        self.assertIn("Defeated Goblin", player.achievements)

    def test_consecutive_mixed_moves(self):
        random.seed(11)
        player = game.Player("Hero")
        silent(player.take_damage, 40)  # hp 60 -> healing is meaningful
        enemy = game.Enemy("Orc", {"hp": 50, "attack": 12})
        ally = game.Ally("Shivansh")
        with patch("builtins.input", scripted(["2", "3", "1"])):
            silent(game.player_turn, player, enemy, ally)  # heal
            self.assertEqual(player.hp, 80)
            self.assertEqual(player.inventory.count("Potion"), 2)
            silent(game.player_turn, player, enemy, ally)  # call ally
            self.assertLess(enemy.hp, 50)
            # assisting must not mutate the ally (no state stacking)
            self.assertEqual((ally.hp, ally.max_hp, ally.attack), (50, 50, 8))
            hp_before = enemy.hp
            silent(game.player_turn, player, enemy, ally)  # attack
            self.assertLess(enemy.hp, hp_before)


class RollbackTest(unittest.TestCase):
    """回退操作: a rejected action must leave every piece of state untouched."""

    def test_invalid_menu_input_changes_nothing(self):
        random.seed(3)
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
        bad = ["", "abc", "0", "4", "-1", "   "]
        with patch("builtins.input", scripted(bad + ["1"])):
            _, out = silent(game.player_turn, player, enemy, None)
        self.assertEqual(out.count("Invalid choice! Please enter 1, 2, or 3."), len(bad))
        self.assertEqual(player.hp, 100)                       # player untouched
        self.assertEqual(player.inventory.count("Potion"), 3)  # potions untouched
        self.assertIn(30 - enemy.hp, range(5, 16))             # only final "1" landed

    def test_full_hp_heal_rolls_back(self):
        player = game.Player("Hero")
        used, _ = silent(player.heal)
        self.assertFalse(used)
        self.assertEqual(player.hp, 100)
        self.assertEqual(player.inventory.count("Potion"), 3)

    def test_heal_without_potion_rolls_back(self):
        player = game.Player("Hero")
        silent(player.take_damage, 30)
        player.inventory = []
        used, _ = silent(player.heal)
        self.assertFalse(used)
        self.assertEqual(player.hp, 70)
        self.assertEqual(player.inventory, [])

    def test_successful_heal_consumes_exactly_one(self):
        player = game.Player("Hero")
        silent(player.take_damage, 50)  # hp 50
        used, _ = silent(player.heal)
        self.assertTrue(used)
        self.assertEqual(player.hp, 70)
        self.assertEqual(player.inventory.count("Potion"), 2)

    def test_hurt_heal_clamps_at_max_and_consumes(self):
        player = game.Player("Hero")
        silent(player.take_damage, 10)  # hp 90: hurt, so the potion is allowed
        used, _ = silent(player.heal)
        self.assertTrue(used)
        self.assertEqual(player.hp, 100)  # clamped, not 110
        self.assertEqual(player.inventory.count("Potion"), 2)


class BoundaryInputTest(unittest.TestCase):
    """边界输入: whitespace, case, EOF and interrupts never crash the game."""

    def test_whitespace_padded_valid_choice(self):
        for raw in ["1", " 1 ", "\t1\t"]:
            random.seed(1)
            player = game.Player("Hero")
            enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
            with patch("builtins.input", scripted([raw])):
                silent(game.player_turn, player, enemy, None)
            self.assertLess(enemy.hp, 30)

    def test_eof_during_battle_exits_gracefully(self):
        with patch.object(sys, "argv", ["game.py", "Hero"]), \
                patch("builtins.input", side_effect=EOFError):
            _, out = silent(game.main)  # must not raise
        self.assertIn("Goodbye", out)

    def test_eof_at_replay_prompt_exits_gracefully(self):
        random.seed(0)
        inputs = ["1"] * 300  # enough to finish (or lose) one full game

        def fake_input(_prompt=""):
            if inputs:
                return inputs.pop(0)
            raise EOFError

        with patch.object(sys, "argv", ["game.py"]), \
                patch("builtins.input", fake_input):
            _, out = silent(game.main)  # must not raise
        self.assertIn("Goodbye", out)

    def test_keyboard_interrupt_exits_gracefully(self):
        with patch.object(sys, "argv", ["game.py", "Hero"]), \
                patch("builtins.input", side_effect=KeyboardInterrupt):
            _, out = silent(game.main)  # must not raise
        self.assertIn("Goodbye", out)


class DeathIsTerminalTest(unittest.TestCase):
    """死亡即终态: dead objects can neither act nor be acted upon."""

    def test_dead_enemy_cannot_be_damaged_or_assisted(self):
        enemy = game.Enemy("Orc", {"hp": 50, "attack": 12})
        silent(enemy.take_damage, 999)
        self.assertEqual(enemy.hp, 0)
        silent(enemy.take_damage, 10)  # corpse takes no further damage
        self.assertEqual(enemy.hp, 0)
        ally = game.Ally("Shivansh")
        silent(ally.assist, enemy)  # corpse cannot be hit by an assist
        self.assertEqual(enemy.hp, 0)

    def test_dead_ally_cannot_assist(self):
        ally = game.Ally("Shivansh")
        silent(ally.take_damage, 999)
        enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
        silent(ally.assist, enemy)
        self.assertEqual(enemy.hp, 30)  # dead ally's assist is a no-op

    def test_dead_player_cannot_heal_or_level_up(self):
        player = game.Player("Hero")
        silent(player.take_damage, 999)
        used, _ = silent(player.heal)
        self.assertFalse(used)
        self.assertEqual(player.hp, 0)
        self.assertEqual(player.inventory.count("Potion"), 3)
        silent(player.level_up)
        self.assertEqual(player.max_hp, 100)
        self.assertEqual(player.hp, 0)

    def test_battle_rejects_dead_combatants(self):
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
        silent(enemy.take_damage, 999)
        result, _ = silent(game.battle, player, enemy)  # returns immediately, no input
        self.assertFalse(result)
        self.assertEqual(player.achievements, set())  # a corpse grants no achievement
        self.assertEqual(player.max_hp, 100)          # and no level up
        self.assertEqual(player.inventory.count("Potion"), 3)

        player2 = game.Player("Hero2")
        silent(player2.take_damage, 999)
        enemy2 = game.Enemy("Orc", {"hp": 50, "attack": 12})
        result2, _ = silent(game.battle, player2, enemy2)
        self.assertFalse(result2)
        self.assertEqual(enemy2.hp, 50)  # untouched by the dead player


class AchievementTest(unittest.TestCase):
    """成就幂等: the same achievement can never be granted twice."""

    def test_achievement_granted_once(self):
        player = game.Player("Hero")
        self.assertTrue(player.add_achievement("Defeated Goblin"))
        self.assertFalse(player.add_achievement("Defeated Goblin"))
        self.assertEqual(player.achievements, {"Defeated Goblin"})

    def test_victory_grants_achievement_exactly_once(self):
        random.seed(7)
        player = game.Player("Hero")
        enemy = game.Enemy("Goblin", {"hp": 30, "attack": 10})
        with patch("builtins.input", scripted(["1"] * 50)):
            silent(game.battle, player, enemy)
        self.assertEqual(player.achievements, {"Defeated Goblin"})


class RestartIsolationTest(unittest.TestCase):
    """重开两次(共三局): every session must start from a pristine object graph."""

    def test_three_sessions_share_nothing(self):
        random.seed(2024)
        snapshots = []  # (kind, obj, pristine state captured at construction)

        class ProbePlayer(game.Player):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                snapshots.append(("player", self, (self.hp, self.max_hp,
                                                   list(self.inventory),
                                                   set(self.achievements))))

        class ProbeAlly(game.Ally):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                snapshots.append(("ally", self, (self.hp, self.max_hp, self.attack)))

        class ProbeEnemy(game.Enemy):
            def __init__(self, *a, **k):
                super().__init__(*a, **k)
                snapshots.append(("enemy", self, (self.name, self.hp, self.max_hp)))

        results = []
        in_game = {"flag": False}
        orig_play_game = game.play_game

        def wrapping_play_game(name):
            in_game["flag"] = True
            try:
                return orig_play_game(name)
            finally:
                in_game["flag"] = False

        menu_calls = {"n": 0}

        def smart_input(_prompt=""):
            if in_game["flag"]:
                # attack, but drink a potion when hurt so games actually progress
                current = [o for k, o, _ in snapshots if k == "player"][-1]
                if 0 < current.hp <= 40 and "Potion" in current.inventory:
                    return "2"
                return "1"
            menu_calls["n"] += 1
            if menu_calls["n"] == 1:
                return "bogus"  # invalid replay answer: must re-prompt, not crash
            return "y" if len(results) < 3 else "n"

        def tracked_play_game(name):
            result = wrapping_play_game(name)
            results.append(result)
            return result

        with patch.object(game, "Player", ProbePlayer), \
                patch.object(game, "Ally", ProbeAlly), \
                patch.object(game, "Enemy", ProbeEnemy), \
                patch.object(game, "play_game", tracked_play_game), \
                patch.object(sys, "argv", ["game.py", "Hero"]), \
                patch("builtins.input", smart_input):
            _, out = silent(game.main)

        # three sessions == initial game + two restarts; invalid menu input re-prompted
        self.assertEqual(len(results), 3)
        self.assertIn("Invalid choice! Please enter 'y' or 'n'.", out)
        self.assertIn("Goodbye", out)

        p1, p2, p3 = results
        # no object (or its mutable containers) is ever reused across sessions
        self.assertEqual(len({id(p1), id(p2), id(p3)}), 3)
        for a, b in [(p1, p2), (p2, p3), (p1, p3)]:
            self.assertIsNot(a.inventory, b.inventory)
            self.assertIsNot(a.achievements, b.achievements)

        # every session's player started pristine: no hp/level/potion/achievement leak
        player_snaps = [s for k, _, s in snapshots if k == "player"]
        self.assertEqual(len(player_snaps), 3)
        for hp, max_hp, inv, ach in player_snaps:
            self.assertEqual((hp, max_hp), (100, 100))
            self.assertEqual(inv, ["Potion", "Potion", "Potion"])
            self.assertEqual(ach, set())

        # ally state never stacks across sessions
        ally_snaps = [s for k, _, s in snapshots if k == "ally"]
        self.assertEqual(len(ally_snaps), 3)
        for hp, max_hp, atk in ally_snaps:
            self.assertEqual((hp, max_hp, atk), (50, 50, 8))

        # every enemy ever created started at its pristine stats
        enemy_snaps = [s for k, _, s in snapshots if k == "enemy"]
        self.assertGreaterEqual(len(enemy_snaps), 3)
        expected = {"Goblin": 30, "Orc": 50, "Dragon": 80}
        for name, hp, max_hp in enemy_snaps:
            self.assertEqual((hp, max_hp), (expected[name], expected[name]))

        # sanity: session 1 really did mutate state (otherwise the test proves nothing)
        self.assertTrue(p1.achievements or p1.hp != 100
                        or p1.inventory.count("Potion") != 3)


if __name__ == "__main__":
    unittest.main()
