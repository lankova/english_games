const socket = io();

// Re-attach sid after reconnect so mid-game events still reach this client.
socket.on('connect', syncPlayerSession);

let currentRoomCode = null;
let playerName = null;
let myRole = null;
let gameSettings = { location_set: 'modern_world' };
let locationsData = null;
let playersListCache = [];
let roomHostName = null;
let lobbyKickMode = false;
let localMarkedLocations = new Set();
let localCrossedPlayers = new Set();

let myVoteSubmitted = false;
let currentVoteAccused = null;
let currentVoteInitiator = null;
let myRoleReadySubmitted = false;
let spyGuessActive = false;
let guessSpyName = null;
let guessSubmitted = false;
let roundInterruptActive = false;
let sessionRestorePending = false;

function completeSessionRestore() {
    sessionRestorePending = false;
}

function completeSessionRestoreIfPending() {
    if (sessionRestorePending) {
        completeSessionRestore();
    }
}

const PLAYER_SESSION_KEY = 'spy_in_ithaca_player_session';

function savePlayerSession() {
    if (!currentRoomCode || !playerName) return;
    sessionStorage.setItem(PLAYER_SESSION_KEY, JSON.stringify({
        roomCode: currentRoomCode,
        playerName,
    }));
}

function loadPlayerSession(roomCode) {
    try {
        const raw = sessionStorage.getItem(PLAYER_SESSION_KEY);
        if (!raw) return null;
        const data = JSON.parse(raw);
        if (data.roomCode === roomCode && data.playerName) {
            return data.playerName;
        }
    } catch (_) {
        // ignore invalid sessionStorage payload
    }
    return null;
}

function clearPlayerSession() {
    sessionStorage.removeItem(PLAYER_SESSION_KEY);
}

function restorePlayerSessionFromUrl() {
    const roomCode = getRoomFromUrl();
    if (!roomCode) return;
    currentRoomCode = roomCode;
    const savedName = loadPlayerSession(roomCode);
    if (!savedName) return;
    playerName = savedName;
    sessionRestorePending = true;
    const input = document.getElementById('playerName');
    if (input) input.value = savedName;
}

// Server uses player_name to resolve sid after refresh or reconnect.
function emitWithPlayer(event, payload = {}) {
    if (!currentRoomCode) return;
    socket.emit(event, {
        room_code: currentRoomCode,
        player_name: playerName,
        ...payload,
    });
}

function syncPlayerSession() {
    if (!currentRoomCode || !playerName) return;
    if (sessionRestorePending) {
        socket.emit('spy_join_room', {
            room_code: currentRoomCode,
            name: playerName,
        });
        return;
    }
    socket.emit('spy_sync_session', {
        room_code: currentRoomCode,
        player_name: playerName,
    });
}

function formatTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
}

// Room code: /spy-in-ithaca/CODE or ?room=CODE (not /game or /rules).
const SPY_RESERVED_PATH_SEGMENTS = ['game', 'rules'];

function getRoomFromUrl() {
    const params = new URLSearchParams(window.location.search);
    let code = params.get('room');
    if (!code) {
        const segments = window.location.pathname.split('/').filter(Boolean);
        if (
            segments[0] === 'spy-in-ithaca' &&
            segments[1] &&
            SPY_RESERVED_PATH_SEGMENTS.indexOf(segments[1].toLowerCase()) === -1
        ) {
            code = segments[1];
        }
    }
    return code;
}

function buildInviteLink() {
    if (!currentRoomCode) return '';
    return `${window.location.origin}/spy-in-ithaca/${currentRoomCode}`;
}

function updateInviteLinkUI() {
    const input = document.getElementById('invite-link-input');
    if (input) input.value = buildInviteLink();
}

