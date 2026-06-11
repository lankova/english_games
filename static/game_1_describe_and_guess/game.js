function shuffleArray(array) {
    const shuffled = [...array];
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return shuffled;
}

// Create a WebSocket connection to the server.
// This socket acts as a two‑way communication channel for live game events.
const socket = io();

let currentRoomCode = null;
let playerName = null;
let cards = []; // Used only during skipped-card replay at the end of a round.
let currentIndex = 0;
let currentWord = null; // Next word from the server pool (shared across the whole game).
let skippedCards = [];
let inSkippedReplay = false;
let score = 0;
let explainerName = null;
let isHost = false;  // Track if current player is the room host
let hostToken = null;
let allCardsDone = false;
const savedHostToken = sessionStorage.getItem('hostToken');
if (savedHostToken) hostToken = savedHostToken;

// Check if there's a room code in the URL
const urlParams = new URLSearchParams(window.location.search);
const roomFromUrl = urlParams.get('room');

if (roomFromUrl) {
    // Trying to join a room
    currentRoomCode = roomFromUrl;
    socket.emit('check_room', { room_code: roomFromUrl });
    document.getElementById('screen-name').style.display = 'flex';
} else {
    // No room code - show name screen for creating a new room
    document.getElementById('screen-name').style.display = 'flex';
}

function requestNextWord(callback) {
    if (!currentRoomCode) {
        currentWord = null;
        if (callback) callback();
        return;
    }
    socket.emit('request_word', {
        room_code: currentRoomCode,
        player_name: playerName,
    }, (response) => {
        currentWord = response && response.word != null ? response.word : null;
        if (callback) callback();
    });
}

function handleAllCardsDone() {
    allCardsDone = true;
    socket.emit('all_cards_done', { room_code: currentRoomCode });

    document.getElementById('cardWord').style.display = 'none';
    document.querySelector('.card-container').style.display = 'none';
    document.getElementById('all-cards-done').style.display = 'block';
    document.getElementById('next-round-btn').style.display = 'none';
    document.getElementById('new-game-btn').style.display = 'block';
    document.getElementById('back-to-main-btn').style.display = 'block';

    endRound();
}

// Update players on score screen
function updatePlayersList(playersArray) {
    const playersList = document.getElementById('players-list');
    if (!playersList) return;
    playersList.innerHTML = '';
    playersArray.forEach(name => {
        const li = document.createElement('li');
        li.setAttribute('data-player', name);
        li.textContent = name;
        playersList.appendChild(li);   // ← исправлено
    });
}


// Show countdown 3-2-1 before revealing the card
function startCountdown(callback) {
    let count = 3;
    const countdownElement = document.getElementById('countdown');
    countdownElement.style.display = 'block';
    countdownElement.textContent = count;

    const interval = setInterval(() => {
        count--;
        if (count >= 1) {
            countdownElement.textContent = count;
        } else {
            clearInterval(interval);
            countdownElement.style.display = 'none';
            if (callback) callback();
        }
    }, 1000);
}


function showCard(index) {
    if (inSkippedReplay) {
        if (index < cards.length) {
            document.getElementById('cardWord').textContent = cards[index];
            document.getElementById('cardWord').style.display = 'block';
            document.querySelector('.card-container').style.display = 'flex';
        } else {
            handleAllCardsDone();
        }
        return;
    }

    if (currentWord !== null) {
        document.getElementById('cardWord').textContent = currentWord;
        document.getElementById('cardWord').style.display = 'block';
        document.querySelector('.card-container').style.display = 'flex';
    } else if (skippedCards.length > 0) {
        openSkippedCardsDialog();
    } else {
        handleAllCardsDone();
    }
}

function openSkippedCardsDialog() {
    const timeLeft = document.getElementById('guessing-timer').textContent.trim();
    document.getElementById('skipped-cards-time-left').textContent =
        `You have ${timeLeft} seconds left.`;
    document.getElementById('skipped-cards-dialog').style.display = 'block';
    if (currentRoomCode) {
        socket.emit('pause_timer', {
            room_code: currentRoomCode,
            time_left: parseInt(timeLeft, 10)
        });
    }
}

