/**
 * Inline edit for the current player's name (pencil button to rename).
 */
window.PlayerNameEdit = (function () {
    const MAX_LEN = 10;

    function normalizeName(name) {
        return (name || '').trim();
    }

    function isValidName(name) {
        const n = normalizeName(name);
        return n.length >= 1 && n.length <= MAX_LEN;
    }

    function isOwnName(name, ownName) {
        return ownName && normalizeName(name) === normalizeName(ownName);
    }

    function showRenameError(message) {
        let toast = document.getElementById('player-rename-toast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'player-rename-toast';
            toast.className = 'player-rename-toast';
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add('show');
        clearTimeout(toast._hideTimer);
        toast._hideTimer = setTimeout(() => toast.classList.remove('show'), 3500);
    }

    function createPencilButton(name, options, containerEl) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'player-name-edit-btn';
        btn.title = 'Edit your name';
        btn.setAttribute('aria-label', 'Edit your name');
        btn.innerHTML = (
            '<svg class="player-name-edit-icon" viewBox="0 0 24 24" width="14" height="14" '
            + 'aria-hidden="true" focusable="false">'
            + '<path fill="currentColor" d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25z'
            + 'M20.71 7.04a1.003 1.003 0 0 0 0-1.42l-2.34-2.34a1.003 1.003 0 0 0-1.42 0l-1.83 1.83'
            + ' 3.75 3.75 1.84-1.82z"/>'
            + '</svg>'
        );
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (containerEl.classList.contains('player-name-editing')) return;
            beginInlineEdit(containerEl, name, options);
        });
        return btn;
    }

    function setPlayerNameElement(el, name, options) {
        const { ownName, onRenameRequest } = options;

        el.innerHTML = '';
        el.classList.remove('player-name-own', 'player-name-editing');
        el.removeAttribute('title');
        el.onclick = null;
        el.dataset.playerName = name;

        if (!isOwnName(name, ownName)) {
            el.textContent = name;
            return;
        }

        el.classList.add('player-name-own');

        const row = document.createElement('span');
        row.className = 'player-name-row';

        const label = document.createElement('span');
        label.className = 'player-name-label';
        label.textContent = name;

        row.appendChild(label);
        row.appendChild(createPencilButton(name, options, el));
        el.appendChild(row);
    }

    function getMeasureSpan(input) {
        if (!input._measureSpan) {
            const span = document.createElement('span');
            span.className = 'player-name-measure';
            span.setAttribute('aria-hidden', 'true');
            span.style.cssText = [
                'position:absolute',
                'visibility:hidden',
                'white-space:pre',
                'pointer-events:none',
                'height:0',
                'overflow:hidden',
            ].join(';');
            document.body.appendChild(span);
            input._measureSpan = span;
        }
        return input._measureSpan;
    }

    function cleanupMeasureSpan(input) {
        if (input._measureSpan) {
            input._measureSpan.remove();
            input._measureSpan = null;
        }
    }

    function measureTextWidth(input, text) {
        const span = getMeasureSpan(input);
        const inputStyles = window.getComputedStyle(input);
        span.style.font = inputStyles.font;
        span.style.fontSize = inputStyles.fontSize;
        span.style.fontFamily = inputStyles.fontFamily;
        span.style.fontWeight = inputStyles.fontWeight;
        span.style.letterSpacing = inputStyles.letterSpacing;
        span.textContent = text || '\u00a0';
        return span.offsetWidth;
    }

    function keepInputCaretVisible(input) {
        if (input.scrollWidth <= input.clientWidth + 1) {
            input.scrollLeft = 0;
            return;
        }

        const pos = input.selectionStart ?? input.value.length;
        const style = window.getComputedStyle(input);
        const probe = document.createElement('span');
        probe.style.cssText = [
            'position:absolute',
            'visibility:hidden',
            'white-space:pre',
            'font:' + style.font,
            'font-size:' + style.fontSize,
            'font-family:' + style.fontFamily,
            'font-weight:' + style.fontWeight,
            'letter-spacing:' + style.letterSpacing,
        ].join(';');
        probe.textContent = input.value.slice(0, pos);
        document.body.appendChild(probe);
        const caretX = probe.offsetWidth;
        probe.remove();

        const textAlign = style.textAlign;
        if (textAlign === 'center' && pos === input.value.length) {
            const overflow = input.scrollWidth - input.clientWidth;
            input.scrollLeft = Math.max(0, overflow / 2);
            return;
        }

        if (pos === input.value.length) {
            input.scrollLeft = input.scrollWidth;
            return;
        }

        if (caretX < input.scrollLeft) {
            input.scrollLeft = caretX;
        } else if (caretX - input.scrollLeft > input.clientWidth - 8) {
            input.scrollLeft = caretX - input.clientWidth + 8;
        }
    }

    function resizeEditContainer(el, input) {
        const minW = el._editMinWidth || 0;
        const maxW = el._editMaxWidth || minW;
        const textWidth = measureTextWidth(input, input.value || ' ');
        const width = Math.min(maxW, Math.max(minW, textWidth + 2));
        el.style.width = `${Math.ceil(width)}px`;
        keepInputCaretVisible(input);
    }

    function prepareEditContainer(el, input, currentName, startWidth, startHeight) {
        const styles = window.getComputedStyle(el);

        if (styles.display === 'inline') {
            el.style.display = 'inline-block';
        }

        el.style.boxSizing = 'border-box';
        el.style.height = `${startHeight}px`;
        el.style.minHeight = `${startHeight}px`;
        el.style.maxHeight = `${startHeight}px`;
        el.style.marginLeft = 'auto';
        el.style.marginRight = 'auto';

        const nameWidth = measureTextWidth(input, currentName || ' ');
        el._editMinWidth = Math.max(startWidth, Math.ceil(nameWidth + 2));
        el._editMaxWidth = Math.max(
            el._editMinWidth,
            Math.ceil(measureTextWidth(input, '0'.repeat(MAX_LEN)) + 4),
        );
        const parent = el.parentElement;
        if (parent) {
            const parentCap = parent.clientWidth;
            if (parentCap > 0) {
                el._editMaxWidth = Math.min(el._editMaxWidth, parentCap);
            }
        }
        resizeEditContainer(el, input);
    }

    function unlockElementSize(el) {
        el.style.boxSizing = '';
        el.style.width = '';
        el.style.height = '';
        el.style.minHeight = '';
        el.style.maxHeight = '';
        el.style.overflow = '';
        el.style.display = '';
        el.style.marginLeft = '';
        el.style.marginRight = '';
        delete el._editMinWidth;
        delete el._editMaxWidth;
    }

    function clampInputLength(input) {
        if (input.value.length <= MAX_LEN) return;
        const pos = input.selectionStart;
        input.value = input.value.slice(0, MAX_LEN);
        const newPos = Math.min(typeof pos === 'number' ? pos : MAX_LEN, MAX_LEN);
        input.setSelectionRange(newPos, newPos);
    }

    function beginInlineEdit(el, currentName, options) {
        const startRect = el.getBoundingClientRect();
        const startWidth = Math.ceil(startRect.width);
        const startHeight = Math.ceil(startRect.height);

        el.classList.add('player-name-editing');

        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'player-name-edit-input';
        input.value = currentName;
        input.maxLength = MAX_LEN;
        input.setAttribute('aria-label', 'Edit your name');

        const restore = (name) => {
            cleanupMeasureSpan(input);
            el.classList.remove('player-name-editing');
            unlockElementSize(el);
            setPlayerNameElement(el, name, options);
        };

        const commit = () => {
            if (!el.classList.contains('player-name-editing')) return;
            const newName = normalizeName(input.value);
            if (!isValidName(newName) || newName === currentName) {
                restore(currentName);
                return;
            }
            options.onRenameRequest(newName);
            restore(currentName);
        };

        el.textContent = '';
        el.appendChild(input);
        prepareEditContainer(el, input, currentName, startWidth, startHeight);
        input.focus();
        const end = input.value.length;
        input.setSelectionRange(end, end);
        keepInputCaretVisible(input);

        input.addEventListener('beforeinput', (e) => {
            if (e.inputType && e.inputType.startsWith('delete')) return;
            const next = (
                input.value.slice(0, input.selectionStart ?? 0)
                + (e.data ?? '')
                + input.value.slice(input.selectionEnd ?? 0)
            );
            if (next.length > MAX_LEN) {
                e.preventDefault();
            }
        });
        input.addEventListener('input', () => {
            clampInputLength(input);
            resizeEditContainer(el, input);
            keepInputCaretVisible(input);
        });
        input.addEventListener('keyup', () => keepInputCaretVisible(input));
        input.addEventListener('click', (e) => {
            e.stopPropagation();
            keepInputCaretVisible(input);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                commit();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                restore(currentName);
            }
        });
        input.addEventListener('blur', commit);
    }

    function createNameTd(name, options) {
        const td = document.createElement('td');
        setPlayerNameElement(td, name, options);
        return td;
    }

    function createNameLi(name, options) {
        const li = document.createElement('li');
        li.setAttribute('data-player', name);
        setPlayerNameElement(li, name, options);
        return li;
    }

    return {
        MAX_LEN,
        normalizeName,
        isValidName,
        showRenameError,
        setPlayerNameElement,
        createNameTd,
        createNameLi,
    };
})();