function hideAllScreens() {
    document.getElementById('screen-name').style.display = 'none';
    document.getElementById('screen-waiting').style.display = 'none';
    document.getElementById('screen-role').style.display = 'none';
    document.getElementById('screen-locations').style.display = 'none';
    document.getElementById('screen-error').style.display = 'none';
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


function isRoomHost() {
    if (roomHostName && playerName && roomHostName === playerName) return true;
    if (playerName && playersListCache.length > 0 && playersListCache[0] === playerName) {
        return true;
    }
    return false;
}

function isBotPlayer(name) {
    return name === 'bot 1' || name === 'bot 2';
}

function applyRoomHostName(hostName) {
    if (hostName) {
        roomHostName = hostName;
        return;
    }
    if (playerName && playersListCache.length > 0 && playersListCache[0] === playerName) {
        roomHostName = playerName;
    }
}

let lobbyMinPlayersPromptTimer = null;
const LOBBY_MIN_PLAYERS_PROMPT_MS = 15000;

function clearLobbyMinPlayersPrompt() {
    if (lobbyMinPlayersPromptTimer) {
        clearTimeout(lobbyMinPlayersPromptTimer);
        lobbyMinPlayersPromptTimer = null;
    }
    const startBtn = document.getElementById('startGame');
    const botsBtn = document.getElementById('startWithBots');
    if (startBtn) startBtn.hidden = false;
    if (botsBtn) {
        botsBtn.hidden = true;
        botsBtn.classList.remove('spy-start-bots-btn--active');
    }
}

function showLobbyMinPlayersPrompt() {
    clearLobbyMinPlayersPrompt();
    showLobbyError('Need at least 3 players.');

    const startBtn = document.getElementById('startGame');
    const botsBtn = document.getElementById('startWithBots');
    if (isRoomHost() && startBtn && botsBtn) {
        startBtn.hidden = true;
        botsBtn.hidden = false;
        botsBtn.classList.add('spy-start-bots-btn--active');
    }

    lobbyMinPlayersPromptTimer = setTimeout(() => {
        lobbyMinPlayersPromptTimer = null;
        showLobbyError('');
        clearLobbyMinPlayersPrompt();
    }, LOBBY_MIN_PLAYERS_PROMPT_MS);
}

function setLobbyKickMode(enabled) {
    lobbyKickMode = Boolean(enabled);
    const panel = document.querySelector('#screen-waiting .lobby-players-panel');
    if (panel) panel.classList.toggle('lobby-kick-mode', lobbyKickMode);
    renderWaitingPlayers(playersListCache);
}

function toggleLobbyKickMode() {
    if (!isRoomHost()) return;
    setLobbyKickMode(!lobbyKickMode);
}

function createKickButton(name) {
    const kickBtn = document.createElement('button');
    kickBtn.type = 'button';
    kickBtn.className = 'player-kick-btn';
    kickBtn.setAttribute('aria-label', `Remove ${name}`);
    kickBtn.textContent = '\u00d7';
    kickBtn.addEventListener('click', (event) => {
        event.stopPropagation();
        emitWithPlayer('spy_kick_player', { target_name: name });
    });
    return kickBtn;
}

function getRenameOptions() {
    return {
        ownName: playerName,
        onRenameRequest: (newName) => {
            emitWithPlayer('spy_rename_player', { new_name: newName });
        },
    };
}

function applyLocalPlayerRename(oldName, newName) {
    if (oldName !== playerName) return;
    playerName = newName;
    if (roomHostName === oldName) roomHostName = newName;
    savePlayerSession();
    const input = document.getElementById('playerName');
    if (input) input.value = newName;
}

function refreshNameDependentUI(data) {
    if (data.vote_initiator != null) currentVoteInitiator = data.vote_initiator;
    if (data.vote_accused != null) currentVoteAccused = data.vote_accused;
    if (data.guess_spy != null) guessSpyName = data.guess_spy;

    if (data.role_ready) {
        updateRoleWaitingMessage(data.role_ready);
    }

    const votePanel = document.getElementById('vote-panel');
    if (votePanel && votePanel.style.display !== 'none' && currentVoteAccused) {
        updateVoteButtonLabels(currentVoteAccused, currentVoteInitiator);
    }

    const finalPanel = document.getElementById('final-vote-panel');
    if (finalPanel && finalPanel.style.display !== 'none') {
        const votes = data.final_votes || {};
        const myVote = playerName ? votes[playerName] : null;
        populateFinalVoteSelect(data.players || playersListCache, myVote);
        updateFinalVoteStatus({
            votes,
            ballots_count: Object.keys(votes).length,
            players_count: (data.players || playersListCache).length,
        });
    }

    const roundResult = document.getElementById('round-result');
    if (roundResult && roundResult.style.display === 'block' && data.last_result) {
        const resultView = getRoundResultView({
            result: data.last_result,
            secret_location: data.secret_location || '',
        });
        document.getElementById('result-message').textContent = resultView.message;
    }

    const nomPanel = document.getElementById('vote-nominate-panel');
    if (nomPanel && nomPanel.style.display !== 'none' && currentVoteInitiator) {
        showNominationPanel(currentVoteInitiator);
    }

    const guessPanel = document.getElementById('spy-guess-panel');
    if (guessPanel && guessPanel.style.display !== 'none' && guessSpyName) {
        showSpyGuessPanel(guessSpyName);
    }

    if (data.scoreboard && document.getElementById('score-table').style.display === 'block') {
        fillScoreboardTable(data.scoreboard);
    }
}

function renderWaitingPlayers(names) {
    const ul = document.getElementById('players-list');
    if (!ul) return;
    ul.innerHTML = '';
    const showKick = lobbyKickMode && isRoomHost();
    names.forEach((name) => {
        const li = PlayerNameEdit.createNameLi(name, getRenameOptions());
        if (showKick && name !== playerName) {
            li.classList.add('player-list-item-kickable');
            li.insertBefore(createKickButton(name), li.firstChild);
        }
        ul.appendChild(li);
    });
}

function renderGamePlayers(names) {
    const wrap = document.getElementById('players-wrap-game');
    if (!wrap) return;
    wrap.innerHTML = '';
    names.forEach((name) => {
        const pill = document.createElement('div');
        pill.className = 'player-pill';
        pill.textContent = name;
        if (localCrossedPlayers.has(name)) {
            pill.classList.add('is-crossed');
        }
        pill.addEventListener('click', () => {
            if (localCrossedPlayers.has(name)) {
                localCrossedPlayers.delete(name);
                pill.classList.remove('is-crossed');
            } else {
                localCrossedPlayers.add(name);
                pill.classList.add('is-crossed');
            }
        });
        wrap.appendChild(pill);
    });
}

function updatePlayersEverywhere(names) {
    playersListCache = Array.isArray(names) ? names : [];
    applyRoomHostName(null);
    renderWaitingPlayers(playersListCache);
    renderGamePlayers(playersListCache);
    populateVoteNominateSelect(playersListCache);
    syncSpyLobbyScroll();
}

function syncSpyLobbyScroll() {
    const lobby = document.getElementById('screen-waiting');
    if (!lobby || lobby.classList.contains('dng-lobby-screen')) return;
    if (lobby.style.display !== 'flex') return;

    const list = document.getElementById('players-list');
    if (list) {
        list.style.maxHeight = '';
        list.style.overflowY = '';
    }
    lobby.classList.remove('spy-lobby-players-scroll');

    requestAnimationFrame(() => {
        requestAnimationFrame(() => {
            const body = lobby.querySelector('.spy-lobby-body');
            if (!body) return;
            lobby.classList.toggle(
                'spy-lobby-scroll',
                body.scrollHeight > body.clientHeight + 1,
            );
        });
    });
}

function applySetupUIFromSettings() {
    const s = gameSettings || {};
    const spyEl = document.getElementById('setting-spy-count');
    const extraEl = document.getElementById('setting-extra-roles');
    const durationEl = document.getElementById('setting-duration');
    const setEl = document.getElementById('setting-location-set');

    if (spyEl && s.spy_count != null) spyEl.value = String(s.spy_count);
    if (extraEl) extraEl.checked = Boolean(s.extra_roles);
    if (durationEl) {
        const minutes = Math.round((s.round_duration_sec || 9 * 60) / 60);
        durationEl.value = String(minutes);
    }
    if (setEl && s.location_set) setEl.value = s.location_set;
    syncAllSpyStepperLabels();
}

const SPY_SETTING_STEPPER_IDS = [
    'setting-spy-count',
    'setting-duration',
    'setting-location-set',
];

function syncSpyStepperLabel(selectId) {
    const select = document.getElementById(selectId);
    const stepper = document.querySelector(`.spy-setting-stepper[data-for="${selectId}"]`);
    if (!select || !stepper) return;
    const label = stepper.querySelector('.spy-stepper-label');
    if (label) {
        label.textContent = select.options[select.selectedIndex]?.text || '';
    }
}

function syncAllSpyStepperLabels() {
    SPY_SETTING_STEPPER_IDS.forEach(syncSpyStepperLabel);
}

function stepSpySetting(selectId, delta) {
    const select = document.getElementById(selectId);
    if (!select || select.options.length === 0) return;
    const nextIndex = (select.selectedIndex + delta + select.options.length) % select.options.length;
    select.selectedIndex = nextIndex;
    syncSpyStepperLabel(selectId);
    select.dispatchEvent(new Event('change', { bubbles: true }));
}

function initSpySettingSteppers() {
    SPY_SETTING_STEPPER_IDS.forEach((selectId) => {
        syncSpyStepperLabel(selectId);
        const stepper = document.querySelector(`.spy-setting-stepper[data-for="${selectId}"]`);
        if (!stepper) return;
        stepper.querySelector('.spy-stepper-prev')?.addEventListener('click', (event) => {
            event.preventDefault();
            stepSpySetting(selectId, -1);
        });
        stepper.querySelector('.spy-stepper-next')?.addEventListener('click', (event) => {
            event.preventDefault();
            stepSpySetting(selectId, 1);
        });
    });
}

function showLobbyError(message) {
    const err = document.getElementById('lobby-error');
    if (!err) return;
    if (message) {
        err.textContent = message;
        err.classList.add('show');
    } else {
        err.textContent = '';
        err.classList.remove('show');
    }
}

function openLobbyScreen() {
    hideAllScreens();
    applySetupUIFromSettings();
    clearLobbyMinPlayersPrompt();
    showLobbyError('');
    setLobbyKickMode(false);
    document.getElementById('screen-waiting').style.display = 'flex';
    updateNewRoundButtonVisibility();
    completeSessionRestoreIfPending();
    syncSpyLobbyScroll();
}

function syncRestartRoundButtonWidth() {
    const voteBtn = document.getElementById('vote-btn');
    const restartBtn = document.getElementById('new-round-btn');
    const playScreen = document.getElementById('screen-locations');
    const mainCard = document.querySelector('.main-card');
    if (!voteBtn || !restartBtn || !mainCard) return;

    const showOnPlay = restartBtn.classList.contains('spy-new-round-btn--play')
        && playScreen
        && playScreen.style.display === 'flex';

    if (!showOnPlay) {
        restartBtn.style.marginLeft = '';
        restartBtn.style.alignSelf = '';
        restartBtn.style.width = '';
        return;
    }

    requestAnimationFrame(() => {
        restartBtn.style.width = 'auto';
        const voteRect = voteBtn.getBoundingClientRect();
        const restartRect = restartBtn.getBoundingClientRect();
        const cardRect = mainCard.getBoundingClientRect();
        const voteCenter = voteRect.left + (voteRect.width / 2);
        const restartLeft = voteCenter - (restartRect.width / 2);
        restartBtn.style.marginLeft = `${Math.max(0, restartLeft - cardRect.left)}px`;
        restartBtn.style.alignSelf = 'flex-start';
    });
}

function updateNewRoundButtonVisibility() {
    const btn = document.getElementById('new-round-btn');
    if (!btn || !currentRoomCode || !playerName) {
        if (btn) btn.style.display = 'none';
        return;
    }
    const roleScreen = document.getElementById('screen-role').style.display === 'flex';
    const playScreen = document.getElementById('screen-locations').style.display === 'flex';
    const resultScreen = document.getElementById('round-result').style.display === 'block';
    const showOnPlay = playScreen && !resultScreen;
    btn.style.display = (roleScreen || showOnPlay) ? 'inline-block' : 'none';
    btn.classList.toggle('spy-new-round-btn--play', showOnPlay);
    syncRestartRoundButtonWidth();
}

function resetClientRoundState() {
    myRole = null;
    localMarkedLocations = new Set();
    localCrossedPlayers = new Set();
    myVoteSubmitted = false;
    currentVoteAccused = null;
    currentVoteInitiator = null;
    myRoleReadySubmitted = false;
    spyGuessActive = false;
    guessSpyName = null;
    guessSubmitted = false;
    roundInterruptActive = false;
    document.getElementById('next-round-btn').style.display = 'none';
    document.getElementById('back-to-main-btn').style.display = 'none';
    document.getElementById('round-result').style.display = 'none';
    document.getElementById('score-table').style.display = 'none';
}

function collectSettingsPayload() {
    const durationEl = document.getElementById('setting-duration');
    let minutes = parseInt(durationEl.value, 10);
    if (Number.isNaN(minutes)) minutes = 9;

    return {
        spy_count: parseInt(document.getElementById('setting-spy-count').value, 10),
        extra_roles: document.getElementById('setting-extra-roles').checked,
        round_duration_sec: minutes,
        location_set: document.getElementById('setting-location-set').value,
    };
}

function populateVoteNominateSelect(players) {
    const select = document.getElementById('vote-nominate-select');
    if (!select) return;

    const others = (players || []).filter((n) => n !== playerName);
    const prev = select.value;
    select.innerHTML = '';
    others.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
    });
    if (prev && others.includes(prev)) {
        select.value = prev;
    }
}

