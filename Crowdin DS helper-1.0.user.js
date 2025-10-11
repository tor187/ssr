// ==UserScript==
// @name         Crowdin DS helper
// @namespace    user.crowdin.linechecker.checkbox-top-right-absolute
// @version      1.0
// @description  Шрифт Death Stranding, перевірка довжини діалогів
// @match        https://*.crowdin.com/editor/dsdc*
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    const MAX_WIDTH = 563;
    const FONT_STACK = '"SST Roman", "SST", "Segoe UI", Arial, sans-serif';
    const FONT = `15px ${FONT_STACK}`;

    // --- CSS ---
    const style = document.createElement('style');
    style.textContent = `
        textarea#translation,
        textarea[data-app-scope="textarea"],
        .hwt-content,
        .hwt-input {
            font-family: ${FONT_STACK} !important;
            font-size: 15px !important;
            line-height: 1.45 !important;
            letter-spacing: 0 !important;
            word-spacing: 0 !important;
            text-rendering: geometricPrecision !important;
            -webkit-font-smoothing: none !important;
            font-kerning: none !important;
            font-variant-ligatures: none !important;
            white-space: pre-wrap !important;
            overflow-wrap: normal !important;
            position: relative;
        }

        .hwt-content span,
        .hwt-content mark {
            letter-spacing: 0 !important;
            word-spacing: 0 !important;
            font-weight: normal !important;
            font-style: normal !important;
        }

        /* Світло-сіре виділення */
        textarea#translation::selection,
        textarea[data-app-scope="textarea"]::selection,
        .hwt-content::selection,
        .hwt-input::selection,
        .hwt-content span::selection {
            background: rgba(180, 180, 180, 0.3) !important;
            color: inherit !important;
        }

        .textarea-wrapper { position: relative; }

        .linecheck-wrapper {
            position: absolute;
            top: -22px;
            right: 0;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .linecheck-warning {
            color: #C00;
            font-size: 12px;
            display: none;
            white-space: nowrap;
        }

        .linecheck-container label.checkbox {
            cursor: pointer;
            font-family: ${FONT_STACK};
            font-size: 14px;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }

        .linecheck-container label.checkbox input[type="checkbox"] {
            margin: 0;
            cursor: pointer;
        }
    `;
    document.head.appendChild(style);

    // --- Вимірювання ширини ---
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    ctx.font = FONT;
    const measure = txt => ctx.measureText(txt).width;

    // --- Синхронізація шарів HWT ---
    function syncLayers() {
        const input = document.querySelector('.hwt-input');
        const content = document.querySelector('.hwt-content');
        if (!input || !content) return;

        const inputRect = input.getBoundingClientRect();
        content.style.width = input.offsetWidth + 'px';
        content.style.height = input.offsetHeight + 'px';
        content.style.transform = getComputedStyle(input).transform || 'none';
        content.style.top = '0';
        content.style.left = '0';
        content.style.margin = '0';
        content.style.padding = '0';
        content.style.overflow = 'hidden';
    }

    setInterval(syncLayers, 500); // регулярне оновлення, щоб курсор завжди збігався

    // --- Створення перевірки довжини рядка ---
    function createChecker(textarea) {
        const wrapper = document.createElement('div');
        wrapper.className = 'textarea-wrapper';
        textarea.parentNode.insertBefore(wrapper, textarea);
        wrapper.appendChild(textarea);

        const topWrapper = document.createElement('div');
        topWrapper.className = 'linecheck-wrapper';

        const warning = document.createElement('div');
        warning.className = 'linecheck-warning';
        warning.textContent = 'Рядок завеликий!';

        const container = document.createElement('div');
        container.className = 'linecheck-container';

        const label = document.createElement('label');
        label.className = 'checkbox';
        label.title = 'Перевіряти довжину рядка для діалогів';
        const checkboxId = 'linecheck_' + Math.random().toString(36).substr(2, 5);
        label.innerHTML = `<input type="checkbox" id="${checkboxId}" checked>`;

        container.appendChild(label);
        topWrapper.appendChild(warning);
        topWrapper.appendChild(container);
        wrapper.appendChild(topWrapper);

        const checkbox = label.querySelector('input[type="checkbox"]');

        textarea.addEventListener('input', () => {
            if (!checkbox.checked) {
                warning.style.display = 'none';
                return;
            }
            const tooWide = textarea.value.split('\n').some(line => measure(line) > MAX_WIDTH);
            warning.style.display = tooWide ? 'inline-block' : 'none';
        });

        checkbox.addEventListener('change', () => {
            if (!checkbox.checked) warning.style.display = 'none';
        });
    }

    // --- Автоматичне підключення ---
    function attachChecker() {
        const textarea = document.querySelector('textarea#translation, [data-app-scope="textarea"]');
        if (!textarea || textarea.dataset._checkerAttached) return;
        textarea.dataset._checkerAttached = 'true';
        createChecker(textarea);
    }

    const observer = new MutationObserver(() => {
        attachChecker();
        syncLayers();
    });
    observer.observe(document.body, { childList: true, subtree: true });
})();
