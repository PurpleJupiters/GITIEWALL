// ==UserScript==
// @name         Audimee Auto-select Hailey
// @namespace    https://audimee.com/
// @version      1.2
// @description  Auto-selects Hailey voice on Audimee convert page
// @author       SunoMaster
// @match        https://audimee.com/create
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';

    var TARGET = 'Hailey';
    var done = false;

    // Type into a React-controlled input using real keyboard events
    function reactType(input, text) {
        input.focus();
        // Clear existing value
        input.select();
        document.execCommand('selectAll', false);
        document.execCommand('delete', false);
        // Insert text via execCommand (React sees this as real user input)
        document.execCommand('insertText', false, text);
    }

    // Find element by exact trimmed text
    function findByExactText(root, text) {
        var all = root.querySelectorAll('p, span, h3, div, button');
        for (var i = 0; i < all.length; i++) {
            var el = all[i];
            if (el.children.length === 0 && el.textContent.trim() === text) {
                return el;
            }
        }
        return null;
    }

    function trySelectHailey() {
        var modal = document.querySelector('[role="dialog"]') ||
                    document.querySelector('[aria-modal="true"]');
        if (!modal) return false;

        // Try to find Hailey directly (no search needed if she's visible)
        var nameEl = findByExactText(modal, TARGET);
        if (nameEl) {
            // Walk up to find the clickable card button
            var clickable = nameEl;
            var limit = 6;
            while (clickable && limit-- > 0) {
                if (clickable.tagName === 'BUTTON' || clickable.getAttribute('role') === 'button' || clickable.onclick) {
                    break;
                }
                clickable = clickable.parentElement;
            }
            if (clickable && clickable !== document.body) {
                clickable.click();
            } else {
                nameEl.click();
            }
            // Verify modal closed = success
            setTimeout(function() {
                var stillOpen = document.querySelector('[role="dialog"]');
                if (!stillOpen) {
                    done = true;
                    console.log('[Audimee] Hailey selected!');
                } else {
                    // Modal still open - try search approach
                    searchAndSelect(modal);
                }
            }, 600);
            return true;
        }

        // Hailey not immediately visible - use search
        searchAndSelect(modal);
        return true;
    }

    function searchAndSelect(modal) {
        var searchBox = modal.querySelector('input');
        if (!searchBox) return;

        reactType(searchBox, TARGET);

        // Wait for filtered results then click Hailey
        var attempts = 0;
        var interval = setInterval(function() {
            attempts++;
            var nameEl = findByExactText(modal, TARGET);
            if (nameEl) {
                clearInterval(interval);
                var clickable = nameEl;
                var limit = 6;
                while (clickable && limit-- > 0) {
                    if (clickable.tagName === 'BUTTON') break;
                    clickable = clickable.parentElement;
                }
                (clickable || nameEl).click();
                setTimeout(function() {
                    if (!document.querySelector('[role="dialog"]')) {
                        done = true;
                        console.log('[Audimee] Hailey selected via search!');
                    }
                }, 600);
            }
            if (attempts > 15) clearInterval(interval);
        }, 400);
    }

    // Main: wait for page to render, click Switch voice, select Hailey
    var attempts = 0;
    var init = setInterval(function() {
        attempts++;
        if (done || attempts > 40) { clearInterval(init); return; }

        // Already on Hailey? Skip.
        var heading = document.querySelector('h2');
        if (heading && heading.textContent.trim() === TARGET) {
            done = true;
            clearInterval(init);
            console.log('[Audimee] Already on Hailey.');
            return;
        }

        // Find Switch voice button
        var switchBtn = Array.from(document.querySelectorAll('button')).find(function(b) {
            return b.innerText && b.innerText.trim() === 'Switch voice';
        });
        if (!switchBtn) return;

        clearInterval(init);
        console.log('[Audimee] Clicking Switch voice...');
        switchBtn.click();

        // Wait for modal, then select Hailey
        var modalWait = 0;
        var modalInterval = setInterval(function() {
            modalWait++;
            var modal = document.querySelector('[role="dialog"]') ||
                        document.querySelector('[aria-modal="true"]');
            if (modal) {
                clearInterval(modalInterval);
                setTimeout(function() { trySelectHailey(); }, 500);
            }
            if (modalWait > 20) clearInterval(modalInterval);
        }, 300);

    }, 500);

})();
