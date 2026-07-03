function hideGameScreensForLobby() {
    document.getElementById('screen-name').style.display = 'none';
    document.getElementById('screen-game').style.display = 'none';
    document.getElementById('screen-error').style.display = 'none';
}

function shuffleArray(array) {
    const shuffled = [...array];
    for (let i = shuffled.length - 1; i > 0; i--) {
        const j = Math.floor(Math.random() * (i + 1));
        [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
    }
    return shuffled;
}

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
let hostName = null;
let hostToken = null;
let allCardsDone = false;
let lobbySettings = { word_set: 'easy', explainer: null, suggested_explainer: null };
let playersListCache = [];
let pendingRoomJoin = false;
let pendingLobbyRevealTimer = null;
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

function buildInviteLink() {
    if (!currentRoomCode) return '';
    return `${window.location.origin}/describe-and-guess/${currentRoomCode}`;
}

function updateInviteLinkUI() {
    const input = document.getElementById('invite-link-input');
    if (input) input.value = buildInviteLink();
}

function applyHostName(name) {
    if (name) hostName = name;
}

function applyLobbyData(data) {
    if (!data) return;
    if (data.host_name) applyHostName(data.host_name);
    if (data.settings) applySettingsUI(data.settings);
    if (data.players) updatePlayersList(data.players);
}

function updateLobbyFooterUI() {
    const startBtn = document.getElementById('startGame');
    const waitingMsg = document.getElementById('lobby-waiting-message');
    if (!startBtn || !waitingMsg) return;

    if (isHost) {
        startBtn.style.display = 'block';
        waitingMsg.style.display = 'none';
        waitingMsg.textContent = '';
        return;
    }

    startBtn.style.display = 'none';
    const host = hostName || 'the host';
    waitingMsg.textContent = `Waiting for ${host} to start a new round`;
    waitingMsg.style.display = 'block';
}

function showDngTimerLabel() {
    const label = document.getElementById('guessing-timer-label');
    if (label) label.style.display = 'block';
}

function hideDngTimerLabel() {
    const label = document.getElementById('guessing-timer-label');
    if (label) label.style.display = 'none';
}

function showDngTimerControls() {
    const controls = document.getElementById('dng-timer-controls');
    const onResults = document.getElementById('round-result')?.style.display === 'block';
    const timerVisible = document.getElementById('guessing-timer')?.style.display === 'block';
    if (!controls || onResults || !timerVisible) return;
    controls.style.display = 'flex';
    document.getElementById('pause-timer-btn').style.display = 'inline-flex';
    document.getElementById('resume-timer-btn').style.display = 'none';
}

function hideDngTimerControls() {
    const controls = document.getElementById('dng-timer-controls');
    if (controls) controls.style.display = 'none';
    const pauseBtn = document.getElementById('pause-timer-btn');
    const resumeBtn = document.getElementById('resume-timer-btn');
    if (pauseBtn) pauseBtn.style.display = 'none';
    if (resumeBtn) resumeBtn.style.display = 'none';
}

function updateDngTimerControlsForPause() {
    const controls = document.getElementById('dng-timer-controls');
    if (controls) controls.style.display = 'flex';
    document.getElementById('pause-timer-btn').style.display = 'none';
    document.getElementById('resume-timer-btn').style.display = 'inline-flex';
}

function updateDngRestartRoundButtonVisibility() {
    const btn = document.getElementById('dng-restart-round-btn');
    if (!btn || !currentRoomCode || !playerName || !isHost) {
        if (btn) btn.style.display = 'none';
        return;
    }
    const gameScreen = document.getElementById('screen-game')?.style.display === 'flex';
    const resultScreen = document.getElementById('round-result')?.style.display === 'block';
    const countdownActive = document.getElementById('countdown')?.style.display === 'block';
    btn.style.display = gameScreen && !resultScreen && !countdownActive ? 'inline-flex' : 'none';
}

function showLobbyError(message) {
    const err = document.getElementById('lobby-error');
    if (!err) return;
    err.textContent = message || '';
    err.classList.toggle('show', Boolean(message));
}

function applySettingsUI(settings) {
    if (!settings) return;
    lobbySettings = { ...lobbySettings, ...settings };
    const wordSetEl = document.getElementById('setting-word-set');
    const explainerEl = document.getElementById('setting-explainer');
    if (wordSetEl && settings.word_set) {
        wordSetEl.value = settings.word_set;
    }
    populateExplainerSelect(playersListCache, lobbySettings);
    if (explainerEl && settings.explainer) {
        explainerEl.value = settings.explainer;
    }
    const disabled = !isHost;
    if (wordSetEl) wordSetEl.disabled = disabled;
    if (explainerEl) explainerEl.disabled = disabled;
}

function populateExplainerSelect(players, settings) {
    const select = document.getElementById('setting-explainer');
    if (!select) return;
    select.innerHTML = '';
    players.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
    });
    const preferred = settings?.explainer || settings?.suggested_explainer || players[0] || '';
    if (players.includes(preferred)) {
        select.value = preferred;
    } else if (players.length) {
        select.value = players[0];
    }
}