function endRound() {
    console.log('endRound called. allCardsDone:', allCardsDone, 'explainerName:', explainerName, 'playerName:', playerName);
    // Hide UI elements
    document.getElementById('guessedBtn').style.display = 'none';
    document.getElementById('skipBtn').style.display = 'none';
    document.getElementById('cardWord').style.display = 'none';
    document.getElementById('all-cards-done').style.display = 'none';
    document.getElementById('skipped-cards-dialog').style.display = 'none';

    // Only the explainer sends round data to server (only the explainer can get points during the round)
    if (explainerName === playerName) {
        socket.emit('round_end', {
            room_code: currentRoomCode,
            player: playerName,
            round_score: Number(score)
        });
    }
            score = 0;
}

function nextCard() {
    if (inSkippedReplay) {
        currentIndex++;
        showCard(currentIndex);
        return;
    }
    requestNextWord(() => showCard(currentIndex));
}

// ---------- Socket events ----------

socket.on('room_created', (data) => {
    if (data.host_token) {
        hostToken = data.host_token;
        sessionStorage.setItem('hostToken', hostToken);
    }
    currentRoomCode = data.room_code;
    isHost = data.is_host || false;

    /* --- DEBUG LOGS (uncomment if needed) --- */
    console.log('🔍 is_host received:', data.is_host);
    console.log('📦 full data:', data);
    /* ---------------------------------------- */

    // Add room code to URL
    const newUrl = `${window.location.origin}/describe-and-guess/${currentRoomCode}`;
    window.history.pushState({}, '', newUrl);

    document.getElementById('screen-waiting').style.display = 'flex';
    document.getElementById('screen-name').style.display = 'none';

    // Show "Start Game" button only for the host
    document.getElementById('startGame').style.display = isHost ? 'block' : 'none';
    updatePlayersList(data.players);
});


// Switch to waiting screen when a player joins (ensures non‑host players see the waiting room)
socket.on('player_joined', (data) => {
    console.log('Players in room:', data.players);
    updatePlayersList(data.players);
    if (!isHost && document.getElementById('screen-waiting').style.display !== 'flex') {
        document.getElementById('screen-name').style.display = 'none';
        document.getElementById('screen-waiting').style.display = 'flex';
    }
});

socket.on('game_started', () => {
    console.log('game_started event received!');
    document.getElementById('screen-waiting').style.display = 'none';
    document.getElementById('screen-game').style.display = 'flex';
    document.getElementById('becomeExplainerBtn').style.display = 'block';
    // Hide other elements initially
    document.querySelector('.card-container').style.display = 'none';
    document.getElementById('guessedBtn').style.display = 'none';
    document.getElementById('skipBtn').style.display = 'none';
    document.getElementById('message_non-explainers').style.display = 'none';
    document.getElementById('countdown').style.display = 'none';
    document.getElementById('next-round-btn').style.display = 'none';
});


socket.on('round_started', (data) => {
    explainerName = data.explainer;
    document.getElementById('explainer-name').textContent = explainerName;

    // Hide "I'll explain" button and prompt for everyone
    document.querySelector('.explainer-prompt').style.display = 'none';
    document.getElementById('becomeExplainerBtn').style.display = 'none';
    document.getElementById('becomeExplainerBtn').style.pointerEvents = 'none';

    // CHECK LATE JOIN FIRST - before showing countdown
    if (data.late_join) {
        // Late joiner - skip countdown, go straight to the round
        // Late joiner is always a guesser for that round
        document.getElementById('guessing-timer').style.display = 'block';
        document.querySelector('.guessing-timer-label').style.display = 'block';
        document.getElementById('message_non-explainers').style.display = 'block';
        document.querySelector('.card-container').style.display = 'none';
        document.getElementById('guessedBtn').style.display = 'none';
        document.getElementById('skipBtn').style.display = 'none';
        return;
    }

    // Normal flow - show countdown
    document.getElementById('countdown').style.display = 'block';
    document.getElementById('countdown').textContent = '3';


    if (data.explainer === playerName) {
        // This client is the explainer
        startCountdown(() => {
        // Countdown finished - now start the real timer on server
        socket.emit('start_timer', { room_code: currentRoomCode });
        document.querySelector('.guessing-timer-label').style.display = 'block';
        document.getElementById('guessing-timer').style.display = 'block';
        document.getElementById('guessing-timer').textContent = data.duration;
        // Show card, buttons, timer
            document.querySelector('.card-container').style.display = 'flex';
            document.getElementById('guessedBtn').style.display = 'inline-block';
            document.getElementById('skipBtn').style.display = 'inline-block';
            document.getElementById('message_non-explainers').style.display = 'none';
            inSkippedReplay = false;
            currentIndex = 0;
            requestNextWord(() => showCard(currentIndex));
        });
    } else {
        // Non-explainer - also see the countdown
        startCountdown(() => {
            // Countdown finished, show waiting message
            document.querySelector('.guessing-timer-label').style.display = 'block';
            document.getElementById('guessing-timer').style.display = 'block';
            document.getElementById('message_non-explainers').style.display = 'block';
        });
        // Hide explainer-only elements
        document.querySelector('.card-container').style.display = 'none';
        document.getElementById('guessedBtn').style.display = 'none';
        document.getElementById('skipBtn').style.display = 'none';
    }
});