function getSpyCountSetting() {
    const fromSettings = parseInt(gameSettings?.spy_count, 10);
    return Number.isNaN(fromSettings) ? 1 : fromSettings;
}

function getMinPlayersToStart() {
    const setting = getSpyCountSetting();
    return (setting === 0 || setting === 2) ? 4 : 3;
}

function getSpyCount() {
    const setting = getSpyCountSetting();
    if (setting === 0) return 0;
    return setting;
}

function getSpyPhrase(spyCount) {
    // Random mode (spy_count 0) never reveals whether there is one spy or two.
    const setting = getSpyCountSetting();
    if (setting === 0) return 'is a spy';
    const count = spyCount != null ? spyCount : setting;
    if (count === 0 || count > 1) return 'is a spy';
    return 'is the spy';
}

function updateVoteButtonLabels(accused, initiator, spyCount) {
    const suspect = accused || currentVoteAccused || '…';
    const voter = initiator || currentVoteInitiator || '…';
    const count = spyCount ?? getSpyCount();
    const phrase = getSpyPhrase(count);

    document.getElementById('vote-accused-name').textContent = suspect;
    document.getElementById('vote-context-line').textContent =
        `${voter} wants to vote against ${suspect}.`;
    const phraseEl = document.getElementById('vote-spy-phrase');
    if (phraseEl) phraseEl.textContent = phrase;
    document.getElementById('vote-yes-btn').textContent = `Yes, ${suspect} ${phrase}`;
}

function ensurePlayingScreenVisible() {
    hideAllScreens();
    document.getElementById('screen-locations').style.display = 'flex';
    const gameUi = document.querySelector('.spy-play-game-ui');
    if (gameUi) gameUi.style.display = 'flex';
}

function updateSpyGuessButtonVisibility() {
    const btn = document.getElementById('spy-guess-btn');
    const actions = document.getElementById('playing-actions');
    if (!btn) return;
    const show = myRole && myRole.is_spy && !roundInterruptActive;
    btn.style.display = show ? 'inline-block' : 'none';
    if (actions) {
        actions.classList.toggle('spy-round-actions--spy', Boolean(show));
    }
}

function showGameBanner(message, durationMs = 5000) {
    const banner = document.getElementById('vote-cancel-banner');
    if (!banner) return;
    banner.textContent = message;
    banner.style.display = 'block';
    setTimeout(() => {
        banner.style.display = 'none';
    }, durationMs);
}

function updateNominateButtonState() {
    const btn = document.getElementById('vote-nominate-btn');
    if (!btn) return;
    const isInitiator = playerName && currentVoteInitiator === playerName;
    btn.disabled = !isInitiator;
}

function updateTimerControlsForPause() {
    document.getElementById('pause-timer-btn').style.display = 'none';
    document.getElementById('resume-timer-btn').style.display = roundInterruptActive
        ? 'none'
        : 'inline-flex';
}

// Vote and spy-guess pause normal play; timer stays frozen until resolved or cancelled.
function hideAllInterruptPanels() {
    document.getElementById('vote-panel').style.display = 'none';
    document.getElementById('vote-nominate-panel').style.display = 'none';
    document.getElementById('final-vote-panel').style.display = 'none';
    document.getElementById('spy-guess-panel').style.display = 'none';
    document.getElementById('spy-guess-wait-view').style.display = 'none';
    document.getElementById('spy-guess-prompt-view').style.display = 'none';
}

function updateLocationsCaptions() {
    const spyCaption = document.getElementById('spy-locations-caption');
    const civilianCaption = document.getElementById('civilian-locations-caption');
    const scrollHidden = document.querySelector('.spy-play-scroll')?.style.display === 'none';
    const showBase = Boolean(myRole && !roundInterruptActive && !scrollHidden);

    if (spyCaption) {
        spyCaption.style.display = showBase && myRole.is_spy ? 'block' : 'none';
    }
    if (civilianCaption) {
        civilianCaption.style.display = showBase && !myRole.is_spy ? 'block' : 'none';
    }
}

