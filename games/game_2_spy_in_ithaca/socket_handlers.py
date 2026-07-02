import time
import threading
from flask import request
from flask_socketio import emit, join_room
import json
import os
import random

# These will be set by register_handlers
rooms = None
save_room_to_db = None
generate_room_code = None
location_sets = {}

# Questions for any location set (myths, modern world)
QUESTION_IDEAS_ANY_SET = [
    "Apart from me, who was the last person you spoke to?",
    "Are you planning to have fun tonight?",
    "Are you sitting or standing?",
    "Can you bring a child here?",
    "Are there any animals in this location?",
    "Do you think this place is dangerous?",
    "Do you hear any music here?",
    "How loud can it be here?",
    "How many people are usually here?",
    "Is it quiet or noisy?",
    "Is this an old building?",
    "Is this place indoors or outdoors?",
    "Is this place modern or old?",
    "What can you eat or drink here?",
    "What do you see around you?",
    "What do you see out the window?",
    "What does it smell like here?",
    "What sounds can you hear?",
    "What would you do here on a typical day?",
    "Why are you here?",
    "Would you come here alone or with others?",
    "Do you come here often?",
    "Is this place crowded right now?",
    "What time of day is it right now?",
    "Would you bring a friend here?",
    "Is there anything broken around you?",
    "What color are the walls?",
    "Do you feel safe here?",
    "Is this place clean?",
    "What's the temperature like here?",
    "Do you have to be quiet here?",
    "What are people doing around you?",
    "Can you sleep here?",
    "Is this place famous?",
    "Would this be a good place to hide in a zombie apocalypse?",
    "What's the view like from here?",
    "Is the floor wet or dry?",
    "Is this place bigger than your home?",
    "What's the weirdest thing about this place?",
]

# Extra questions only for myths
QUESTION_IDEAS_MYTHS_ODYSSEY = [
    "Is there a god or goddess nearby?",
    "Are there any monsters around?",
    "Do you hear thunder or waves?",
    "Is this place cursed or blessed?",
    "Can a mortal walk here safely?",
    "Is there a hero here?",
    "Do you see any torches or fires?",
    "Is this place made by gods or by humans?",
    "Can you hear someone praying?",
    "Is there a sacrifice happening nearby?",
    "Do you smell incense or smoke?",
    "Is there a temple or altar here?",
    "Are you on a journey right now?",
    "Would you need a ship to get here?",
    "Is someone telling a story or singing?",
]

# Extra questions only for the "everyday" set (modern world)
QUESTION_IDEAS_MODERN_WORLD = [
    "Are the bathrooms here clean or dirty?",
    "Do you need sunglasses when you go outside?",
    "Does this place need a lot of security?",
    "How did you get here today?",
    "How long did it take to get here?",
    "How much does it cost to be here?",
    "Is there anything wrong with what you're wearing?",
    "What did you eat for lunch today?",
    "Is there a line to get in?",
    "Do you need a ticket to be here?",
    "Is there Wi-Fi here?",
    "Would you come here on a first date?",
    "Can you wear shorts and flip-flops here?",
    "Is this place busier at night?",
    "Do people tip here?",
    "Can you take pictures here?",
    "Do you have to take your shoes off?",
    "Is this place open every day?",
    "Would your parents like this place?",
    "Do you need a jacket here?",
    "Can you hear birds or traffic?",
]

QUESTION_ROTATE_SEC = 120

LOCATION_SET_KEYS = ("myths", "modern_world")


def _questions_for_location_set(set_key):
    deck = list(QUESTION_IDEAS_ANY_SET)
    if set_key == "myths":
        deck.extend(QUESTION_IDEAS_MYTHS_ODYSSEY)
    elif set_key == "modern_world":
        deck.extend(QUESTION_IDEAS_MODERN_WORLD)
    return deck