function readSettingsFromUI() {
    return {
        word_set: document.getElementById('setting-word-set')?.value || 'easy',
        explainer: document.getElementById('setting-explainer')?.value || playersListCache[0] || '',
    };
}

function syncSettingsToServer() {
    if (!isHost || !currentRoomCode) return;
    socket.emit('dng_update_settings', {
        room_code: currentRoomCode,
        ...readSettingsFromUI(),
    });
}

function hideGameScreensForLobby() {
    document.getElementById('screen-name').style.display = 'none';
    document.getElementById('screen-game').style.display = 'none';
    document.getElementById('screen-error').style.display = 'none';
}

function showGameScreen() {
    hideGameScreensForLobby();
    document.getElementById('screen-waiting').style.display = 'none';
    document.getElementById('screen-game').style.display = 'flex';
}

function cancelPendingLobbyReveal() {
    if (pendingLobbyRevealTimer) {
        clearTimeout(pendingLobbyRevealTimer);
        pendingLobbyRevealTimer = null;
    }
}

function finalizePendingJoin() {
    cancelPendingLobbyReveal();
    pendingRoomJoin = false;
}

function schedulePendingLobbyReveal() {
    cancelPendingLobbyReveal();
    pendingLobbyRevealTimer = setTimeout(() => {
        pendingLobbyRevealTimer = null;
        if (!pendingRoomJoin) return;
        finalizePendingJoin();
        openLobbyScreen();
    }, 80);
}

function openLobbyScreen() {
    hideGameScreensForLobby();
    document.getElementById('screen-waiting').style.display = 'flex';
    hideDngTimerControls();
    updateDngRestartRoundButtonVisibility();
    updateInviteLinkUI();
    updateLobbyFooterUI();
    applySettingsUI(lobbySettings);
    showLobbyError('');
    syncDngLobbyScroll();
}

function getRenameOptions() {
    return {
        ownName: playerName,
        onRenameRequest: (newName) => {
            socket.emit('rename_player', {
                room_code: currentRoomCode,
                old_name: playerName,
                new_name: newName,
            });
        },
    };
}

function applyLocalPlayerRename(oldName, newName) {
    if (oldName !== playerName) return;
    playerName = newName;
    const input = document.getElementById('playerName');
    if (input) input.value = newName;
}

function updateExplainerNameDisplay() {
    const el = document.getElementById('explainer-name');
    if (!el || !explainerName) return;
    PlayerNameEdit.setPlayerNameElement(el, explainerName, getRenameOptions());
}

function fillScoreboardTable(scoreboard) {
    const tbody = document.querySelector('#results-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    (scoreboard || []).forEach((row) => {
        const tr = document.createElement('tr');
        tr.appendChild(PlayerNameEdit.createNameTd(row.name, getRenameOptions()));
        const tdScore = document.createElement('td');
        tdScore.textContent = row.display;
        tr.appendChild(tdScore);
        tbody.appendChild(tr);
    });
}

// Update players list in lobby
function updatePlayersList(playersArray) {
    playersListCache = Array.isArray(playersArray) ? playersArray : [];
    const playersList = document.getElementById('players-list');
    if (!playersList) return;
    playersList.innerHTML = '';
    playersListCache.forEach((name) => {
        playersList.appendChild(PlayerNameEdit.createNameLi(name, getRenameOptions()));
    });
    populateExplainerSelect(playersListCache, lobbySettings);
    syncDngLobbyScroll();
}