function enterRoundInterruptMode() {
    roundInterruptActive = true;
    hideAllInterruptPanels();
    document.getElementById('playing-actions').style.display = 'none';
    document.getElementById('questions-block').style.display = 'none';
    document.getElementById('vote-cancel-banner').style.display = 'none';
    document.getElementById('pause-timer-btn').style.display = 'none';
    document.getElementById('resume-timer-btn').style.display = 'none';
    updateLocationsCaptions();
}

function exitRoundInterruptMode() {
    roundInterruptActive = false;
    spyGuessActive = false;
    guessSpyName = null;
    guessSubmitted = false;
    hideAllInterruptPanels();
    const locationsScroll = document.querySelector('.spy-play-scroll');
    if (locationsScroll) locationsScroll.style.display = '';
    document.getElementById('playing-actions').style.display = 'flex';
    document.getElementById('vote-btn').style.display = 'inline-block';
    document.getElementById('questions-block').style.display = 'block';
    applyRoleToLocationsScreen();
    document.getElementById('pause-timer-btn').style.display = 'inline-flex';
    document.getElementById('resume-timer-btn').style.display = 'none';
    updateSpyGuessButtonVisibility();
    updateLocationsCaptions();
    syncRestartRoundButtonWidth();
    renderLocationsGrid();
}

function showSpyGuessPanel(spyName) {
    ensurePlayingScreenVisible();
    spyGuessActive = true;
    guessSpyName = spyName;
    guessSubmitted = false;
    currentVoteAccused = null;
    currentVoteInitiator = null;
    enterRoundInterruptMode();

    document.getElementById('spy-guess-panel').style.display = 'block';
    document.getElementById('spy-play-interrupt-zone').style.display = 'block';

    const isSpy = myRole && myRole.is_spy;
    document.getElementById('spy-guess-wait-view').style.display = isSpy ? 'none' : 'block';
    document.getElementById('spy-guess-prompt-view').style.display = isSpy ? 'block' : 'none';
    document.getElementById('spy-guess-spy-name').textContent = spyName;
    document.getElementById('spy-guess-spy-name-2').textContent = spyName;
    updateSpyGuessButtonVisibility();
    renderLocationsGrid();
}

function hideNominationPanel() {
    document.getElementById('vote-nominate-panel').style.display = 'none';
}

function showNominationPanel(initiator) {
    if (!initiator) return;
    ensurePlayingScreenVisible();
    currentVoteAccused = null;
    currentVoteInitiator = initiator;
    myVoteSubmitted = false;
    spyGuessActive = false;
    enterRoundInterruptMode();
    document.getElementById('vote-nominate-panel').style.display = 'block';
    document.getElementById('spy-play-interrupt-zone').style.display = 'block';
    const isInitiator = playerName && initiator === playerName;
    document.getElementById('vote-nominate-status').textContent = isInitiator
        ? "Let's vote"
        : `${initiator} is choosing a player`;
    const initiatorView = document.getElementById('vote-nominate-initiator-view');
    initiatorView.style.display = isInitiator ? 'flex' : 'none';
    if (isInitiator) {
        populateVoteNominateSelect(playersListCache);
    }
    updateNominateButtonState();
}

function showVotePanel(accused, initiator, spyCount) {
    ensurePlayingScreenVisible();
    currentVoteAccused = accused || currentVoteAccused;
    if (initiator !== undefined) {
        currentVoteInitiator = initiator;
    }
    const resolvedSpyCount = spyCount ?? getSpyCount();
    if (spyCount != null) {
        gameSettings = { ...gameSettings, spy_count: spyCount };
    }
    spyGuessActive = false;
    enterRoundInterruptMode();

    const isAccused = playerName && currentVoteAccused === playerName;
    const isInitiator = playerName && currentVoteInitiator === playerName;
    const canVote = !isAccused && !isInitiator;
    myVoteSubmitted = isInitiator;

    updateVoteButtonLabels(currentVoteAccused, currentVoteInitiator, resolvedSpyCount);

    const panel = document.getElementById('vote-panel');
    panel.style.display = 'block';
    document.getElementById('spy-play-interrupt-zone').style.display = 'block';
    panel.classList.remove('vote-panel-voted');
    panel.classList.toggle('vote-panel-voted', isInitiator);

    document.getElementById('vote-context-line').style.display =
        isInitiator ? 'none' : 'block';
    document.getElementById('vote-question-line').style.display =
        canVote ? 'block' : 'none';
    document.getElementById('vote-voter-view').style.display = canVote ? 'block' : 'none';
    document.getElementById('vote-accused-view').style.display = isAccused ? 'block' : 'none';
    document.getElementById('vote-initiator-view').style.display = isInitiator ? 'block' : 'none';
    document.getElementById('vote-status').textContent = '';
    updateSpyGuessButtonVisibility();
}

function hideVotePanel() {
    currentVoteAccused = null;
    currentVoteInitiator = null;
    myVoteSubmitted = false;
    exitRoundInterruptMode();
}

function populateFinalVoteSelect(players, selectedTarget) {
    const select = document.getElementById('final-vote-select');
    if (!select) return;

    const others = (players || []).filter((n) => n !== playerName);
    select.innerHTML = '';
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = 'Choose a player…';
    placeholder.disabled = true;
    placeholder.selected = !selectedTarget;
    select.appendChild(placeholder);

    others.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
    });

    if (selectedTarget && others.includes(selectedTarget)) {
        select.value = selectedTarget;
        placeholder.selected = false;
    }
}

function updateFinalVoteStatus(data) {
    const status = document.getElementById('final-vote-status');
    if (!status) return;

    const total = data.players_count || playersListCache.length;
    const count = data.ballots_count ?? Object.keys(data.votes || {}).length;
    const myVote = (data.votes && playerName && data.votes[playerName])
        || document.getElementById('final-vote-select')?.value
        || '';

    if (myVote) {
        status.textContent =
            `You voted for ${myVote}. ${count} of ${total} players have voted. `
            + 'You can change your vote until everyone has voted.';
        return;
    }

    status.textContent = `${count} of ${total} players have voted.`;
}

function showFinalVotePanel(data) {
    completeSessionRestore();
    ensurePlayingScreenVisible();
    enterRoundInterruptMode();
    document.getElementById('round-timer').textContent = '0:00';
    document.getElementById('final-vote-panel').style.display = 'block';
    document.getElementById('spy-play-interrupt-zone').style.display = 'block';

    const locationsScroll = document.querySelector('.spy-play-scroll');
    if (locationsScroll) locationsScroll.style.display = 'none';
    document.getElementById('spy-round-info').style.display = 'none';

    const votes = data.votes || {};
    const myVote = playerName ? votes[playerName] : null;
    populateFinalVoteSelect(data.players || playersListCache, myVote);
    updateFinalVoteStatus({
        votes,
        ballots_count: data.ballots_count,
        players_count: data.players_count,
    });
}

function markVoteSubmitted(message) {
    myVoteSubmitted = true;
    document.getElementById('vote-panel').classList.add('vote-panel-voted');
    document.getElementById('vote-status').textContent = message;
}

function emitSettingsUpdate() {
    if (!currentRoomCode) return;
    socket.emit('spy_update_settings', {
        room_code: currentRoomCode,
        ...collectSettingsPayload(),
    });
}

