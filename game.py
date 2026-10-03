import sys
import random
import time

# Set to 0 (e.g. in tests) to skip the typing animation and pauses.
DELAY_SCALE = 1.0

# Typing effect and Timer
def pause_print(msg, delay=1.0, typing_speed=0.03):
    if DELAY_SCALE <= 0:
        print(msg)
        return
    for char in msg:
        print(char, end='', flush=True)
        time.sleep(typing_speed * DELAY_SCALE)
    print()
    time.sleep(delay * DELAY_SCALE)

# Classes
class Character:
    def __init__(self, name, hp, attack):
        self.name = name
        self.hp = hp
        self.max_hp = hp  # cap for healing
        self.attack = attack

    def is_alive(self):
        return self.hp > 0

    def take_damage(self, damage):
        if not self.is_alive():
            return  # dead is a terminal state: corpses cannot take more damage
        self.hp -= damage
        if self.hp < 0:   # prevent negative HP
            self.hp = 0
        pause_print(f"{self.name} takes {damage} damage! (HP: {self.hp})", 0.5)

class Player(Character):
    def __init__(self, name, hp=100, attack=15):
        super().__init__(name, hp, attack)
        self.inventory = ["Potion", "Potion", "Potion"]  # start with 3 potions
        self.achievements = set()

    def heal(self):
        if not self.is_alive():
            return False  # dead characters cannot act
        if "Potion" in self.inventory:
            if self.hp >= self.max_hp:
                pause_print(f"{self.name} is already at full HP! Potion not used.", 0.5)
                return False
            self.hp += 20
            if self.hp > self.max_hp:   # cap at current max HP
                self.hp = self.max_hp
            self.inventory.remove("Potion")
            pause_print(
                f"{self.name} drinks a potion and heals 20 HP! (HP: {self.hp})", 1
            )
            pause_print(
                f"Remaining Potions: {self.inventory.count('Potion')}", 0.5
            )
            return True
        else:
            pause_print("No potions left!", 0.5)
            return False

    def add_achievement(self, achievement):
        if achievement in self.achievements:
            return False  # idempotent: an achievement is granted only once
        self.achievements.add(achievement)
        return True

    def level_up(self):
        if not self.is_alive():
            return
        self.max_hp += 10
        self.hp = self.max_hp   # restore to new max
        pause_print(
            f"✨ {self.name} leveled up! Max HP increased to {self.max_hp}. HP fully restored!", 1.5
        )

class Enemy(Character):
    def __init__(self, name, stats):
        super().__init__(name, stats["hp"], stats["attack"])

class Ally(Character):
    def __init__(self, name, hp=50, attack=8):
        super().__init__(name, hp, attack)

    def assist(self, enemy):
        if not self.is_alive() or not enemy.is_alive():
            return  # dead allies cannot act and dead enemies cannot be hit
        damage = random.randint(3, self.attack)
        pause_print(f"{self.name} assists and hits {enemy.name} for {damage}!", 1)
        enemy.take_damage(damage)

# Input helper: keeps prompting on invalid input; EOF propagates to main()
def read_choice(valid_options, error_msg):
    choice = ""
    while choice not in valid_options:
        choice = input("> ").strip().lower()
        if choice not in valid_options:
            pause_print(error_msg, 0.5)
    return choice

# GamePlay Program
def player_turn(player, enemy, ally):
    pause_print("\nChoose action:", 0.5)
    print("1. Attack")
    print("2. Heal (use potion)")
    print("3. Call Ally")

    choice = read_choice(["1", "2", "3"], "Invalid choice! Please enter 1, 2, or 3.")

    if choice == "1":
        damage = random.randint(5, player.attack)
        pause_print(f"{player.name} attacks {enemy.name} for {damage}!", 1)
        enemy.take_damage(damage)
    elif choice == "2":
        player.heal()
    elif choice == "3":
        if ally and ally.is_alive():
            ally.assist(enemy)
        else:
            pause_print(f"{player.name}'s ally cannot answer the call!", 0.5)

def battle(player, enemy, ally=None, is_final=False):
    if not player.is_alive() or not enemy.is_alive():
        return False  # a battle requires two living combatants

    pause_print(f"\n⚔️ Battle starts: {player.name} vs {enemy.name}!\n", 1.5)

    while player.is_alive() and enemy.is_alive():
        player_turn(player, enemy, ally)

        if enemy.is_alive():
            # Safe damage range
            low = 1 if enemy.attack < 3 else 3
            damage = random.randint(low, enemy.attack)
            pause_print(f"{enemy.name} strikes back for {damage}!", 1)
            player.take_damage(damage)

    if player.is_alive() and not enemy.is_alive():
        pause_print(f"\n✅ {player.name} defeated {enemy.name}!\n", 1.5)
        player.add_achievement(f"Defeated {enemy.name}")

        # Chance for potion drop (30%)
        if random.random() < 0.3:
            player.inventory.append("Potion")
            pause_print(f"🍷 {enemy.name} dropped a Potion! Added to inventory.", 1)
            pause_print(f"Potions now: {player.inventory.count('Potion')}", 0.5)

        # Level up only if NOT the final enemy
        if not is_final:
            player.level_up()

        return True
    else:
        pause_print(f"\n💀 {player.name} was defeated by {enemy.name}...\n", 1.5)
        return False

# Main Game
def play_game(player_name):
    # Session boundary: every run builds a fresh object graph, so nothing from a
    # previous game (hp, potions, levels, achievements, ally state) can leak in.
    player = Player(player_name, hp=100, attack=15)

    enemies = [
        ("Goblin", {"hp": 30, "attack": 10}),
        ("Orc", {"hp": 50, "attack": 12}),
        ("Dragon", {"hp": 80, "attack": 20})  # Final boss
    ]

    ally = Ally("Shivansh")

    for i, (name, stats) in enumerate(enemies):
        is_final = (i == len(enemies) - 1)  # check if last enemy
        enemy = Enemy(name, stats)
        if not battle(player, enemy, ally, is_final=is_final):
            break

    pause_print(f"\n🎉 Game Over! {player.name}'s Summary:", 1.5)
    pause_print(f"Inventory: {player.inventory}", 1)
    pause_print(f"Achievements: {player.achievements}", 1)
    return player

def main():
    if len(sys.argv) < 2:
        player_name = "Hero"  # default name
        pause_print("No name given, using default: Hero", 0.5)
    else:
        player_name = sys.argv[1]

    try:
        while True:
            play_game(player_name)

            # Ask user if they want to continue
            pause_print("\nDo you want to play again? (y/n): ", 0.5)
            choice = read_choice(
                ["y", "n", "yes", "no"],
                "Invalid choice! Please enter 'y' or 'n'.",
            )

            if choice in ["n", "no"]:
                pause_print("\n👋 Thanks for playing! Goodbye!", 1)
                break
    except (EOFError, KeyboardInterrupt):
        # Closed stdin (Ctrl+D) / Ctrl+C: leave gracefully instead of crashing.
        pause_print("\n👋 Thanks for playing! Goodbye!", 1)

if __name__ == "__main__":
    main()
