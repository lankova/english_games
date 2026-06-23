from flask import render_template
import os

def register_routes(app):

    @app.route('/game1/rules')
    def game1_rules():
        return render_template('game_1_describe_and_guess/rules.html')

    @app.route('/game1/game')
    def game1_game():
        return render_template('game_1_describe_and_guess/game.html')

    @app.route('/describe-and-guess/<room_code>')
    def describe_and_guess(room_code):
        return render_template('game_1_describe_and_guess/game.html')