// ---------- Load locations from API ----------
async function loadLocationsJson() {
    if (locationsData) return locationsData;
    const res = await fetch('/api/spy-in-ithaca/locations');
    const data = await res.json();
    locationsData = { sets: data };

    return locationsData;
}

function getLocationsForSet(setKey) {
    const sets = locationsData.sets || {};
    return (sets[setKey] && sets[setKey].locations) ? sets[setKey].locations : [];
}

function renderLocationsGrid() {
    const grid = document.getElementById('locations-grid');
    if (!grid || !locationsData) return;

    const setKey = gameSettings.location_set || 'modern_world';
    const locations = getLocationsForSet(setKey);

    grid.innerHTML = '';
    locations.forEach((loc) => {
        const card = document.createElement('div');
        card.className = 'location-card';
        if (localMarkedLocations.has(loc.name)) {
            card.classList.add('is-marked');
        }

        const label = document.createElement('div');
        label.className = 'location-card-label';
        label.textContent = loc.name;

        const mark = document.createElement('div');
        mark.className = 'location-card-mark';
        mark.textContent = '✕';
        mark.setAttribute('aria-hidden', 'true');

        card.appendChild(label);
        card.appendChild(mark);

        if (spyGuessActive && myRole && myRole.is_spy) {
            card.classList.add('location-card-guessable');
        }

        card.addEventListener('click', () => {
            if (spyGuessActive && myRole && myRole.is_spy) {
                if (guessSubmitted || !currentRoomCode) return;
                guessSubmitted = true;
                emitWithPlayer('spy_submit_guess', { location: loc.name });
                return;
            }
            // Local marks only - other players never see these.
            if (localMarkedLocations.has(loc.name)) {
                localMarkedLocations.delete(loc.name);
                card.classList.remove('is-marked');
            } else {
                localMarkedLocations.add(loc.name);
                card.classList.add('is-marked');
            }
        });

        grid.appendChild(card);
    });
    syncRestartRoundButtonWidth();
}

function showQuestionIdea(question) {
    const block = document.getElementById('questions-block');
    if (!block || !question) return;
    block.textContent = `Question idea: ${question}`;
}

function getRoundDurationMinutes(payload) {
    const sec = payload?.round_duration_sec
        ?? gameSettings?.round_duration_sec
        ?? 9 * 60;
    return Math.round(sec / 60);
}

function resetRoleReadyUI() {
    myRoleReadySubmitted = false;
    const btn = document.getElementById('role-continue-btn');
    btn.disabled = false;
    btn.textContent = 'OK';
    const msg = document.getElementById('role-waiting-message');
    msg.textContent = '';
    msg.style.display = 'none';
}

function updateRoleWaitingMessage(data) {
    const msg = document.getElementById('role-waiting-message');
    const btn = document.getElementById('role-continue-btn');

    if (data.ready && playerName && data.ready.includes(playerName)) {
        myRoleReadySubmitted = true;
        if (btn) btn.disabled = true;
    }

    if (data.waiting_for) {
        msg.textContent = `Waiting for ${data.waiting_for} to click OK`;
        msg.style.display = 'block';
        return;
    }

    if (myRoleReadySubmitted) {
        msg.textContent = 'Waiting for other players...';
        msg.style.display = 'block';
        return;
    }

    msg.textContent = '';
    msg.style.display = 'none';
}

function showRoleScreen(rolePayload) {
    myRole = rolePayload;
    resetRoleReadyUI();

    if (rolePayload.is_spy) {
        document.getElementById('role-spy').style.display = 'block';
        document.getElementById('role-civilian').style.display = 'none';
        document.getElementById('role-spy-duration').textContent =
            String(getRoundDurationMinutes(rolePayload));
    } else {
        document.getElementById('role-spy').style.display = 'none';
        document.getElementById('role-civilian').style.display = 'block';

        const roleLine = document.getElementById('role-reveal-role');
        const showRole = rolePayload.extra_roles && rolePayload.role_label;
        if (showRole) {
            roleLine.style.display = 'block';
            document.getElementById('role-reveal-role-name').textContent = rolePayload.role_label;
        } else {
            roleLine.style.display = 'none';
        }
        document.getElementById('role-reveal-location').textContent = rolePayload.location || '';
    }

    hideAllScreens();
    document.getElementById('screen-role').style.display = 'flex';
    updateNewRoundButtonVisibility();
}

async function enterGameScreen() {
    await loadLocationsJson();
    const inInterrupt = roundInterruptActive;
    if (!inInterrupt) {
        exitRoundInterruptMode();
    }
    applyRoleToLocationsScreen();
    renderLocationsGrid();
    hideAllScreens();
    document.getElementById('screen-locations').style.display = 'flex';
    if (!inInterrupt) {
        showPlayingUI();
    }
    updateNewRoundButtonVisibility();
}

function applyRoleToLocationsScreen() {
    if (!myRole) return;

    const roundInfo = document.getElementById('spy-round-info');
    const locationLine = document.getElementById('info-location');
    const locationName = document.getElementById('info-location-name');
    const spyRoleLine = document.getElementById('info-spy-role');
    const roleEl = document.getElementById('info-role');

    if (myRole.is_spy) {
        roundInfo.style.display = 'block';
        locationLine.style.display = 'none';
        roleEl.style.display = 'none';
        if (spyRoleLine) spyRoleLine.style.display = 'block';
    } else {
        roundInfo.style.display = 'block';
        if (spyRoleLine) spyRoleLine.style.display = 'none';
        const location = myRole.location || '';
        locationName.textContent = location;
        locationLine.style.display = location ? 'block' : 'none';
        if (myRole.role_label) {
            roleEl.textContent = `Role: ${myRole.role_label}`;
            roleEl.style.display = 'block';
        } else {
            roleEl.textContent = '';
            roleEl.style.display = 'none';
        }
    }
    updateSpyGuessButtonVisibility();
    updateLocationsCaptions();
}

function hidePlayingUI() {
    const gameUi = document.querySelector('.spy-play-game-ui');
    if (gameUi) gameUi.style.display = 'none';
    document.getElementById('vote-panel').style.display = 'none';
    document.getElementById('vote-nominate-panel').style.display = 'none';
    document.getElementById('spy-guess-panel').style.display = 'none';
    document.getElementById('vote-cancel-banner').style.display = 'none';
}

function showPlayingUI() {
    const gameUi = document.querySelector('.spy-play-game-ui');
    if (gameUi) gameUi.style.display = 'flex';
    document.getElementById('questions-block').style.display = 'block';
    document.getElementById('playing-actions').style.display = 'flex';
    document.getElementById('round-result').style.display = 'none';
    document.getElementById('score-table').style.display = 'none';
    document.getElementById('next-round-btn').style.display = 'none';
    document.getElementById('back-to-main-btn').style.display = 'none';
}

// Civilians already know the location; spies get role-specific result copy.
function formatSpyNames(spies) {
    if (!spies || spies.length === 0) return '?';
    if (spies.length === 1) return spies[0];
    if (spies.length === 2) return `${spies[0]} and ${spies[1]}`;
    return `${spies.slice(0, -1).join(', ')}, and ${spies[spies.length - 1]}`;
}