function syncDngLobbyScroll() {
    const lobbyScreen = document.getElementById('screen-waiting');
    if (!lobbyScreen?.classList.contains('dng-lobby-screen')) return;

    const count = Math.max(playersListCache.length, 1);
    lobbyScreen.style.setProperty('--dng-player-count', String(count));

    const spacerMin = Math.max(0.12, 0.65 - (count - 1) * 0.08);
    lobbyScreen.style.setProperty('--dng-spacer-min', `${spacerMin}rem`);

    const desktop = window.matchMedia('(min-width: 481px)').matches;
    const listMin = count <= 3 ? (desktop ? '8rem' : '5.75rem') : '0px';
    lobbyScreen.style.setProperty('--dng-list-min-height', listMin);

    if (lobbyScreen.style.display !== 'flex') return;

    const list = document.getElementById('players-list');
    if (!list) return;

    list.style.maxHeight = '';
    list.style.overflowY = '';

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            const needsScroll = list.scrollHeight > list.clientHeight + 1;
            lobbyScreen.classList.toggle('dng-lobby-players-scroll', needsScroll);
        });
    });
}


function hideRoundPlayUI() {
    document.querySelector('.card-container').style.display = 'none';
    document.getElementById('cardWord').style.display = 'none';
    document.getElementById('guessedBtn').style.display = 'none';
    document.getElementById('skipBtn').style.display = 'none';
    document.getElementById('message_non-explainers').style.display = 'none';
    hideDngTimerLabel();
    document.getElementById('guessing-timer').style.display = 'none';
    hideDngTimerControls();
}

function showExplainerRoundUI(duration) {
    showDngTimerLabel();
    document.getElementById('guessing-timer').style.display = 'block';
    document.getElementById('guessing-timer').textContent = duration;
    showDngTimerControls();
    document.getElementById('message_non-explainers').style.display = 'none';
    document.getElementById('guessedBtn').style.display = 'inline-block';
    document.getElementById('skipBtn').style.display = 'inline-block';
}

function showGuesserRoundUI(duration) {
    showDngTimerLabel();
    document.getElementById('guessing-timer').style.display = 'block';
    document.getElementById('guessing-timer').textContent = duration;
    showDngTimerControls();
    document.getElementById('message_non-explainers').style.display = 'flex';
    document.querySelector('.card-container').style.display = 'none';
    document.getElementById('guessedBtn').style.display = 'none';
    document.getElementById('skipBtn').style.display = 'none';
}

function revealExplainerCardAfterCountdown() {
    if (currentWord !== null) {
        showCard(currentIndex);
        return;
    }
    requestNextWord(() => showCard(currentIndex));
}

