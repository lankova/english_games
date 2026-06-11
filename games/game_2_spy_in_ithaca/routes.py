from flask import render_template, jsonify
import json
import os


def register_routes(app):
    """Register all routes for Game 2."""

    @app.route("/spy-in-ithaca/rules")
    def game2_rules():
        return render_template("game_2_spy_in_ithaca/rules.html")

    @app.route("/spy-in-ithaca/game")
    def spy_in_ithaca_game():
        return render_template("game_2_spy_in_ithaca/game.html")

    @app.route("/spy-in-ithaca/<room_code>")
    def spy_in_ithaca_room(room_code):
        return render_template("game_2_spy_in_ithaca/game.html")

    @app.route("/api/spy-in-ithaca/locations")
    def get_locations():
        data_dir = os.path.join(os.path.dirname(__file__), "data")

        with open(os.path.join(data_dir, "myths.json"), "r", encoding="utf-8") as f:
            myths = json.load(f)
        with open(os.path.join(data_dir, "odyssey.json"), "r", encoding="utf-8") as f:
            odyssey = json.load(f)
        with open(os.path.join(data_dir, "modern_world.json"), "r", encoding="utf-8") as f:
            modern_world = json.load(f)

        return jsonify({
            "myths": myths,
            "odyssey": odyssey,
            "modern_world": modern_world,
        })