function getRoundResultView(data) {
    const result = data.result;
    const location = data.secret_location || '?';
    const showSecretLine = Boolean(myRole?.is_spy);

    if (!result) {
        return {
            message: 'Round finished!',
            secretLine: showSecretLine ? `Secret location: ${location}` : '',
            plain: false,
        };
    }

    const spies = Array.isArray(result.spies) ? result.spies : [];
    const accused = result.accused;

    if (myRole?.is_spy && result.reason === 'vote') {
        if (result.winner === 'spies' && accused) {
            const spyNames = formatSpyNames(spies);
            const winLine = spies.includes(playerName)
                ? (spies.length === 1
                    ? 'You were the spy — and win this round!'
                    : `You were among the spies (${spyNames}) — spies win this round!`)
                : `${spyNames} ${spies.length === 1 ? 'was' : 'were'} the spy — and win this round!`;
            return {
                message: `${accused} wasn't the spy.\n\n${winLine}`,
                secretLine: `Secret location: ${location}`,
                plain: true,
            };
        }

        if (result.winner === 'civilians' && accused && spies.includes(accused)) {
            if (playerName === accused) {
                return {
                    message: (
                        `They found you!\n\n`
                        + `The secret location was ${location}.`
                    ),
                    secretLine: '',
                    plain: true,
                };
            }
            return {
                message: (
                    `They caught one of us...\n\n`
                    + `The group voted against ${accused} — they were right, `
                    + `${accused} was a spy.\n\n`
                    + `Civilians win this round.`
                ),
                secretLine: `Secret location: ${location}`,
                plain: true,
            };
        }
    }

    return {
        message: result.message || 'Round finished!',
        secretLine: showSecretLine ? `Secret location: ${location}` : '',
        plain: false,
    };
}

function showRoundResult(data) {
    roundInterruptActive = false;
    spyGuessActive = false;
    hidePlayingUI();

    document.getElementById('screen-locations').style.display = 'flex';
    document.getElementById('round-result').style.display = 'block';
    const resultView = getRoundResultView(data);
    const resultEl = document.getElementById('result-message');
    resultEl.textContent = resultView.message;
    resultEl.classList.toggle('result-message-plain', resultView.plain);
    const secretEl = document.getElementById('secret-location-reveal');
    secretEl.textContent = resultView.secretLine;
    secretEl.style.display = resultView.secretLine ? 'block' : 'none';

    const tbody = document.querySelector('#results-table tbody');
    tbody.innerHTML = '';
    fillScoreboardTable(data.scoreboard || []);
    document.getElementById('score-table').style.display = 'block';

    document.getElementById('next-round-btn').style.display = 'block';
    document.getElementById('back-to-main-btn').style.display = 'block';
    updateNewRoundButtonVisibility();
}

// Invite link in URL - verify room exists before showing the name screen.
restorePlayerSessionFromUrl();
const roomFromUrl = getRoomFromUrl();
if (roomFromUrl) {
    currentRoomCode = roomFromUrl;
    socket.emit('spy_check_room', { room_code: roomFromUrl });
}
if (sessionRestorePending) {
    hideAllScreens();
} else if (!playerName) {
    document.getElementById('screen-name').style.display = 'flex';
}

if (sessionRestorePending && socket.connected) {
    syncPlayerSession();
}

setTimeout(() => {
    if (!sessionRestorePending) return;
    if (document.getElementById('screen-error').style.display === 'flex') return;
    if (document.getElementById('screen-waiting').style.display === 'flex') return;
    if (document.getElementById('screen-role').style.display === 'flex') return;
    if (document.getElementById('screen-locations').style.display === 'flex') return;
    completeSessionRestore();
    document.getElementById('screen-name').style.display = 'flex';
}, 4000);

loadLocationsJson().catch((err) => console.error('Failed to load locations:', err));

// ---------- Socket events ----------

function enterWaitingRoom(data) {
    currentRoomCode = data.room_code;
    if (data.settings) gameSettings = data.settings;
    applyRoomHostName(data.host_name);
    window.history.pushState({}, '', `/spy-in-ithaca/${currentRoomCode}`);
    updateInviteLinkUI();
    updatePlayersEverywhere(data.players);
    openLobbyScreen();
}

function restoreScreenForPhase(phase) {
    if (!phase || phase === 'waiting') {
        openLobbyScreen();
        return;
    }
    if (phase === 'role_reveal') {
        hideAllScreens();
        document.getElementById('screen-role').style.display = 'flex';
        updateNewRoundButtonVisibility();
    } else if (phase === 'playing') {
        enterGameScreen();
    } else if (phase === 'results') {
        hideAllScreens();
        document.getElementById('screen-locations').style.display = 'flex';
    } else if (phase === 'final_vote') {
        hideAllScreens();
    }
    completeSessionRestoreIfPending();
}

socket.on('spy_room_created', (data) => {
    currentRoomCode = data.room_code;
    if (data.settings) gameSettings = data.settings;
    applyRoomHostName(data.host_name);
    window.history.pushState({}, '', `/spy-in-ithaca/${currentRoomCode}`);
    updateInviteLinkUI();
    updatePlayersEverywhere(data.players);
    savePlayerSession();
    if (data.reconnect || data.mid_game) {
        restoreScreenForPhase(data.phase);
        return;
    }
    openLobbyScreen();
});

socket.on('spy_player_joined', (data) => {
    applyRoomHostName(data.host_name);
    updatePlayersEverywhere(data.players);
});

socket.on('spy_player_kicked', (data) => {
    if (data.player === playerName) {
        clearPlayerSession();
        currentRoomCode = null;
        hideAllScreens();
        const err = document.getElementById('name-error');
        err.textContent = 'You were removed from the game.';
        err.classList.add('show');
        document.getElementById('screen-name').style.display = 'flex';
    }
});

socket.on('spy_player_renamed', (data) => {
    if (localCrossedPlayers.has(data.old_name)) {
        localCrossedPlayers.delete(data.old_name);
        localCrossedPlayers.add(data.new_name);
    }
    applyLocalPlayerRename(data.old_name, data.new_name);
    updatePlayersEverywhere(data.players);
    refreshNameDependentUI(data);
});

socket.on('rename_error', (data) => {
    PlayerNameEdit.showRenameError(data.message || 'Could not rename');
});

socket.on('spy_state_update', (data) => {
    // Keeps lobby settings in sync and restores vote/guess UI after reconnect.
    if (data.settings) {
        gameSettings = data.settings;
        if (document.getElementById('screen-waiting').style.display === 'flex') {
            applySetupUIFromSettings();
        }
    }
    if (data.players) updatePlayersEverywhere(data.players);

    const interruptPhases = ['vote_nominate', 'voting', 'spy_guess', 'final_vote'];
    if (!interruptPhases.includes(data.phase)) {
        restoreScreenForPhase(data.phase);
    }

    if (data.phase === 'vote_nominate' && data.vote_initiator) {
        showNominationPanel(data.vote_initiator);
    } else if (data.phase === 'voting' && data.vote_accused) {
        const spyCount = data.settings?.spy_count ?? gameSettings.spy_count;
        showVotePanel(data.vote_accused, data.vote_initiator, spyCount);
    } else if (data.phase === 'spy_guess' && data.guess_spy) {
        showSpyGuessPanel(data.guess_spy);
    } else if (data.phase === 'final_vote') {
        completeSessionRestore();
        showFinalVotePanel({
            players: data.players,
            votes: data.final_votes || {},
            ballots_count: data.final_vote_ballots_count,
            players_count: data.final_vote_players_count,
        });
    }
});

