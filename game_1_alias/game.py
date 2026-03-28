from flask import Flask
app = Flask(__name__)

from random import shuffle
import os
import time

class TabooGame:
    def __init__(self):
        self.words_db = {
            "easy": [
                {"word": "apple", "forbidden": ["fruit", "red", "tree", "iPhone"]},
                {"word": "car", "forbidden": ["vehicle", "drive", "road", "wheel"]},
                {"word": "book", "forbidden": ["read", "pages", "story", "library"]},
                {"word": "sun", "forbidden": ["star", "hot", "sky", "light"]},
                {"word": "water", "forbidden": ["drink", "liquid", "ocean", "wet"]}
            ],
            "medium": [
                {"word": "quantum", "forbidden": ["physics", "mechanics", "atom", "energy"]},
                {"word": "algorithm", "forbidden": ["computer", "program", "code", "math"]},
                {"word": "biodiversity", "forbidden": ["species", "ecosystem", "nature", "variety"]},
                {"word": "metaphor", "forbidden": ["comparison", "figure", "speech", "literal"]},
                {"word": "symphony", "forbidden": ["orchestra", "music", "beethoven", "concert"]}
            ],
            "hard": [
                {"word": "photosynthesis", "forbidden": ["plants", "sunlight", "chlorophyll", "oxygen"]},
                {"word": "entrepreneurship", "forbidden": ["business", "startup", "venture", "innovation"]},
                {"word": "deoxyribonucleic", "forbidden": ["DNA", "acid", "genetic", "molecule"]},
                {"word": "philosophical", "forbidden": ["philosophy", "thinking", "theory", "wisdom"]},
                {"word": "counterintuitive", "forbidden": ["unexpected", "paradox", "contrary", "logic"]}
            ]
        }
        self.time_limit = 60
        self.score = {0: 0}

    def setup_game(self):
        print("🎯 Welcome to Taboo Word Guessing Game! 🎯")
        print("\nHow to play:")
        print("- One player describes words without using the word itself or forbidden words")
        print("- Other players try to guess as many words as possible within the time limit")
        print("- Each correct guess = 1 point")
        print("- Using forbidden words = -1 point")
        print("- Skipping a word = 0 points")
       
        self.score = {0: 0}
       
        # Choose difficulty
        print("\nChoose difficulty level:")
        print("1. Easy")
        print("2. Medium")
        print("3. Hard")