def _load_json(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def register_handlers(socketio, rooms_ref, save_room_fn, generate_code_fn):
    """Register all SocketIO event handlers for Game 2."""
    global rooms, save_room_to_db, generate_room_code, location_sets
    rooms = rooms_ref
    save_room_to_db = save_room_fn
    generate_room_code = generate_code_fn

    # Load location sets from JSON files
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    location_sets = {
        "myths": _load_json(os.path.join(data_dir, "myths.json")),
        "modern_world": _load_json(os.path.join(data_dir, "modern_world.json")),
    }

    def _room(code):
        return rooms.get(code)

    def _player_name_by_sid(room, sid):
        for name, pdata in room["players"].items():
            if pdata.get("sid") == sid:
                return name
        return None

    def _is_sid_connected(sid):
        if not sid:
            return False
        try:
            return socketio.server.manager.is_connected(sid, "/")
        except Exception:
            return False

    def _can_claim_player_name(room, name):
        if name not in room.get("players", {}):
            return True
        old_sid = room["players"][name].get("sid")
        if old_sid == request.sid:
            return True
        if old_sid and _is_sid_connected(old_sid):
            return False
        return True

    def _resolve_player(room, room_code, data=None):
        # Client sends player_name on actions; also maps reconnect sid to an existing player.
        if not room:
            return None
        data = data or {}
        name = (data.get("player_name") or "").strip()
        if name in room.get("players", {}):
            if not _can_claim_player_name(room, name):
                return None
            room["players"][name]["sid"] = request.sid
            join_room(room_code)
            return name
        player = _player_name_by_sid(room, request.sid)
        if player:
            join_room(room_code)
        return player

    def _validate_player_name(name):
        name = (name or "").strip()
        if not name or len(name) > 10:
            return None
        return name

    def _rename_ordered_key(mapping, old_key, new_key):
        if old_key not in mapping:
            return
        items = [(new_key if k == old_key else k, v) for k, v in mapping.items()]
        mapping.clear()
        mapping.update(items)

    def _rename_player_in_room(room, old_name, new_name):
        players = room.get("players", {})
        if old_name not in players:
            return False

        _rename_ordered_key(players, old_name, new_name)

        roles = room.get("roles", {})
        if old_name in roles:
            _rename_ordered_key(roles, old_name, new_name)

        ready = room.get("role_ready", [])
        room["role_ready"] = [new_name if n == old_name else n for n in ready]

        for field in ("vote_initiator", "vote_accused", "guess_spy"):
            if room.get(field) == old_name:
                room[field] = new_name

        votes = {}
        for voter, target in room.get("votes", {}).items():
            votes[new_name if voter == old_name else voter] = (
                new_name if target == old_name else target
            )
        room["votes"].clear()
        room["votes"].update(votes)

        ballots = {}
        for voter, ballot in room.get("vote_ballots", {}).items():
            nk = new_name if voter == old_name else voter
            nb = dict(ballot)
            if nb.get("target") == old_name:
                nb["target"] = new_name
            ballots[nk] = nb
        room["vote_ballots"].clear()
        room["vote_ballots"].update(ballots)

        questions = room.get("player_questions", {})
        if old_name in questions:
            _rename_ordered_key(questions, old_name, new_name)

        last = room.get("last_result")
        if last:
            if last.get("accused") == old_name:
                last["accused"] = new_name
            if last.get("spy") == old_name:
                last["spy"] = new_name
            msg = last.get("message")
            if msg and old_name in msg:
                last["message"] = msg.replace(old_name, new_name)

        return True

    _MID_ROUND_PHASES = frozenset({
        "role_reveal", "playing", "vote_nominate", "voting", "spy_guess", "final_vote",
    })

    def _assign_late_civilian_role(room, name):
        roles = room.setdefault("roles", {})
        if roles.get(name, {}).get("is_spy"):
            return
        roles[name] = {"is_spy": False, "role": None}

    def _is_active_round_phase(room):
        return room.get("phase") in _MID_ROUND_PHASES

    def _role_payload_for_player(room, name):
        role_info = room.get("roles", {}).get(name)
        if not role_info:
            return None
        settings = room["settings"]
        private = {
            "is_spy": role_info["is_spy"],
            "role": role_info["role"],
        }
        if role_info["is_spy"]:
            private["round_duration_sec"] = settings["round_duration_sec"]
        else:
            private["location"] = room.get("secret_location")
            private["location_image"] = room.get("secret_location_image")
            private["extra_roles"] = settings["extra_roles"]
            if role_info["role"]:
                private["role_label"] = role_info["role"]
        return private

    def _catch_up_player(room_code, name):
        # Late join or reconnect
        room = _room(room_code)
        if not room or name not in room.get("players", {}):
            return

        role_payload = _role_payload_for_player(room, name)
        phase = room.get("phase")

        if phase == "role_reveal":
            ready, waiting_for = _role_ready_waiting_for(room)
            emit("spy_role_ready_update", {
                "ready": ready,
                "waiting_for": waiting_for,
            }, to=request.sid)
        elif phase == "playing":
            emit("spy_enter_game", {}, to=request.sid)
            emit("spy_round_started", {
                "duration": room["settings"]["round_duration_sec"],
                "location_set": room["settings"]["location_set"],
            }, to=request.sid)
            if room.get("timer_time_left") is not None:
                emit("spy_timer_update", {
                    "time_left": room["timer_time_left"],
                }, to=request.sid)
            if room.get("timer_paused"):
                emit("spy_timer_paused", {
                    "time_left": room.get("timer_time_left"),
                }, to=request.sid)
            question = room.get("player_questions", {}).get(name)
            if question:
                emit("spy_question_idea", {"question": question}, to=request.sid)
        elif phase == "vote_nominate":
            emit("spy_vote_nomination_started", {
                "initiator": room.get("vote_initiator"),
                "time_left": room.get("timer_time_left"),
            }, to=request.sid)
            if room.get("timer_paused"):
                emit("spy_timer_paused", {"time_left": room.get("timer_time_left")}, to=request.sid)
        elif phase == "voting":
            emit("spy_vote_started", {
                "players": _players_list(room),
                "accused": room.get("vote_accused"),
                "initiator": room.get("vote_initiator"),
                "time_left": room.get("timer_time_left"),
                "spy_count": _public_spy_count(room),
            }, to=request.sid)
        elif phase == "spy_guess":
            emit("spy_guess_started", {
                "spy": room.get("guess_spy"),
                "time_left": room.get("timer_time_left"),
            }, to=request.sid)
        elif phase == "final_vote":
            players = _players_list(room)
            votes = dict(room.get("votes", {}))
            emit("spy_final_vote_started", {
                "players": players,
                "votes": votes,
                "ballots_count": len(votes),
                "players_count": len(players),
            }, to=request.sid)
        elif phase == "results" and room.get("last_result"):
            emit("spy_round_result", {
                "result": room["last_result"],
                "scoreboard": _scoreboard(room),
                "secret_location": room.get("secret_location"),
            }, to=request.sid)

        if role_payload:
            role_emit = dict(role_payload)
            role_emit["show_screen"] = phase == "role_reveal"
            emit("spy_role_assigned", role_emit, to=request.sid)

        state_payload = {
            "phase": room["phase"],
            "players": _players_list(room),
            "settings": _public_settings(room),
            "timer_time_left": room.get("timer_time_left"),
            "timer_paused": room.get("timer_paused", False),
            "votes_open": room.get("votes_open", False),
            "spy_guess_active": room.get("spy_guess_active", False),
            "vote_accused": room.get("vote_accused"),
            "vote_initiator": room.get("vote_initiator"),
            "guess_spy": room.get("guess_spy"),
        }
        if room.get("phase") == "final_vote":
            votes = dict(room.get("votes", {}))
            state_payload["final_votes"] = votes
            state_payload["final_vote_ballots_count"] = len(votes)
            state_payload["final_vote_players_count"] = len(_players_list(room))
        emit("spy_state_update", state_payload, to=request.sid)

    def _emit_to_all_players(room_code, room, event, payload):
        # Room broadcast plus direct sid emit (covers stale room membership after reconnect).
        socketio.emit(event, payload, to=room_code)
        for pdata in room.get("players", {}).values():
            sid = pdata.get("sid")
            if sid:
                socketio.emit(event, payload, to=sid)

    def _players_list(room):
        return list(room["players"].keys())

    def _scoreboard(room):
        return [{"name": n, "display": str(room["players"][n]["score"])} for n in _players_list(room)]

    def _pick_location_set(set_key):
        block = location_sets.get(set_key)
        if not block:
            block = location_sets["modern_world"]
        return block["locations"]

    def _min_players_to_start(settings):
        spy_setting = int(settings.get("spy_count", 1))
        return 4 if spy_setting in (0, 2) else 3

    def _effective_spy_count(room):
        if room.get("resolved_spy_count") is not None:
            return room["resolved_spy_count"]
        spy_setting = int(room["settings"].get("spy_count", 1))
        return spy_setting if spy_setting > 0 else 1

    def _public_spy_count(room):
        # spy_count 0 = "1 or 2 spies" lobby option; hide the resolved count during play.
        spy_setting = int(room["settings"].get("spy_count", 1))
        if spy_setting == 0 and room.get("phase") != "waiting":
            return 0
        return spy_setting

    def _public_settings(room):
        return {
            "spy_count": _public_spy_count(room),
            "extra_roles": room["settings"]["extra_roles"],
            "round_duration_sec": room["settings"]["round_duration_sec"],
            "location_set": room["settings"]["location_set"],
        }

    def _apply_settings_from_data(room, data):
        s = room["settings"]
        if "spy_count" in data:
            v = int(data["spy_count"])
            s["spy_count"] = 0 if v == 0 else min(max(v, 1), 2)
        if "extra_roles" in data:
            s["extra_roles"] = bool(data["extra_roles"])
        if "round_duration_sec" in data:
            minutes = int(data["round_duration_sec"])
            s["round_duration_sec"] = min(max(minutes, 6), 15) * 60
        if "location_set" in data:
            if data["location_set"] in LOCATION_SET_KEYS:
                s["location_set"] = data["location_set"]

    def _broadcast_public_state(room_code, event="spy_state_update"):
        room = _room(room_code)
        if not room:
            return
        payload = {
            "phase": room["phase"],
            "players": _players_list(room),
            "settings": _public_settings(room),
            "timer_time_left": room.get("timer_time_left"),
            "timer_paused": room.get("timer_paused", False),
            "votes_open": room.get("votes_open", False),
            "spy_guess_active": room.get("spy_guess_active", False),
            "vote_accused": room.get("vote_accused"),
            "vote_initiator": room.get("vote_initiator"),
            "guess_spy": room.get("guess_spy"),
        }
        if room.get("phase") == "final_vote":
            votes = dict(room.get("votes", {}))
            payload["final_votes"] = votes
            payload["final_vote_ballots_count"] = len(votes)
            payload["final_vote_players_count"] = len(_players_list(room))
        socketio.emit(event, payload, to=room_code)

    def _stop_timer(room):
        room["round_active"] = False
        room["timer_paused"] = False
        _stop_question_rotation(room)

    def _init_question_deck(room):
        set_key = room["settings"].get("location_set", "modern_world")
        deck = _questions_for_location_set(set_key)
        random.shuffle(deck)
        room["question_deck"] = deck
        room["question_deck_pos"] = 0
        room["player_questions"] = {}

    def _draw_questions(room, count):
        deck = room["question_deck"]
        pos = room["question_deck_pos"]
        drawn = []
        batch_seen = set()

        while len(drawn) < count:
            if pos >= len(deck):
                random.shuffle(deck)
                pos = 0
            question = deck[pos]
            pos += 1
            if question in batch_seen:
                if len(batch_seen) < len(deck):
                    continue
            batch_seen.add(question)
            drawn.append(question)

        room["question_deck_pos"] = pos
        return drawn

    def _assign_question_ideas(room_code):
        # One unique question per player; reshuffle the deck when it runs out.
        room = _room(room_code)
        if not room or room["phase"] != "playing":
            return
        players = _players_list(room)
        if not players:
            return

        questions = _draw_questions(room, len(players))
        player_questions = room.setdefault("player_questions", {})
        for name, question in zip(players, questions):
            player_questions[name] = question
            sid = room["players"][name].get("sid")
            if sid:
                socketio.emit("spy_question_idea", {"question": question}, to=sid)
        save_room_to_db(room_code, rooms)

    def _stop_question_rotation(room):
        room["question_rotation_active"] = False

    def _start_question_rotation(room_code):
        room = _room(room_code)
        if not room:
            return

        old = room.get("question_thread")
        if old and old.is_alive():
            room["question_rotation_active"] = False
            time.sleep(0.15)

        room["question_rotation_active"] = True

        def rotation_task():
            while room.get("question_rotation_active") and room_code in rooms:
                if room.get("phase") != "playing" or room.get("timer_paused"):
                    time.sleep(0.5)
                    continue
                time.sleep(QUESTION_ROTATE_SEC)
                if not room.get("question_rotation_active"):
                    return
                if room.get("phase") == "playing" and not room.get("timer_paused"):
                    _assign_question_ideas(room_code)

        thread = threading.Thread(target=rotation_task, daemon=True)
        room["question_thread"] = thread
        thread.start()

    def _pause_round_timer(room):
        room["timer_paused"] = True

    def _resume_round_timer(room_code):
        room = _room(room_code)
        if not room or room.get("phase") != "playing":
            return
        room["round_active"] = True
        room["timer_paused"] = False
        thread = room.get("timer_thread")
        if thread and thread.is_alive():
            socketio.emit(
                "spy_timer_resumed",
                {"time_left": room.get("timer_time_left")},
                to=room_code,
            )
            return
        _start_round_timer(room_code, reset_duration=False)

    def _award_round(room, winner_side):
        for name, pdata in room["players"].items():
            is_spy = room["roles"][name]["is_spy"]
            if winner_side == "spies" and is_spy:
                pdata["score"] += 1
            elif winner_side == "civilians" and not is_spy:
                pdata["score"] += 1

    def _spy_names(room):
        return [
            name for name in _players_list(room)
            if room["roles"][name]["is_spy"]
        ]

    def _vote_result_message(room, accused):
        spies = _spy_names(room)
        spy_count = _effective_spy_count(room)
        accused_is_spy = room["roles"][accused]["is_spy"]

        if spy_count >= 2:
            if accused_is_spy:
                others = [name for name in spies if name != accused]
                other_spy = others[0] if others else "?"
                return (
                    f"You found a spy! Congratulations! "
                    f"The other spy was {other_spy}."
                )
            if len(spies) >= 2:
                return (
                    f"{accused} was not a spy. "
                    f"{spies[0]} and {spies[1]} were the spies. "
                    f"Spies win this round!"
                )
            spy = spies[0] if spies else "?"
            return (
                f"{accused} wasn't a spy.\n\n{spy} was the spy — and wins this round!"
            )

        if accused_is_spy:
            return f"You found the spy — {accused}"
        spy = spies[0] if spies else "?"
        return (
            f"{accused} wasn't the spy.\n\n{spy} was the spy — and wins this round!"
        )

    def _finish_unanimous_vote(room_code, accused):
        room = _room(room_code)
        if not room:
            return

        accused_is_spy = room["roles"][accused]["is_spy"]
        if accused_is_spy:
            winner = "civilians"
        else:
            winner = "spies"
        message = _vote_result_message(room, accused)

        room["phase"] = "results"
        room["votes_open"] = False
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["vote_accused"] = None
        room["vote_initiator"] = None
        _stop_timer(room)
        room["last_result"] = {
            "reason": "vote",
            "winner": winner,
            "accused": accused,
            "message": message,
            "resolved_spy_count": _effective_spy_count(room),
        }
        _award_round(room, winner_side=winner)
        save_room_to_db(room_code, rooms)
        socketio.emit("spy_round_result", {
            "result": room["last_result"],
            "scoreboard": _scoreboard(room),
            "secret_location": room["secret_location"],
        }, to=room_code)

    def _cancel_voting(room_code, message):
        room = _room(room_code)
        if not room:
            return
        room["phase"] = "playing"
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["vote_accused"] = None
        room["vote_initiator"] = None
        room["votes_open"] = False
        save_room_to_db(room_code, rooms)
        _emit_to_all_players(room_code, room, "spy_vote_cancelled", {"message": message})
        _resume_round_timer(room_code)

    def _begin_final_vote(room_code):
        room = _room(room_code)
        if not room or room.get("phase") != "playing":
            return
        players = _players_list(room)
        room["phase"] = "final_vote"
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["votes_open"] = True
        room["vote_accused"] = None
        room["vote_initiator"] = None
        room["timer_time_left"] = 0
        _stop_timer(room)
        save_room_to_db(room_code, rooms)
        payload = {
            "players": players,
            "votes": {},
            "ballots_count": 0,
            "players_count": len(players),
        }
        _emit_to_all_players(room_code, room, "spy_final_vote_started", payload)
        socketio.emit("spy_timer_update", {"time_left": 0}, to=room_code)
        _broadcast_public_state(room_code)

    def _finish_final_vote_spies_escape(room_code):
        room = _room(room_code)
        if not room:
            return
        room["phase"] = "results"
        room["votes_open"] = False
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["vote_accused"] = None
        room["vote_initiator"] = None
        _stop_timer(room)
        room["last_result"] = {
            "reason": "final_vote_failed",
            "winner": "spies",
            "message": "The spy escapes! Spies win this round!",
        }
        _award_round(room, winner_side="spies")
        save_room_to_db(room_code, rooms)
        socketio.emit("spy_round_result", {
            "result": room["last_result"],
            "scoreboard": _scoreboard(room),
            "secret_location": room["secret_location"],
        }, to=room_code)

    def _evaluate_final_vote(room_code):
        room = _room(room_code)
        if not room or room["phase"] != "final_vote":
            return
        players = _players_list(room)
        votes = room.get("votes", {})
        if len(votes) < len(players):
            return

        for voter, target in votes.items():
            if voter == target:
                return

        accused = None
        for candidate in players:
            others = [p for p in players if p != candidate]
            if all(votes.get(p) == candidate for p in others):
                accused = candidate
                break

        if accused:
            _finish_unanimous_vote(room_code, accused)
        else:
            _finish_final_vote_spies_escape(room_code)

    def _evaluate_voting(room_code):
        # Every eligible voter must vote Yes on the same accused, or the vote is cancelled.
        room = _room(room_code)
        if not room or room["phase"] != "voting":
            return

        ballots = room.get("vote_ballots", {})
        players = _players_list(room)
        accused = room.get("vote_accused")
        if not accused:
            return

        if accused not in players:
            _finish_vote_failed_spies_win(
                room_code,
                "Vote failed — accused player left. Spies win this round!",
            )
            return

        remaining = [p for p in players if p != accused]
        if len(remaining) == 0:
            _finish_vote_failed_spies_win(
                room_code,
                "Vote failed — no voters left. Spies win this round!",
            )
            return

        cancel_msg = "Vote is not unanimous. Continue discussion."

        if any(b.get("decision") == "no" for b in ballots.values()):
            _cancel_voting(room_code, cancel_msg)
            return

        for name in _eligible_voters(room):
            ballot = ballots.get(name)
            if (
                not ballot
                or ballot.get("decision") != "yes"
                or ballot.get("target") != accused
            ):
                return

        initiator = room.get("vote_initiator")
        if initiator and initiator in players and initiator != accused:
            init_ballot = ballots.get(initiator)
            if not init_ballot or init_ballot.get("decision") != "yes":
                return

        _finish_unanimous_vote(room_code, accused)

    def _eligible_voters(room):
        accused = room.get("vote_accused")
        initiator = room.get("vote_initiator")
        return [
            p for p in _players_list(room)
            if p != accused and p != initiator
        ]

    def _finish_vote_failed_spies_win(room_code, message):
        room = _room(room_code)
        if not room:
            return
        room["phase"] = "results"
        room["votes_open"] = False
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["vote_accused"] = None
        room["vote_initiator"] = None
        _stop_timer(room)
        room["last_result"] = {
            "reason": "vote_failed",
            "winner": "spies",
            "message": message,
        }
        _award_round(room, winner_side="spies")
        save_room_to_db(room_code, rooms)
        socketio.emit("spy_round_result", {
            "result": room["last_result"],
            "scoreboard": _scoreboard(room),
            "secret_location": room.get("secret_location"),
        }, to=room_code)

    def _on_player_left_during_voting(room_code, player_name):
        room = _room(room_code)
        if not room or room["phase"] != "voting":
            return

        accused = room.get("vote_accused")
        remaining = [p for p in _players_list(room) if p != accused]
        if accused not in room["players"] or len(remaining) == 0:
            _finish_vote_failed_spies_win(
                room_code,
                f"{player_name} left. Vote failed — spies win this round!",
            )
            return

        _emit_to_all_players(room_code, room, "spy_vote_player_left", {
            "player": player_name,
            "message": f"{player_name} left. Vote continues.",
        })
        save_room_to_db(room_code, rooms)
        _evaluate_voting(room_code)

    def _remove_player_from_room(room_code, player_name):
        room = _room(room_code)
        if not room or player_name not in room.get("players", {}):
            return False
        del room["players"][player_name]
        ready = room.get("role_ready", [])
        if player_name in ready:
            ready.remove(player_name)
        if not room["players"]:
            del rooms[room_code]
            socketio.emit("spy_room_closed", {}, to=room_code)
            return True
        socketio.emit("spy_player_left", {
            "player": player_name,
            "players": _players_list(room),
        }, to=room_code)
        _broadcast_public_state(room_code)
        return False

    def _deal_roles(room_code):
        room = _room(room_code)
        players = _players_list(room)
        settings = room["settings"]
        min_players = _min_players_to_start(settings)
        if len(players) < min_players:
            socketio.emit(
                "error",
                {"message": f"Need at least {min_players} players to start the game"},
                to=request.sid,
            )
            return False

        spy_setting = int(settings.get("spy_count", 1))
        if spy_setting == 0:
            # Random mode: pick 1 or 2 spies when the round is dealt.
            spy_count = random.choice([1, 2])
        else:
            spy_count = min(max(spy_setting, 1), 2)
        spy_count = min(spy_count, len(players) - 1)
        room["resolved_spy_count"] = spy_count

        try:
            locations = _pick_location_set(settings["location_set"])
        except ValueError as exc:
            socketio.emit("error", {"message": str(exc)}, to=request.sid)
            return False
        if not locations:
            socketio.emit(
                "error",
                {"message": "No locations available for this set"},
                to=request.sid,
            )
            return False

        location = random.choice(locations)
        room["secret_location"] = location["name"]
        room["secret_location_image"] = location.get("image")
        room["location_roles"] = location.get("roles", [])

        spies = set(random.sample(players, spy_count))
        room["roles"] = {}

        roles_pool = list(room["location_roles"])
        random.shuffle(roles_pool)

        for name in players:
            if name in spies:
                room["roles"][name] = {"is_spy": True, "role": None}
            else:
                role = None
                if settings["extra_roles"] and roles_pool:
                    role = roles_pool.pop()
                room["roles"][name] = {"is_spy": False, "role": role}

        for name, pdata in room["players"].items():
            role_info = room["roles"][name]
            private = {
                "is_spy": role_info["is_spy"],
                "role": role_info["role"],
            }
            if role_info["is_spy"]:
                private["round_duration_sec"] = room["settings"]["round_duration_sec"]
            else:
                private["location"] = room["secret_location"]
                private["location_image"] = room["secret_location_image"]
                private["extra_roles"] = settings["extra_roles"]
                if role_info["role"]:
                    private["role_label"] = role_info["role"]

            socketio.emit("spy_role_assigned", private, to=pdata["sid"])

        return True

    def _begin_playing_round(room_code):
        room = _room(room_code)
        if not room:
            return
        room["phase"] = "playing"
        room["role_ready"] = []
        _init_question_deck(room)
        save_room_to_db(room_code, rooms)
        _assign_question_ideas(room_code)
        socketio.emit("spy_round_started", {
            "duration": room["settings"]["round_duration_sec"],
            "location_set": room["settings"]["location_set"],
        }, to=room_code)
        _start_round_timer(room_code)
        _start_question_rotation(room_code)
        socketio.emit("spy_enter_game", {}, to=room_code)
        _broadcast_public_state(room_code)

    def _role_ready_waiting_for(room):
        players = _players_list(room)
        ready = list(room.get("role_ready", []))
        waiting_for = None
        if len(ready) == len(players) - 1:
            remaining = [p for p in players if p not in ready]
            if len(remaining) == 1:
                waiting_for = remaining[0]
        return ready, waiting_for

    def _emit_role_ready_update(room_code):
        room = _room(room_code)
        if not room:
            return
        ready, waiting_for = _role_ready_waiting_for(room)
        socketio.emit("spy_role_ready_update", {
            "ready": ready,
            "waiting_for": waiting_for,
        }, to=room_code)

    def _start_round_timer(room_code, reset_duration=True):
        room = _room(room_code)
        if not room:
            return

        old = room.get("timer_thread")
        if old and old.is_alive():
            room["round_active"] = False
            time.sleep(0.15)

        room["round_active"] = True
        room["timer_paused"] = False
        if reset_duration or room.get("timer_time_left") is None:
            room["timer_time_left"] = room["settings"]["round_duration_sec"]

        def timer_task():
            while room.get("round_active") and room_code in rooms:
                if room.get("timer_paused"):
                    time.sleep(0.1)
                    continue

                left = room.get("timer_time_left", 0)
                socketio.emit("spy_timer_update", {"time_left": left}, to=room_code)
                if left <= 0:
                    break
                time.sleep(1)
                if not room.get("round_active"):
                    return
                room["timer_time_left"] = left - 1

            if room_code in rooms and room.get("phase") == "playing":
                _begin_final_vote(room_code)

        thread = threading.Thread(target=timer_task, daemon=True)
        room["timer_thread"] = thread
        thread.start()

    # ------ Socket events ------

    @socketio.on("spy_check_room")
    def handle_spy_check_room(data):
        room_code = data.get("room_code")
        if _room(room_code):
            emit("spy_room_exists", {"exists": True})
        else:
            emit("error", {"message": "Room not found"})

    @socketio.on("spy_create_room")
    def handle_spy_create_room(data):
        name = _validate_player_name(data.get("name"))
        if not name:
            emit("error", {"message": "Name must be 1-10 characters"})
            return

        room_code = generate_room_code()
        sid = request.sid

        rooms[room_code] = {
            "game": "spy_in_ithaca",
            "players": {name: {"score": 0, "sid": sid}},
            "phase": "waiting",
            "game_started": False,
            "settings": {
                "spy_count": 1,
                "extra_roles": True,
                "round_duration_sec": 9 * 60,
                "location_set": "modern_world",
            },
            "round_active": False,
            "timer_paused": False,
            "timer_time_left": None,
            "timer_thread": None,
            "votes": {},
            "vote_ballots": {},
            "vote_accused": None,
            "vote_initiator": None,
            "votes_open": False,
            "spy_guess_active": False,
            "roles": {},
            "role_ready": [],
            "secret_location": None,
        }

        save_room_to_db(room_code, rooms)
        join_room(room_code)

        emit("spy_room_created", {
            "room_code": room_code,
            "players": _players_list(rooms[room_code]),
            "settings": _public_settings(rooms[room_code]),
        }, to=request.sid)

    @socketio.on("spy_join_room")
    def handle_spy_join_room(data):
        name = _validate_player_name(data.get("name"))
        room_code = data.get("room_code")

        room = _room(room_code)
        if not room:
            emit("error", {"message": "Room not found"})
            return

        if not name:
            emit("error", {"message": "Name must be 1-10 characters"})
            return

        if name in room["players"]:
            if not _can_claim_player_name(room, name):
                emit("error", {
                    "message": "This name is already taken. Please choose another.",
                })
                return
            # Same name reconnecting - update sid, do not add a duplicate player.
            room["players"][name]["sid"] = request.sid
            join_room(room_code)
            save_room_to_db(room_code, rooms)
            emit("spy_room_created", {
                "room_code": room_code,
                "players": _players_list(room),
                "settings": _public_settings(room),
                "phase": room["phase"],
                "reconnect": True,
            }, to=request.sid)
            _catch_up_player(room_code, name)
            return

        mid_game = _is_active_round_phase(room)
        room["players"][name] = {"score": 0, "sid": request.sid}
        if mid_game:
            _assign_late_civilian_role(room, name)
        join_room(room_code)
        save_room_to_db(room_code, rooms)

        emit("spy_player_joined", {
            "player": name,
            "players": _players_list(room),
        }, to=room_code)

        emit("spy_room_created", {
            "room_code": room_code,
            "players": _players_list(room),
            "settings": _public_settings(room),
            "phase": room["phase"],
            "mid_game": mid_game,
        }, to=request.sid)

        if mid_game:
            _catch_up_player(room_code, name)

        emit("spy_state_update", {
            "phase": room["phase"],
            "players": _players_list(room),
            "settings": _public_settings(room),
            "timer_time_left": room.get("timer_time_left"),
            "timer_paused": room.get("timer_paused", False),
            "votes_open": room.get("votes_open", False),
            "spy_guess_active": room.get("spy_guess_active", False),
            "vote_accused": room.get("vote_accused"),
            "vote_initiator": room.get("vote_initiator"),
            "guess_spy": room.get("guess_spy"),
        }, to=request.sid)

    @socketio.on("spy_sync_session")
    def handle_spy_sync_session(data):
        room_code = data.get("room_code")
        name = (data.get("player_name") or "").strip()
        room = _room(room_code)
        if not room or not name or name not in room.get("players", {}):
            return
        room["players"][name]["sid"] = request.sid
        join_room(room_code)
        save_room_to_db(room_code, rooms)
        _catch_up_player(room_code, name)

    @socketio.on("spy_rename_player")
    def handle_spy_rename_player(data):
        room_code = data.get("room_code")
        new_name = _validate_player_name(data.get("new_name"))
        room = _room(room_code)
        if not room:
            emit("rename_error", {"message": "Room not found"}, to=request.sid)
            return

        old_name = _resolve_player(room, room_code, data)
        if not old_name:
            emit("rename_error", {"message": "You can only rename yourself"}, to=request.sid)
            return

        if not new_name:
            emit("rename_error", {"message": "Invalid name"}, to=request.sid)
            return

        if new_name == old_name:
            return

        if new_name in room["players"]:
            emit("rename_error", {
                "message": "This name is already taken. Please choose another.",
            }, to=request.sid)
            return

        if not _rename_player_in_room(room, old_name, new_name):
            emit("rename_error", {"message": "Player not found"}, to=request.sid)
            return

        save_room_to_db(room_code, rooms)

        payload = {
            "old_name": old_name,
            "new_name": new_name,
            "players": _players_list(room),
            "vote_initiator": room.get("vote_initiator"),
            "vote_accused": room.get("vote_accused"),
            "guess_spy": room.get("guess_spy"),
        }
        if room.get("phase") == "role_reveal":
            ready, waiting_for = _role_ready_waiting_for(room)
            payload["role_ready"] = {
                "ready": ready,
                "waiting_for": waiting_for,
            }
        if room.get("phase") == "final_vote":
            payload["final_votes"] = dict(room.get("votes", {}))

        payload["scoreboard"] = _scoreboard(room)
        if room.get("last_result"):
            payload["last_result"] = room["last_result"]
        payload["secret_location"] = room.get("secret_location")

        socketio.emit("spy_player_renamed", payload, to=room_code)

    @socketio.on("spy_start_game")
    def handle_spy_start_game(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room:
            emit("error", {"message": "Room not found"})
            return
        if room["phase"] != "waiting":
            emit("error", {"message": "The game has already started"})
            return

        _apply_settings_from_data(room, data)
        min_players = _min_players_to_start(room["settings"])
        if len(_players_list(room)) < min_players:
            emit("error", {
                "message": f"Need at least {min_players} players to start the game",
            })
            return

        room["game_started"] = True

        if not _deal_roles(room_code):
            room["game_started"] = False
            room["phase"] = "waiting"
            room.pop("resolved_spy_count", None)
            save_room_to_db(room_code, rooms)
            return

        room["phase"] = "role_reveal"
        room["role_ready"] = []
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["votes_open"] = False
        room["spy_guess_active"] = False
        save_room_to_db(room_code, rooms)
        _broadcast_public_state(room_code)

    @socketio.on("spy_role_ready")
    def handle_spy_role_ready(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room or room["phase"] != "role_reveal":
            return
        player = _resolve_player(room, room_code, data)
        if not player:
            return
        ready = room.setdefault("role_ready", [])
        if player in ready:
            return
        ready.append(player)
        save_room_to_db(room_code, rooms)
        _emit_role_ready_update(room_code)
        if len(ready) >= len(_players_list(room)):
            _begin_playing_round(room_code)

    @socketio.on("spy_update_settings")
    def handle_spy_update_settings(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room or room["phase"] != "waiting":
            return

        _apply_settings_from_data(room, data)
        save_room_to_db(room_code, rooms)
        _broadcast_public_state(room_code)

    @socketio.on("spy_confirm_settings")
    def handle_spy_confirm_settings(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room:
            return
        if room["phase"] != "setup":
            return

        if not _deal_roles(room_code):
            return

        room["phase"] = "role_reveal"
        room["role_ready"] = []
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["votes_open"] = False
        room["spy_guess_active"] = False
        save_room_to_db(room_code, rooms)
        _broadcast_public_state(room_code)

    @socketio.on("spy_pause_timer")
    def handle_spy_pause_timer(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room or room["phase"] != "playing":
            return
        if "time_left" in data:
            try:
                room["timer_time_left"] = int(data["time_left"])
            except (TypeError, ValueError):
                pass
        room["timer_paused"] = True
        socketio.emit("spy_timer_paused", {"time_left": room.get("timer_time_left")}, to=room_code)

    @socketio.on("spy_resume_timer")
    def handle_spy_resume_timer(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room or room["phase"] != "playing":
            return
        if room.get("timer_time_left", 0) <= 0:
            return
        room["timer_paused"] = False
        socketio.emit("spy_timer_resumed", {"time_left": room["timer_time_left"]}, to=room_code)

    def _open_voting(room_code, accused):
        room = _room(room_code)
        if not room:
            return
        initiator = room.get("vote_initiator")
        room["phase"] = "voting"
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["vote_accused"] = accused
        room["votes_open"] = True
        # Initiator is treated as an automatic Yes; they do not use the Yes/No buttons.
        if initiator and initiator != accused:
            room["vote_ballots"][initiator] = {
                "decision": "yes",
                "target": accused,
            }
            room["votes"][initiator] = accused
        vote_payload = {
            "players": _players_list(room),
            "accused": accused,
            "initiator": initiator,
            "time_left": room.get("timer_time_left"),
            "spy_count": _public_spy_count(room),
        }
        _emit_to_all_players(room_code, room, "spy_vote_started", vote_payload)
        save_room_to_db(room_code, rooms)
        _broadcast_public_state(room_code)

    @socketio.on("spy_start_vote")
    def handle_spy_start_vote(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room:
            emit("error", {"message": "Room not found"})
            return
        if room["phase"] != "playing":
            emit("error", {"message": "You cannot start a vote right now"})
            return
        initiator = _resolve_player(room, room_code, data)
        if not initiator:
            emit("error", {"message": "Player not found in room. Please refresh and rejoin."})
            return

        room["phase"] = "vote_nominate"
        room["vote_initiator"] = initiator
        room["vote_accused"] = None
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["votes_open"] = False
        _pause_round_timer(room)
        nominate_payload = {
            "initiator": initiator,
            "time_left": room.get("timer_time_left"),
        }

        _emit_to_all_players(room_code, room, "spy_vote_nomination_started", nominate_payload)
        _emit_to_all_players(room_code, room, "spy_timer_paused", {
            "time_left": room.get("timer_time_left"),
        })
        save_room_to_db(room_code, rooms)
        _broadcast_public_state(room_code)

    @socketio.on("spy_nominate_accused")
    def handle_spy_nominate_accused(data):
        room_code = data.get("room_code")
        accused = (data.get("target") or "").strip()
        room = _room(room_code)
        if not room:
            emit("error", {"message": "Room not found"})
            return
        if room["phase"] != "vote_nominate":
            emit("error", {"message": "Nomination is not active. Start a vote first."})
            return
        initiator = _resolve_player(room, room_code, data)
        if not initiator:
            emit("error", {"message": "Player not found in room. Please refresh and rejoin."})
            return
        if initiator != room.get("vote_initiator"):
            emit("error", {"message": "Only the player who started the vote can choose"})
            return
        if not accused:
            emit("error", {"message": "Choose a player to accuse"})
            return
        if accused not in room["players"]:
            emit("error", {"message": "Choose a player to accuse"})
            return
        if accused == initiator:
            emit("error", {"message": "You cannot accuse yourself"})
            return
        _open_voting(room_code, accused)

    def _record_ballot(room, voter, target, decision):
        accused = room.get("vote_accused")
        if not accused or target != accused:
            return False
        if voter == accused:
            return False
        if voter == room.get("vote_initiator"):
            return False
        if target not in room["players"]:
            return False
        if voter in room.get("vote_ballots", {}):
            return False

        room.setdefault("vote_ballots", {})[voter] = {
            "decision": decision,
            "target": target,
        }
        if decision == "yes":
            room["votes"][voter] = target
        return True

    @socketio.on("spy_cast_vote")
    def handle_spy_cast_vote(data):
        room_code = data.get("room_code")
        target = (data.get("target") or "").strip()
        room = _room(room_code)
        if not room or room["phase"] != "voting" or not room.get("votes_open"):
            return
        voter = _resolve_player(room, room_code, data)
        if not voter or not target:
            return
        if not _record_ballot(room, voter, target, "yes"):
            return

        save_room_to_db(room_code, rooms)
        players = _players_list(room)
        accused = room.get("vote_accused")
        voters_count = len(players) - (1 if accused in players else 0)
        socketio.emit("spy_vote_cast", {
            "voter": voter,
            "target": target,
            "decision": "yes",
            "votes": dict(room["votes"]),
            "ballots_count": len(room["vote_ballots"]),
            "players_count": voters_count,
        }, to=room_code)
        _evaluate_voting(room_code)

    @socketio.on("spy_vote_no")
    def handle_spy_vote_no(data):
        room_code = data.get("room_code")
        target = (data.get("target") or "").strip()
        room = _room(room_code)
        if not room or room["phase"] != "voting" or not room.get("votes_open"):
            return
        voter = _resolve_player(room, room_code, data)
        if not voter or not target:
            return
        if not _record_ballot(room, voter, target, "no"):
            return

        save_room_to_db(room_code, rooms)
        players = _players_list(room)
        accused = room.get("vote_accused")
        voters_count = len(players) - (1 if accused in players else 0)
        socketio.emit("spy_vote_cast", {
            "voter": voter,
            "target": target,
            "decision": "no",
            "votes": dict(room["votes"]),
            "ballots_count": len(room["vote_ballots"]),
            "players_count": voters_count,
        }, to=room_code)
        _evaluate_voting(room_code)

    @socketio.on("spy_cast_final_vote")
    def handle_spy_cast_final_vote(data):
        room_code = data.get("room_code")
        target = (data.get("target") or "").strip()
        room = _room(room_code)
        if not room or room["phase"] != "final_vote" or not room.get("votes_open"):
            return
        voter = _resolve_player(room, room_code, data)
        if not voter or not target:
            return
        if target not in room["players"]:
            return
        if voter == target:
            emit("error", {"message": "You cannot vote for yourself"})
            return

        room.setdefault("votes", {})[voter] = target
        save_room_to_db(room_code, rooms)
        players = _players_list(room)
        socketio.emit("spy_final_vote_cast", {
            "voter": voter,
            "target": target,
            "votes": dict(room["votes"]),
            "ballots_count": len(room["votes"]),
            "players_count": len(players),
        }, to=room_code)
        _evaluate_final_vote(room_code)

    @socketio.on("spy_start_guess")
    def handle_spy_start_guess(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room:
            emit("error", {"message": "Room not found"})
            return
        if room["phase"] != "playing":
            emit("error", {"message": "You cannot guess the location right now"})
            return
        player_name = _resolve_player(room, room_code, data)
        if not player_name or not room["roles"].get(player_name, {}).get("is_spy"):
            emit("error", {"message": "Only the spy can guess the location"})
            return

        room["phase"] = "spy_guess"
        room["spy_guess_active"] = True
        room["guess_spy"] = player_name
        _pause_round_timer(room)
        save_room_to_db(room_code, rooms)
        socketio.emit("spy_guess_started", {
            "spy": player_name,
            "time_left": room.get("timer_time_left"),
        }, to=room_code)
        socketio.emit("spy_timer_paused", {"time_left": room.get("timer_time_left")}, to=room_code)
        _broadcast_public_state(room_code)

    @socketio.on("spy_submit_guess")
    def handle_spy_submit_guess(data):
        room_code = data.get("room_code")
        guessed_location = (data.get("location") or "").strip()
        room = _room(room_code)
        if not room or room["phase"] != "spy_guess":
            return
        player_name = _resolve_player(room, room_code, data)
        if not player_name or player_name != room.get("guess_spy"):
            return
        if not guessed_location:
            return

        is_correct = guessed_location == room.get("secret_location")
        room["phase"] = "results"
        room["spy_guess_active"] = False
        room["guess_spy"] = None
        _stop_timer(room)

        if is_correct:
            winner = "spies"
            message = f"{player_name} guessed the location correctly! Spies win!"
        else:
            winner = "civilians"
            message = f"{player_name} guessed {guessed_location} — wrong! Civilians win!"

        room["last_result"] = {
            "reason": "spy_guess",
            "winner": winner,
            "message": message,
            "guessed_location": guessed_location,
            "spy": player_name,
        }
        _award_round(room, winner_side=winner)
        save_room_to_db(room_code, rooms)
        socketio.emit("spy_round_result", {
            "result": room["last_result"],
            "scoreboard": _scoreboard(room),
            "secret_location": room["secret_location"],
        }, to=room_code)

    def _return_to_waiting_lobby(room_code):
        room = _room(room_code)
        if not room:
            return False
        _stop_timer(room)
        room["phase"] = "waiting"
        room["game_started"] = False
        room["votes"] = {}
        room["vote_ballots"] = {}
        room["vote_accused"] = None
        room["vote_initiator"] = None
        room["votes_open"] = False
        room["spy_guess_active"] = False
        room["guess_spy"] = None
        room["secret_location"] = None
        room.pop("secret_location_image", None)
        room["roles"] = {}
        room["role_ready"] = []
        room.pop("resolved_spy_count", None)
        room.pop("last_result", None)
        room["player_questions"] = {}
        room["timer_paused"] = False
        room["timer_time_left"] = None
        room.pop("question_deck", None)
        room.pop("question_deck_pos", None)
        save_room_to_db(room_code, rooms)
        return True

    @socketio.on("spy_new_round")
    def handle_spy_new_round(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room:
            emit("error", {"message": "Room not found"})
            return
        if not _resolve_player(room, room_code, data):
            emit("error", {"message": "Player not found"})
            return
        phase = room.get("phase")
        if phase == "waiting" and not room.get("game_started"):
            return
        if not _return_to_waiting_lobby(room_code):
            return
        socketio.emit("spy_next_round_ready", {}, to=room_code)
        _broadcast_public_state(room_code)

    @socketio.on("spy_next_round")
    def handle_spy_next_round(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room:
            return
        if room["phase"] != "results":
            return
        if not _return_to_waiting_lobby(room_code):
            return
        socketio.emit("spy_next_round_ready", {}, to=room_code)
        _broadcast_public_state(room_code)

    @socketio.on("spy_leave_room")
    def handle_spy_leave_room(data):
        room_code = data.get("room_code")
        room = _room(room_code)
        if not room:
            return
        player_name = _resolve_player(room, room_code, data)
        if not player_name:
            return
        phase = room.get("phase")
        if phase == "voting":
            _remove_player_from_room(room_code, player_name)
            save_room_to_db(room_code, rooms)
            _on_player_left_during_voting(room_code, player_name)
            return
        if phase == "final_vote":
            votes = room.get("votes", {})
            if player_name in votes:
                del votes[player_name]
            _remove_player_from_room(room_code, player_name)
            save_room_to_db(room_code, rooms)
            room = _room(room_code)
            if room and room.get("players"):
                _evaluate_final_vote(room_code)
            return
        if phase == "vote_nominate" and player_name == room.get("vote_initiator"):
            _cancel_voting(room_code, f"{player_name} left. Vote cancelled.")
        room_closed = _remove_player_from_room(room_code, player_name)
        if not room_closed:
            save_room_to_db(room_code, rooms)

    @socketio.on("disconnect")
    def handle_spy_disconnect():
        sid = request.sid

        # Game 2 registers disconnect after Game 1; keep DnG host-offline behavior.
        import app as app_module
        for room_code, room_data in app_module.rooms_game1.items():
            if sid == room_data.get("host_sid"):
                room_data["host_sid"] = None
                save_room_to_db(room_code, app_module.rooms_game1)
                socketio.emit(
                    "host_disconnected",
                    {"message": "Host disconnected. Waiting for them to return..."},
                    to=room_code,
                )
                return

        for room_code, room in list(rooms.items()):
            if room.get("game") != "spy_in_ithaca":
                continue
            name = _player_name_by_sid(room, sid)
            if not name:
                continue

            phase = room.get("phase")
            if phase == "voting":
                _remove_player_from_room(room_code, name)
                save_room_to_db(room_code, rooms)
                _on_player_left_during_voting(room_code, name)
            elif phase == "final_vote":
                votes = room.get("votes", {})
                if name in votes:
                    del votes[name]
                _remove_player_from_room(room_code, name)
                save_room_to_db(room_code, rooms)
                room = _room(room_code)
                if room and room.get("players"):
                    _evaluate_final_vote(room_code)
            elif phase == "vote_nominate" and name == room.get("vote_initiator"):
                _cancel_voting(room_code, f"{name} left. Vote cancelled.")
                room["players"][name]["sid"] = None
                save_room_to_db(room_code, rooms)
            else:
                room["players"][name]["sid"] = None
                save_room_to_db(room_code, rooms)
            break