socket.on('spy_role_assigned', (data) => {
    if (data.player_name && playerName && data.player_name !== playerName) {
        return;
    }
    myRole = data;
    if (data.show_screen === false) {
        if (document.getElementById('screen-locations').style.display === 'flex') {
            applyRoleToLocationsScreen();
        }
        return;
    }
    showRoleScreen(data);
});

socket.on('spy_role_ready_update', (data) => {
    updateRoleWaitingMessage(data);
});

socket.on('spy_enter_game', () => {
    enterGameScreen();
});

socket.on('spy_round_started', (data) => {
    if (data.duration) {
        document.getElementById('round-timer').textContent = formatTime(data.duration);
    }
});

socket.on('spy_question_idea', (data) => {
    showQuestionIdea(data.question);
});

socket.on('spy_timer_update', (data) => {
    document.getElementById('round-timer').textContent = formatTime(data.time_left);
});

socket.on('spy_timer_paused', () => {
    updateTimerControlsForPause();
});

socket.on('spy_timer_resumed', () => {
    document.getElementById('pause-timer-btn').style.display = 'inline-flex';
    document.getElementById('resume-timer-btn').style.display = 'none';
});

socket.on('spy_vote_nomination_started', (data) => {
    if (data.time_left != null) {
        document.getElementById('round-timer').textContent = formatTime(data.time_left);
    }
    showNominationPanel(data.initiator);
});

socket.on('spy_guess_started', (data) => {
    if (data.time_left != null) {
        document.getElementById('round-timer').textContent = formatTime(data.time_left);
    }
    showSpyGuessPanel(data.spy);
});

socket.on('spy_vote_started', (data) => {
    if (data.time_left != null) {
        document.getElementById('round-timer').textContent = formatTime(data.time_left);
    }
    showVotePanel(data.accused, data.initiator, data.spy_count);
});

socket.on('spy_final_vote_started', (data) => {
    if (data.players) {
        updatePlayersEverywhere(data.players);
    }
    showFinalVotePanel(data);
});

socket.on('spy_final_vote_cast', (data) => {
    updateFinalVoteStatus(data);
    if (data.voter === playerName && data.target) {
        const select = document.getElementById('final-vote-select');
        if (select && select.value !== data.target) {
            select.value = data.target;
        }
    }
});

socket.on('spy_vote_cast', (data) => {
    if (myVoteSubmitted) return;
    const total = data.players_count || playersListCache.length;
    const count = data.ballots_count || 0;
    document.getElementById('vote-status').textContent = `${count} of ${total} players have voted.`;
});

socket.on('spy_vote_cancelled', (data) => {
    hideVotePanel();
    const banner = document.getElementById('vote-cancel-banner');
    banner.textContent = data.message || 'Vote is not unanimous. Continue discussion.';
    banner.style.display = 'block';
    setTimeout(() => {
        banner.style.display = 'none';
    }, 6000);
});

socket.on('spy_vote_player_left', (data) => {
    showGameBanner(data.message || `${data.player} left. Vote continues.`);
    if (data.players) {
        updatePlayersEverywhere(data.players);
    }
});

socket.on('spy_round_result', (data) => {
    showRoundResult(data);
});

socket.on('spy_next_round_ready', () => {
    resetClientRoundState();
    openLobbyScreen();
});

socket.on('error', (data) => {
    const message = data.message || 'Error';

    // If the room doesn't exist, show the error screen
    if (message === 'Room not found') {
        completeSessionRestore();
        clearPlayerSession();
        hideAllScreens();
        document.getElementById('screen-error').style.display = 'flex';
        return;
    }
    if (message.includes('already taken')) {
        hideAllScreens();
        document.getElementById('screen-name').style.display = 'flex';
        const err = document.getElementById('name-error');
        err.textContent = message;
        err.classList.add('show');
        return;
    }
    if (document.getElementById('screen-waiting').style.display === 'flex') {
        showLobbyError(message);
        return;
    }
    if (document.getElementById('screen-locations').style.display === 'flex') {
        if (
            roundInterruptActive
            && (message.includes('cannot start a vote') || message.includes('Room not found'))
        ) {
            hideVotePanel();
        }
        showGameBanner(message);
        return;
    }
    const err = document.getElementById('name-error');
    err.textContent = message;
    err.classList.add('show');
});

socket.on('spy_room_exists', () => {
    if (!playerName && !sessionRestorePending) {
        document.getElementById('screen-name').style.display = 'flex';
    }
});

// ---------- Button handlers (send to server) ----------

const spyPlayerNameInput = document.getElementById('playerName');

function clampSpyPlayerNameInput() {
    if (!spyPlayerNameInput) return;
    if (spyPlayerNameInput.value.length <= PlayerNameEdit.MAX_LEN) return;
    const pos = spyPlayerNameInput.selectionStart;
    spyPlayerNameInput.value = spyPlayerNameInput.value.slice(0, PlayerNameEdit.MAX_LEN);
    const newPos = Math.min(typeof pos === 'number' ? pos : PlayerNameEdit.MAX_LEN, PlayerNameEdit.MAX_LEN);
    spyPlayerNameInput.setSelectionRange(newPos, newPos);
}

if (spyPlayerNameInput) {
    spyPlayerNameInput.addEventListener('beforeinput', (e) => {
        if (e.inputType && e.inputType.startsWith('delete')) return;
        const next = (
            spyPlayerNameInput.value.slice(0, spyPlayerNameInput.selectionStart ?? 0)
            + (e.data ?? '')
            + spyPlayerNameInput.value.slice(spyPlayerNameInput.selectionEnd ?? 0)
        );
        if (next.length > PlayerNameEdit.MAX_LEN) {
            e.preventDefault();
        }
    });
    spyPlayerNameInput.addEventListener('input', () => {
        clampSpyPlayerNameInput();
        document.getElementById('name-error').classList.remove('show');
    });
}

document.getElementById('submit_name_btn').addEventListener('click', () => {
    const nameError = document.getElementById('name-error');
    nameError.classList.remove('show');

    playerName = document.getElementById('playerName').value.trim();
    if (!playerName) {
        nameError.textContent = 'Please enter your name';
        nameError.classList.add('show');
        return;
    }
    if (playerName.length > PlayerNameEdit.MAX_LEN) {
        nameError.textContent = `Name is too long (max ${PlayerNameEdit.MAX_LEN} characters)`;
        nameError.classList.add('show');
        return;
    }

    const roomToJoin = getRoomFromUrl() || currentRoomCode;

    if (roomToJoin) {
        currentRoomCode = roomToJoin;
        savePlayerSession();
        socket.emit('spy_join_room', {
            room_code: currentRoomCode,
            name: playerName,
        });
    } else {
        roomHostName = playerName;
        socket.emit('spy_create_room', { name: playerName });
    }
});