while True:
            try:
                choice = int(input("Enter choice (1-3): "))
                if 1 <= choice <= 3:
                    self.difficulty = ["easy", "medium", "hard"][choice-1]
                    break
                else:
                    print("Please enter 1, 2, or 3")
            except ValueError:
                print("Please enter a valid number")
   
    def get_random_word(self):
        """Get a random word from the current difficulty level"""
        return random.choice(self.words_db[self.difficulty])
   
    def display_word_info(self, word_data):
        """Display the word and forbidden words to the describer"""
        print(f"\n{'='*50}")
        print(f"Word to describe: 🎯 {word_data['word'].upper()} 🎯")
        print(f"Forbidden words: ❌ {', '.join(word_data['forbidden'])} ❌")
        print(f"{'='*50}")
   
    def run_round(self, team_index):
        """Run a round for one team"""
        print(f"\n{'#'*60}")
        print(f"Team {self.teams[team_index]}'s turn!")
        print(f"Current score: {self.teams[0]} - {self.score[0]} | {self.teams[1]} - {self.score[1]}")
        print(f"{'#'*60}")
       
        input(f"\nPlayer from {self.teams[team_index]}, press Enter when you're ready to describe...")
       
        round_score = 0
        start_time = time.time()
        words_used = []
       
        print(f"\n⏰ Time starts now! You have {self.time_limit} seconds!")
        print("Type 'skip' to skip a word, 'quit' to end round early")
       
        while time.time() - start_time < self.time_limit:
            # Get a new word (ensure no repeats in same round)
            word_data = self.get_random_word()
            while word_data['word'] in words_used:
                word_data = self.get_random_word()
           
            words_used.append(word_data['word'])
            self.display_word_info(word_data)
           
            # Get input from describer
            guess_start = time.time()
            user_input = input("\nEnter 'correct', 'skip', 'quit', or describe: ").strip().lower()
           
            if user_input == 'correct':
                round_score += 1
                print("✅ Correct! +1 point")
            elif user_input == 'skip':
                print("⏭️  Word skipped")
            elif user_input == 'quit':
                print("🛑 Round ended early")
                break
            else:
                # Check if describer used forbidden words
                used_forbidden = False
                for forbidden in word_data['forbidden']:
                    if forbidden in user_input.lower():
                        print(f"❌ Used forbidden word: '{forbidden}'! -1 point")
                        round_score -= 1
                        used_forbidden = True
                        break
               
                if not used_forbidden:
                    print("⚠️  Remember to type 'correct' when your team guesses the word!")
           
            # Show remaining time
            elapsed = time.time() - start_time
            remaining = max(0, self.time_limit - elapsed)
            print(f"⏰ Time remaining: {remaining:.1f} seconds")
           
            if remaining <= 0:
                print("⏰ Time's up!")
                break
       
        # Update team score
        self.score[team_index] += round_score
        print(f"\n🎊 Round over! {self.teams[team_index]} scored {round_score} points this round!")
        print(f"Total score: {self.teams[0]} - {self.score[0]} | {self.teams[1]} - {self.score[1]}")
   
    def play_game(self):
        """Main game loop"""
        self.setup_game()
       
        rounds_played = 0
        max_rounds = 3  # Play best of 3 rounds per team
       
        while rounds_played < max_rounds:
            for team in [0, 1]:
                self.run_round(team)
                rounds_played += 1
               
                # Check if game should continue
                if rounds_played >= max_rounds:
                    points_needed = (max_rounds // 2) + 1
                    if any(score >= points_needed for score in self.score.values()):
                        break
           
            # Ask if players want to continue
            if rounds_played < max_rounds * 2:  # Maximum possible rounds
                continue_game = input("\nContinue to next round? (y/n): ").lower().strip()
                if continue_game != 'y':
                    break
       
        # Game over - declare winner
        self.declare_winner()
   
    def declare_winner(self):
        """Display final results and winner"""
        print(f"\n{'🎊'*20}")
        print("GAME OVER!")
        print(f"{'🎊'*20}")
        print(f"Final Scores:")
        print(f"{self.teams[0]}: {self.score[0]} points")
        print(f"{self.teams[1]}: {self.score[1]} points")
       
        if self.score[0] > self.score[1]:
            print(f"🎉 {self.teams[0]} WINS! 🎉")
        elif self.score[1] > self.score[0]:
            print(f"🎉 {self.teams[1]} WINS! 🎉")
        else:
            print("🤝 It's a TIE! 🤝")
       
        print(f"\nThanks for playing Alias!")
   
    def add_custom_words(self):
        """Allow players to add their own words to the game"""
        print("\nWould you like to add custom words? (y/n)")
        if input().lower() != 'y':
            return
       
        print("\nAdd custom words (format: word,forbidden1,forbidden2,forbidden3)")
        print("Example: computer,machine,laptop,electronic")
        print("Type 'done' when finished")
       
        while True:
            custom_input = input("\nEnter word and forbidden words: ").strip()
            if custom_input.lower() == 'done':
                break
           
            parts = [part.strip() for part in custom_input.split(',')]
            if len(parts) >= 2:
                word = parts[0]
                forbidden = parts[1:5]  # Max 4 forbidden words
               
                # Add to medium difficulty by default
                self.words_db["medium"].append({"word": word, "forbidden": forbidden})
                print(f"✅ Added: {word} (forbidden: {', '.join(forbidden)})")
            else:
                print("❌ Invalid format. Please use: word,forbidden1,forbidden2,forbidden3")

# Run the game
if __name__ == "__main__":
    game = AliasGame()
    game.add_custom_words()
    game.play_game()
        