socket.on('timer_update', (data) => {
    document.getElementById('guessing-timer').textContent = data.time_left;
    const skippedDialog = document.getElementById('skipped-cards-dialog');
    if (skippedDialog.style.display === 'block') {
        document.getElementById('skipped-cards-time-left').textContent =
            `You have ${data.time_left} seconds left.`;
    }
});

socket.on('round_timeout', () => {
    console.log('round_timeout received. allCardsDone:', allCardsDone, 'explainerName:', explainerName);
    if (allCardsDone) return
    endRound();
});

socket.on('error', (data) => {
    // If the room doesn't exist, show the error screen
    if (data.message === 'Room not found') {
        // Hide the name input screen
        document.getElementById('screen-name').style.display = 'none';
        // Show the error message screen with a button to go home
        document.getElementById('screen-error').style.display = 'block';
    } else if (data.message === 'This name is already taken. Please choose another.') {
        document.getElementById('screen-waiting').style.display = 'none';
        document.getElementById('screen-name').style.display = 'flex';
        const nameError = document.getElementById('name-error');
        nameError.textContent = 'This name is already taken. Please choose another.';
        nameError.classList.add('show');
    } else {
        // For any other errors, show a simple alert (keeps it simple for the user)
        alert(data.message);
    }
});

socket.on('room_exists', (data) => {
    if (data.exists) {
    // Room exists, show name input (already visible)
        console.log('Room exists, ready to join');
    }
});

socket.on('scoreboard_update', (data) => {
    // Hide round UI elements for ALL players
    document.getElementById('guessing-timer').style.display = 'none';
    document.querySelector('.guessing-timer-label').style.display = 'none';
    document.getElementById('guessedBtn').style.display = 'none';
    document.getElementById('skipBtn').style.display = 'none';
    document.querySelector('.card-container').style.display = 'none';
    document.getElementById('message_non-explainers').style.display = 'none';
    document.getElementById('countdown').style.display = 'none';
    document.getElementById('becomeExplainerBtn').style.display = 'none';
    document.querySelector('.explainer-prompt').style.display = 'none';
    document.getElementById('screen-waiting').style.display = 'none';
    document.getElementById('screen-game').style.display = 'flex';

    document.getElementById('round-result').style.display = 'block';

    if (allCardsDone) {
        document.getElementById('all-cards-done').style.display = 'block';
    }

    // Show who scored and how much this round
    if (data.last_round) {
        document.getElementById('result-message').textContent =
            `${data.last_round.player} got ${data.last_round.score} point${data.last_round.score !== 1 ? 's' : ''} this round!`
    } else {
        document.getElementById('result-message').textContent = 'Round finished!';
    }

    // Show/hide buttons based on the role
    if (!isHost) {
        document.getElementById('next-round-btn').style.display = 'none';
        document.getElementById('new-game-btn').style.display = 'none';
        document.getElementById('back-to-main-btn').style.display = 'none';

        if (data.all_cards_done) {
            document.getElementById('all-cards-done').style.display = 'block';
            document.getElementById('waiting-host-message').textContent = 'Waiting for the host to start a new game...';
        } else {
            document.getElementById('waiting-host-message').textContent = 'Waiting for the host to start a new round...';
        }
        document.getElementById('waiting-host-message').style.display = 'block';
    //* For the host *//
    } else if (data.all_cards_done) {
        document.getElementById('all-cards-done').style.display = 'block';
        document.getElementById('next-round-btn').style.display = 'none';
        document.getElementById('new-game-btn').style.display = 'block';
        document.getElementById('back-to-main-btn').style.display = 'block';
    } else {
        document.getElementById('next-round-btn').style.display = 'block';
        document.getElementById('new-game-btn').style.display = 'none';
        document.getElementById('back-to-main-btn').style.display = 'block';
    }

    const tbody = document.querySelector('#results-table tbody');
    tbody.innerHTML = '';

    // Using textContent  to avoid XSS (Cross-Site Scripting)
    data.scoreboard.forEach(row => {
        const tr = document.createElement('tr'); // table row
        const tdName = document.createElement('td'); // table data
        tdName.textContent = row.name; // pLayer's name
        const tdScore = document.createElement('td'); // player's score
        tdScore.textContent = row.display;
        tr.appendChild(tdName);
        tr.appendChild(tdScore);
        tbody.appendChild(tr);
    });

    document.getElementById('score-table').style.display = 'block';
});

