# Utility functions shared across all games

import random
import string


def generate_room_code():
    """Generate random room code"""
    characters = string.ascii_uppercase + string.digits
    return ''.join(random.choices(characters, k=4))