document.getElementById('startGame').addEventListener('click', () => {
    if (!currentRoomCode) return;
    clearLobbyMinPlayersPrompt();
    showLobbyError('');
    const minPlayers = getMinPlayersToStart();
    if (playersListCache.length < minPlayers) {
        showLobbyMinPlayersPrompt();
        return;
    }
    socket.emit('spy_start_game', {
        room_code: currentRoomCode,
        player_name: playerName,
        ...collectSettingsPayload(),
    });
});

document.getElementById('startWithBots').addEventListener('click', () => {
    if (!currentRoomCode || !isRoomHost()) return;
    clearLobbyMinPlayersPrompt();
    showLobbyError('');
    socket.emit('spy_start_with_bots', {
        room_code: currentRoomCode,
        player_name: playerName,
        ...collectSettingsPayload(),
    });
});

function handleSpyLobbyCatClick(event) {
    event.preventDefault();
    event.stopPropagation();
    const lobby = document.getElementById('screen-waiting');
    if (!lobby || lobby.style.display !== 'flex') return;
    toggleLobbyKickMode();
}

document.getElementById('spy-lobby-cat')?.addEventListener('click', handleSpyLobbyCatClick);

['setting-spy-count', 'setting-extra-roles', 'setting-duration', 'setting-location-set'].forEach((id) => {
    document.getElementById(id).addEventListener('change', () => {
        if (document.getElementById('screen-waiting').style.display === 'flex') {
            emitSettingsUpdate();
        }
    });
});

document.getElementById('role-continue-btn').addEventListener('click', () => {
    if (!currentRoomCode || myRoleReadySubmitted) return;
    myRoleReadySubmitted = true;
    document.getElementById('role-continue-btn').disabled = true;
    emitWithPlayer('spy_role_ready');
    updateRoleWaitingMessage({ waiting_for: null });
});

document.getElementById('copy-invite-btn').addEventListener('click', async () => {
    const link = buildInviteLink();
    const btn = document.getElementById('copy-invite-btn');
    const status = document.getElementById('copy-invite-status');

    try {
        await navigator.clipboard.writeText(link);
    } catch {
        const input = document.getElementById('invite-link-input');
        input.select();
        document.execCommand('copy');
    }

    btn.classList.add('copied');
    status.classList.add('show');

    setTimeout(() => {
        btn.classList.remove('copied');
        status.classList.remove('show');
    }, 2000);
});

document.getElementById('final-vote-select').addEventListener('change', (event) => {
    const target = event.target.value;
    if (!target || !currentRoomCode || !playerName) return;
    emitWithPlayer('spy_cast_final_vote', { target });
});

document.getElementById('pause-timer-btn').addEventListener('click', () => {
    const text = document.getElementById('round-timer').textContent;
    const parts = text.split(':');
    const sec = parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
    emitWithPlayer('spy_pause_timer', { time_left: sec });
});

document.getElementById('resume-timer-btn').addEventListener('click', () => {
    emitWithPlayer('spy_resume_timer');
});

document.getElementById('spy-guess-btn').addEventListener('click', () => {
    if (!currentRoomCode || !playerName || roundInterruptActive) return;
    emitWithPlayer('spy_start_guess');
});

document.getElementById('vote-btn').addEventListener('click', () => {
    if (!currentRoomCode || !playerName || roundInterruptActive) return;
    // Show UI immediately for the initiator; server event updates everyone else.
    showNominationPanel(playerName);
    emitWithPlayer('spy_start_vote');
});

document.getElementById('vote-nominate-btn').addEventListener('click', () => {
    if (!currentRoomCode || !playerName) return;
    if (playerName !== currentVoteInitiator) {
        showGameBanner('Only the player who started the vote can choose.');
        return;
    }
    const target = document.getElementById('vote-nominate-select').value;
    if (!target) {
        showGameBanner('Choose a player to accuse.');
        return;
    }
    showVotePanel(target, currentVoteInitiator, getSpyCount());
    emitWithPlayer('spy_nominate_accused', { target });
});

document.getElementById('vote-yes-btn').addEventListener('click', () => {
    if (!currentRoomCode || !playerName || myVoteSubmitted || !currentVoteAccused) return;
    if (playerName === currentVoteAccused || playerName === currentVoteInitiator) return;
    emitWithPlayer('spy_cast_vote', { target: currentVoteAccused });
    markVoteSubmitted('You voted. Waiting for other players…');
});

document.getElementById('vote-no-btn').addEventListener('click', () => {
    if (!currentRoomCode || !playerName || myVoteSubmitted || !currentVoteAccused) return;
    if (playerName === currentVoteAccused || playerName === currentVoteInitiator) return;
    emitWithPlayer('spy_vote_no', { target: currentVoteAccused });
    markVoteSubmitted('You voted. Waiting for other players…');
});

document.getElementById('next-round-btn').addEventListener('click', () => {
    emitWithPlayer('spy_next_round');
});

const newRoundDialog = document.getElementById('new-round-dialog');

function showNewRoundDialog() {
    if (!newRoundDialog) return;
    newRoundDialog.classList.add('is-open');
    newRoundDialog.setAttribute('aria-hidden', 'false');
}

function hideNewRoundDialog() {
    if (!newRoundDialog) return;
    newRoundDialog.classList.remove('is-open');
    newRoundDialog.setAttribute('aria-hidden', 'true');
}

document.getElementById('new-round-btn').addEventListener('click', () => {
    if (!currentRoomCode || !playerName) return;
    showNewRoundDialog();
});

document.getElementById('new-round-cancel-btn').addEventListener('click', hideNewRoundDialog);
document.getElementById('new-round-dialog-backdrop').addEventListener('click', hideNewRoundDialog);
document.getElementById('new-round-confirm-btn').addEventListener('click', () => {
    hideNewRoundDialog();
    emitWithPlayer('spy_new_round');
});

document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const dialog = document.getElementById('new-round-dialog');
    if (dialog?.classList.contains('is-open')) hideNewRoundDialog();
});

document.getElementById('back-to-main-btn').addEventListener('click', () => {
    window.location.href = '/';
});

document.getElementById('goHomeBtn').addEventListener('click', () => {
    window.location.href = '/';
});

// Theme toggle (shared with other game pages)
function updateLobbyCatImage(isLight) {
    document.querySelectorAll('.lobby-cat').forEach((lobbyCat) => {
        if (lobbyCat.id === 'spy-lobby-cat') {
            lobbyCat.src = '/static/common/images/orange_cat_waiting.png';
            return;
        }
        lobbyCat.src = isLight
            ? '/static/common/images/orange_cat_light.png'
            : '/static/common/images/orange_cat_waiting.png';
    });
}

const themeToggle = document.getElementById('theme-toggle');
if (localStorage.getItem('theme') === 'light') {
    document.body.classList.add('light-theme');
}
themeToggle.addEventListener('click', () => {
    document.body.classList.toggle('light-theme');
    const isLight = document.body.classList.contains('light-theme');
    localStorage.setItem('theme', isLight ? 'light' : 'dark');
    updateLobbyCatImage(isLight);
});
updateLobbyCatImage(document.body.classList.contains('light-theme'));
initSpySettingSteppers();

window.addEventListener('resize', syncSpyLobbyScroll);
window.addEventListener('resize', syncRestartRoundButtonWidth);