// Next round button
document.getElementById('next-round-btn').onclick = () => {
    socket.emit('next_round', { room_code: currentRoomCode });
};

socket.on('next_round_ready', () => {
    // Reset for a new round
    document.getElementById('guessing-timer').style.display = 'none';
    document.querySelector('.guessing-timer-label').style.display = 'none';
    document.getElementById('all-cards-done').style.display = 'none';
    document.getElementById('waiting-host-message').style.display = 'none';
    allCardsDone = false;
    document.getElementById('explainer-name').textContent = 'The explainer';
    score = 0;
    currentIndex = 0;
    currentWord = null;
    cards = [];
    skippedCards = [];
    inSkippedReplay = false;

    // Hide result and score table
    document.getElementById('round-result').style.display = 'none';
    document.getElementById('score-table').style.display = 'none';
    document.getElementById('next-round-btn').style.display = 'none';
    document.getElementById('new-game-btn').style.display = 'none';
    document.getElementById('back-to-main-btn').style.display = 'none';

    // Show explainer selection screen
    document.querySelector('.explainer-prompt').style.display = 'block';
    document.getElementById('becomeExplainerBtn').style.display = 'block';
    document.getElementById('becomeExplainerBtn').style.pointerEvents = 'auto';


    // Card stays hidden until explainer is chosen and countdown finishes
    document.querySelector('.card-container').style.display = 'none';
});

socket.on('new_game_ready', () => {
    allCardsDone = false;
    currentIndex = 0;
    score = 0;
    skippedCards = [];
    document.getElementById('all-cards-done').style.display = 'none';
    document.getElementById('round-result').style.display = 'none';
    document.getElementById('score-table').style.display = 'none';
    document.getElementById('waiting-host-message').style.display = 'none';
    document.getElementById('new-game-btn').style.display = 'none';
    document.getElementById('back-to-main-btn').style.display = 'none';
    document.getElementById('next-round-btn').style.display = 'none';

    document.querySelector('.card-container').style.display = 'none';
    document.getElementById('cardWord').style.display = 'none';
    currentWord = null;
    cards = [];
    inSkippedReplay = false;

    document.querySelector('.explainer-prompt').style.display = 'block';
    document.getElementById('becomeExplainerBtn').style.display = 'block';
    document.getElementById('becomeExplainerBtn').style.pointerEvents = 'auto';
});


socket.on('player_kicked', (data) => {
    const playerElement = document.querySelector(`[data-player="${data.player}"]`);
    if (playerElement) playerElement.remove();
});

// ---------- Button handlers (send to server) ----------

document.getElementById('submit_name_btn').onclick = () => {

    const nameError = document.getElementById('name-error');
    nameError.classList.remove('show');

    playerName = document.getElementById('playerName').value.trim();
        if (playerName.length < 1) {
            nameError.textContent = 'Please enter your name';
            nameError.classList.add('show');
            return;
        }
        if (playerName.length > 20) {
            nameError.textContent = 'Name is too long (max 20 characters)';
            nameError.classList.add('show');
            return;
        }


// Room code: ?room=CODE or /game1/game/CODE - NOT the last segment of /game1/game
// (that segment is the word "game", which wrongly triggered "join" and "room not found").
const params = new URLSearchParams(window.location.search);
let roomToJoin = params.get('room');
if (!roomToJoin) {
    const segments = window.location.pathname.split('/').filter((s) => s.length);
    if (segments.length >= 3 && segments[0] === 'game1' && segments[1] === 'game') {
        roomToJoin = segments[2];
    } else if (segments.length >= 2 && segments[0] === 'describe-and-guess') {
        roomToJoin = segments[1];
    }
}

if (roomToJoin) {
    // Room code is in URL → join the existing room
    currentRoomCode = roomToJoin;
    socket.emit('check_room', { room_code: currentRoomCode });

    socket.once('room_exists', (data) => {
        console.log('room_exists:', data); //Debug only
        if (data.exists) {
            socket.emit('join_room', {
                room_code: currentRoomCode,
                name: playerName,
                host_token: hostToken
            });
            document.getElementById('screen-name').style.display = 'none';
            document.getElementById('screen-waiting').style.display = 'flex';
        } else {
            document.getElementById('screen-name').style.display = 'none';
            document.getElementById('screen-error').style.display = 'block';
        }
    });
} else {
    // There's no room code in URl → create a new room
    socket.emit('create_room', { name: playerName });
    document.getElementById('screen-name').style.display = 'none';
    document.getElementById('screen-waiting').style.display = 'flex';
}
};

