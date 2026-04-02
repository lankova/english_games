# from flask import Flask, redirect, url_for, request
import random
# import string

# app = Flask(__name__)

# rooms = {}

# def generate_room_code():
#     return ''.join(random.choices(string.ascii_uppercase, k=4))

# @app.route(/'rooms')
# def start (): #Когда нажимаешь на "start a new game, человек попадает в room и выполняется код ниже"
#     room_code = generate_room_code()
#     rooms[room_code] = [] #список комнат
#     return redirect(url_for('rooms', room_code=room_code)) #перенаправляем игрока в комнату

# @app.route('/rooms/<room_code>')
# def rooms(room_code):
#     if room_code not in rooms:
#         return "Not found", 404 #если нет такой комнаты
#     '''return f'''
   
    

# @app.route('/join', methods=['POST'])
# def join_room(): # обрабатываем запрос на присоединение
#     room_code = request.form['room_code']
#     player_name = request.form['player_name']
#     if room_code in rooms:
#         # добавляем игрока и перенаправляем его обратно
#         rooms[room_code].append(player_name)
#         return redirect(url_for('rooms', room_code=room_code))
#     return "Not found", 404

# if __name__ == '__main__':
#     app.run(debug=True)

# players = ["Kate", "Lida", "Olga"]
# chameleon = random.choice(players)
# vote_for_chameleon = "Kate"
# print(chameleon) # Это строка только для создания игры, потом удалю.
# print(vote_for_chameleon in chameleon)
# if vote_for_chameleon in chameleon:
#     print(f"We voted for {vote_for_chameleon}. WE FOUND THE CHAMELEON! Now {vote_for_chameleon} has 30 seconds to find our secret word.")
# else:
#     print(f"We voted for {vote_for_chameleon}. We were wrong. {chameleon.upper()} was the chameleon!")

#vote
Kate = 2
Olga = 2
Lida = 3
# if Kate > Olga > Lida:
#     print("We voted for Kate")
# elif Olga > Lida > Kate:
#     print("We vote for Olga")
# elif Lida > Kate > Olga:
#     print("We voted for Lida")
# else:
#     print(f"There is a tie. Results of the vote: Lida {Lida}, Olga {Olga}, Lida {Lida}.")

print(Lida > Olga and Lida > Kate)
