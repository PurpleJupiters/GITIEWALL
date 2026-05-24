// ==UserScript==
// @name         Audimee — Auto-select Hailey
// @namespace    https://audimee.com/
// @version      1.1
// @description  Automatically selects Hailey as the voice every time the Convert Vocals page loads. No more accidental Mark conversions.
// @author       SunoMaster / Claude Code
// @match        https://audimee.com/create
// @match        https://audimee.com/create*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function () {
    'use strict';

    const TARGET_VOICE = 'Hailey';
    const CHECK_INTERVAL_MS = 500;
    const MAX_WAIT_MS = 15000;

    let done = false;

    function log(msg) {
        console.log(`[Audimee Auto-Hailey] ${msg}`);
    }

    // Wait for an element matching selector to appear, then call callback
    function waitFor(selector, callback, root = document, timeout = MAX_WAIT_MS) {
        const deadline = Date.now() + timeout;
        const interval = setInterval(() => {
            const el = root.querySelector(selector);
            if (el) {
                clearInterval(interval);
                callback(el);
            } else if (Date.now() > deadline) {
                clearInterval(interval);
                log(`Timed out waiting for: ${selector}`);
            }
        }, CHECK_INTERVAL_MS);
    }

    // Find element by exact text content
    function findByText(parent, tag, text) {
        return [...parent.querySelectorAll(tag)].find(el => el.textContent.trim() === text);
    }

    function selectHailey() {
        if (done) return;

        // Step 1: Check if voice is already Hailey
        const currentVoiceEl = document.querySelector('h1, h2, [class*="voice-name"], [class*="VoiceName"]');
        const bodyText = document.body.innerText;
        if (bodyText.includes(`${TARGET_VOICE}\n`) && !bodyText.includes('Select voice')) {
            // Check the heading on the page
            const headings = [...document.querySelectorAll('h1, h2, h3, p')];
            const voiceHeading = headings.find(h =>
                h.textContent.trim() === TARGET_VOICE &&
                h.className && h.className.includes && !h.className.includes('modal')
            );
            if (voiceHeading) {
                log(`${TARGET_VOICE} already selected — nothing to do.`);
                done = true;
                return;
            }
        }

        // Step 2: Find "Switch voice" button
        const switchBtn = findByText(document, 'button', 'Switch voice') ||
                          [...document.querySelectorAll('button')].find(b => b.innerText?.includes('Switch voice'));

        if (!switchBtn) {
            log('Switch voice button not found yet...');
            return;
        }

        log('Clicking "Switch voice"...');
        switchBtn.click();

        // Step 3: Wait for the modal search box to appear
        waitFor('input[placeholder*="Search"]', (searchBox) => {
            log('Modal open — typing "Hailey"...');
            // Type into search box
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
            nativeInputValueSetter.call(searchBox, TARGET_VOICE);
            searchBox.dispatchEvent(new Event('input', { bubbles: true }));
            searchBox.dispatchEvent(new Event('change', { bubbles: true }));

            // Step 4: Wait for Hailey card to appear and click her name
            const searchDeadline = Date.now() + 5000;
            const searchInterval = setInterval(() => {
                // Look for p/span/div with exact text "Hailey"
                const modal = document.querySelector('[role="dialog"]') ||
                              document.querySelector('[class*="modal"]') ||
                              document.querySelector('[aria-modal="true"]') ||
                              document.body;

                const nameEl = findByText(modal, 'p', TARGET_VOICE) ||
                               findByText(modal, 'span', TARGET_VOICE) ||
                               [...modal.querySelectorAll('p, span, div')].find(el =>
                                   el.textContent.trim() === TARGET_VOICE && el.children.length === 0
                               );

                if (nameEl) {
                    clearInterval(searchInterval);
                    log(`Found ${TARGET_VOICE} card — clicking...`);
                    // Click the name element to select the voice
                    nameEl.click();
                    // Also try clicking the parent button if name click doesn't work
                    setTimeout(() => {
                        const modal2 = document.querySelector('[role="dialog"]') || document.body;
                        const stillOpen = modal2.querySelector('input[placeholder*="Search"]');
                        if (stillOpen) {
                            log('Modal still open — trying parent click...');
                            const parent = nameEl.closest('button') || nameEl.parentElement?.closest('button') || nameEl.parentElement;
                            if (parent) parent.click();
                        } else {
                            log(`${TARGET_VOICE} selected successfully! ✓`);
                            done = true;
                        }
                    }, 800);
                } else if (Date.now() > searchDeadline) {
                    clearInterval(searchInterval);
                    log(`Could not find ${TARGET_VOICE} in search results.`);
                }
            }, 300);
        });
    }

    // Run once the page has loaded and React has rendered
    function init() {
        log('Page loaded — waiting for voice selector to be ready...');

        // Wait for "Switch voice" button to appear (indicates React has rendered)
        const deadline = Date.now() + MAX_WAIT_MS;
        const initInterval = setInterval(() => {
            const switchBtn = [...document.querySelectorAll('button')].find(b =>
                b.innerText?.includes('Switch voice')
            );
            if (switchBtn) {
                clearInterval(initInterval);
                // Small delay to let React finish rendering voice state
                setTimeout(selectHailey, 1000);
            } else if (Date.now() > deadline) {
                clearInterval(initInterval);
                log('Timed out — Switch voice button never appeared.');
            }
        }, CHECK_INTERVAL_MS);
    }

    init();
})();