// Show countdown 3-2-1 before revealing the card
function startCountdown(callback) {
    let count = 3;
    const countdownElement = document.getElementById('countdown');
    countdownElement.style.display = 'block';
    countdownElement.textContent = count;
    updateDngRestartRoundButtonVisibility();

    const interval = setInterval(() => {
        count--;
        if (count >= 1) {
            countdownElement.textContent = count;
        } else {
            clearInterval(interval);
            countdownElement.style.display = 'none';
            updateDngRestartRoundButtonVisibility();
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
    updateDngTimerControlsForPause();
}

function endRound() {
    console.log('endRound called. allCardsDone:', allCardsDone, 'explainerName:', explainerName, 'playerName:', playerName);
    hideDngTimerControls();
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
    applyHostName(data.host_name || (isHost ? playerName : null));

    /* --- DEBUG LOGS (uncomment if needed) --- */
    console.log('🔍 is_host received:', data.is_host);
    console.log('📦 full data:', data);
    /* ---------------------------------------- */

    // Add room code to URL
    const newUrl = `${window.location.origin}/describe-and-guess/${currentRoomCode}`;
    window.history.pushState({}, '', newUrl);

    document.getElementById('screen-waiting').style.display = 'flex';
    document.getElementById('screen-name').style.display = 'none';

    applyLobbyData(data);
    updateInviteLinkUI();
    updateLobbyFooterUI();
});


socket.on('player_joined', (data) => {
    console.log('Players in room:', data.players);
    applyLobbyData(data);
    updateInviteLinkUI();
    updateLobbyFooterUI();
    if (pendingRoomJoin && data.player === playerName) {
        schedulePendingLobbyReveal();
        return;
    }
    if (!isHost && document.getElementById('screen-waiting').style.display !== 'flex') {
        openLobbyScreen();
    }
});

socket.on('lobby_state', (data) => {
    applyLobbyData(data);
    updateInviteLinkUI();
    updateLobbyFooterUI();
    if (pendingRoomJoin) {
        finalizePendingJoin();
        openLobbyScreen();
    }
});

socket.on('round_started', (data) => {
    finalizePendingJoin();
    if (data.settings) applySettingsUI(data.settings);
    showGameScreen();
    document.getElementById('round-result').style.display = 'none';
    document.getElementById('score-table').style.display = 'none';
    showLobbyError('');
    hideDngTimerControls();
    updateDngRestartRoundButtonVisibility();

    explainerName = data.explainer;
    updateExplainerNameDisplay();

    document.getElementById('next-round-btn').style.display = 'none';

    // CHECK LATE JOIN FIRST - before showing countdown
    if (data.late_join) {
        // Late joiner - skip countdown, go straight to the round
        // Late joiner is always a guesser for that round
        showGuesserRoundUI(data.duration);
        return;
    }

    hideRoundPlayUI();
    inSkippedReplay = false;
    currentIndex = 0;
    score = 0;
    currentWord = null;

    const isExplainer = data.explainer === playerName;
    if (isExplainer) {
        requestNextWord();
    }

    document.getElementById('countdown').style.display = 'block';
    document.getElementById('countdown').textContent = '3';
    updateDngRestartRoundButtonVisibility();

    startCountdown(() => {
        if (isExplainer) {
            socket.emit('start_timer', { room_code: currentRoomCode });
            showExplainerRoundUI(data.duration);
            revealExplainerCardAfterCountdown();
            return;
        }
        showGuesserRoundUI(data.duration);
    });
});

socket.on('timer_update', (data) => {
    document.getElementById('guessing-timer').textContent = data.time_left;
    const skippedDialog = document.getElementById('skipped-cards-dialog');
    if (skippedDialog.style.display === 'block') {
        document.getElementById('skipped-cards-time-left').textContent =
            `You have ${data.time_left} seconds left.`;
    }
});

socket.on('timer_paused', (data) => {
    if (data?.time_left != null) {
        document.getElementById('guessing-timer').textContent = data.time_left;
    }
    updateDngTimerControlsForPause();
});

socket.on('timer_resumed', (data) => {
    if (data?.time_left != null) {
        document.getElementById('guessing-timer').textContent = data.time_left;
    }
    showDngTimerControls();
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
        finalizePendingJoin();
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
    if (pendingRoomJoin || document.getElementById('screen-waiting').style.display === 'flex') {
        finalizePendingJoin();
        showGameScreen();
    }
    // Hide round UI elements for ALL players
    document.getElementById('guessing-timer').style.display = 'none';
    hideDngTimerLabel();
    hideDngTimerControls();
    updateDngRestartRoundButtonVisibility();
    document.getElementById('skipped-cards-dialog').style.display = 'none';
    score = 0;
    document.getElementById('guessedBtn').style.display = 'none';
    document.getElementById('skipBtn').style.display = 'none';
    document.querySelector('.card-container').style.display = 'none';
    document.getElementById('message_non-explainers').style.display = 'none';
    document.getElementById('countdown').style.display = 'none';
    document.getElementById('becomeExplainerBtn')?.remove();
    document.querySelector('.explainer-prompt')?.remove();

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

    fillScoreboardTable(data.scoreboard);

    document.getElementById('score-table').style.display = 'block';
});

socket.on('player_renamed', (data) => {
    applyLocalPlayerRename(data.old_name, data.new_name);
    if (data.host_name) applyHostName(data.host_name);
    updatePlayersList(data.players);
    updateLobbyFooterUI();
    if (data.explainer) {
        explainerName = data.explainer;
        updateExplainerNameDisplay();
    }
    if (data.last_round) {
        const msg = document.getElementById('result-message');
        if (msg && document.getElementById('round-result').style.display === 'block') {
            const score = data.last_round.score;
            const pointsWord = score !== 1 ? 'points' : 'point';
            msg.textContent =
                `${data.last_round.player} got ${score} ${pointsWord} this round!`;
        }
    }
    if (data.scoreboard && document.getElementById('score-table').style.display === 'block') {
        fillScoreboardTable(data.scoreboard);
    }
});

socket.on('rename_error', (data) => {
    PlayerNameEdit.showRenameError(data.message || 'Could not rename');
});

// Next round button
document.getElementById('next-round-btn').onclick = () => {
    socket.emit('next_round', { room_code: currentRoomCode });
};

socket.on('next_round_ready', (data) => {
    allCardsDone = false;
    document.getElementById('explainer-name').textContent = 'The explainer';
    score = 0;
    currentIndex = 0;
    currentWord = null;
    cards = [];
    skippedCards = [];
    inSkippedReplay = false;

    document.getElementById('round-result').style.display = 'none';
    document.getElementById('score-table').style.display = 'none';
    document.getElementById('next-round-btn').style.display = 'none';
    document.getElementById('new-game-btn').style.display = 'none';
    document.getElementById('back-to-main-btn').style.display = 'none';
    document.getElementById('guessing-timer').style.display = 'none';
    hideDngTimerLabel();
    hideDngTimerControls();
    document.getElementById('waiting-host-message').style.display = 'none';
    document.querySelector('.card-container').style.display = 'none';

    if (data?.settings) applySettingsUI(data.settings);
    if (data?.players) updatePlayersList(data.players);
    if (data?.host_name) applyHostName(data.host_name);
    openLobbyScreen();
});

socket.on('new_game_ready', (data) => {
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

    if (data?.settings) applySettingsUI(data.settings);
    if (data?.players) updatePlayersList(data.players);
    if (data?.host_name) applyHostName(data.host_name);
    openLobbyScreen();
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
        if (playerName.length > PlayerNameEdit.MAX_LEN) {
            nameError.textContent = `Name is too long (max ${PlayerNameEdit.MAX_LEN} characters)`;
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
            pendingRoomJoin = true;
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
    if (!currentRoomCode) {
        showLobbyError('No room found');
        return;
    }
    if (!isHost) return;
    if (playersListCache.length < 1) {
        showLobbyError('Need at least one player to start.');
        return;
    }
    showLobbyError('');
    const settings = readSettingsFromUI();
    socket.emit('start_game', {
        room_code: currentRoomCode,
        ...settings,
    });
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

['setting-word-set', 'setting-explainer'].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('change', () => {
        if (!isHost) return;
        syncSettingsToServer();
    });
});

document.getElementById('copy-invite-btn')?.addEventListener('click', async () => {
    const link = buildInviteLink();
    const btn = document.getElementById('copy-invite-btn');
    const status = document.getElementById('copy-invite-status');
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(link);
        } else {
            const input = document.getElementById('invite-link-input');
            input.select();
            document.execCommand('copy');
        }
        btn?.classList.add('copied');
        if (status) {
            status.textContent = 'Link copied!';
            status.classList.add('show');
        }
        setTimeout(() => {
            btn?.classList.remove('copied');
            if (status) {
                status.textContent = '';
                status.classList.remove('show');
            }
        }, 2000);
    } catch (e) {
        if (status) {
            status.textContent = 'Could not copy';
            status.classList.add('show');
        }
    }
});

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

document.getElementById('pause-timer-btn')?.addEventListener('click', () => {
    if (!currentRoomCode) return;
    const timeLeft = parseInt(document.getElementById('guessing-timer').textContent, 10);
    if (Number.isNaN(timeLeft)) return;
    socket.emit('pause_timer', {
        room_code: currentRoomCode,
        time_left: timeLeft,
    });
});

document.getElementById('resume-timer-btn')?.addEventListener('click', () => {
    if (!currentRoomCode) return;
    socket.emit('resume_timer', { room_code: currentRoomCode });
});

const dngRestartRoundDialog = document.getElementById('dng-restart-round-dialog');

function showDngRestartRoundDialog() {
    if (!dngRestartRoundDialog) return;
    dngRestartRoundDialog.classList.add('is-open');
    dngRestartRoundDialog.setAttribute('aria-hidden', 'false');
}

function hideDngRestartRoundDialog() {
    if (!dngRestartRoundDialog) return;
    dngRestartRoundDialog.classList.remove('is-open');
    dngRestartRoundDialog.setAttribute('aria-hidden', 'true');
}

document.getElementById('dng-restart-round-btn')?.addEventListener('click', () => {
    showDngRestartRoundDialog();
});

document.getElementById('dng-restart-round-cancel-btn')?.addEventListener('click', hideDngRestartRoundDialog);
document.getElementById('dng-restart-round-dialog-backdrop')?.addEventListener('click', hideDngRestartRoundDialog);
document.getElementById('dng-restart-round-confirm-btn')?.addEventListener('click', () => {
    hideDngRestartRoundDialog();
    if (!currentRoomCode) return;
    socket.emit('dng_restart_round', { room_code: currentRoomCode });
});

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
    const catImage = document.querySelector('.cat-image');
    if (catImage) {
        catImage.src = isLight ? '/static/common/images/orange_cat_light.png' : '/static/common/images/orange_cat.png';
    }
    document.querySelectorAll('.lobby-cat').forEach((lobbyCat) => {
        lobbyCat.src = isLight
            ? '/static/common/images/orange_cat_light.png'
            : '/static/common/images/orange_cat_waiting.png';
    });
}

document.addEventListener('DOMContentLoaded', () => {
    const isLight = document.body.classList.contains('light-theme');
    updateCatImage(isLight);
});

window.addEventListener('resize', syncDngLobbyScroll);