// Hide error when player starts typing
document.getElementById('playerName').addEventListener('input', () => {
    document.getElementById('name-error').classList.remove('show');
});

document.getElementById('startGame').onclick = () => {
    if (currentRoomCode) {
        socket.emit('start_game', { room_code: currentRoomCode });
    } else {
        alert('No room found');
    }
};

document.getElementById('guessedBtn').onclick = () => {
    const hasCard = inSkippedReplay ? currentIndex < cards.length : currentWord !== null;
    if (!hasCard) return;

    score++;
    socket.emit('score_update', {
        room_code: currentRoomCode,
        increment: 1
    });
    nextCard();
};

document.getElementById('skipBtn').onclick = () => {
    if (inSkippedReplay) {
        if (currentIndex < cards.length) {
            skippedCards.push(cards[currentIndex]);
        }
    } else if (currentWord !== null) {
        skippedCards.push(currentWord);
    } else {
        return;
    }
    nextCard();
};

// Redirect user to the home page when they click the button
document.getElementById('goHomeBtn').onclick = () => { window.location.href = '/'; };

const exitDialog = document.getElementById('exit-dialog');

function showExitDialog() {
    exitDialog.classList.add('is-open');
    exitDialog.setAttribute('aria-hidden', 'false');
}

function hideExitDialog() {
    exitDialog.classList.remove('is-open');
    exitDialog.setAttribute('aria-hidden', 'true');
}

document.getElementById('back-to-main-btn').onclick = showExitDialog;
document.getElementById('new-game-btn').onclick = () => {
    socket.emit('new_game', { room_code: currentRoomCode });
};

document.getElementById('exit-yes-btn').onclick = () => { window.location.href = '/'; };
document.getElementById('exit-no-btn').onclick = hideExitDialog;
document.getElementById('exit-dialog-backdrop').onclick = hideExitDialog;

// Become explainer button
document.getElementById('becomeExplainerBtn').onclick = () => {
    document.querySelector('.explainer-prompt').style.display = 'none';
    socket.emit('become_explainer', {
        room_code: currentRoomCode,
        player_name: playerName
    });
};

// If there are no cards left
// Yes button - shuffle skipped cards and continue
document.getElementById('play-skipped-btn').onclick = () => {
    document.getElementById('skipped-cards-dialog').style.display = 'none';
    cards = shuffleArray([...skippedCards]);
    skippedCards = [];
    currentIndex = 0;
    inSkippedReplay = true;
    allCardsDone = false;
    if (currentRoomCode) {
        socket.emit('resume_timer', { room_code: currentRoomCode });
    }

    document.querySelector('.card-container').style.display = 'flex';
    document.getElementById('cardWord').style.display = 'block';
    showCard(0);
};


// No - finish the game
document.getElementById('finish-round-btn').onclick = () => {
    document.getElementById('skipped-cards-dialog').style.display = 'none';
    endRound();
};

// Theme toggle
const themeToggle = document.getElementById('theme-toggle');
const savedTheme = localStorage.getItem('theme');

if (savedTheme === 'light') {
    document.body.classList.add('light-theme');
}

themeToggle.addEventListener('click', () => {
    document.body.classList.toggle('light-theme');
    const isLight = document.body.classList.contains('light-theme');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    updateCatImage(isLight);
});

function updateCatImage(isLight) {
    // For other index.html and rules.html
    const catImage = document.querySelector('.cat-image');
    if (catImage) {
        catImage.src = isLight ? '/static/common/images/orange_cat_light.png' : '/static/common/images/orange_cat.png';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const isLight = document.body.classList.contains('light-theme');
    updateCatImage(isLight);
});
