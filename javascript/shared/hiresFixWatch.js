/**
 * Reports the Hires. fix switch of the host to the popup (HIRES_FIX_STATE {on}), which shows a badge on its
 * Generate tab while it is on. Unlike the Generate tab mirror it runs while the popup is open, whatever tab
 * it shows: the switch also changes in the host UI and by the strategies (upscaling switches it on for the run).
 * Only changes are sent; HIRES_FIX_SUBSCRIBE (sent by the popup to each host page it meets) sends the state again.
 */

const POLL_INTERVAL = 1000;

/**
 * @param {() => boolean|null} read - Whether Hires. fix is on, null if the host has no switch for it
 * @param {Object} popup - {sendMessage: (msg) => boolean, isOpen: () => boolean}
 */
export function createHiresFixWatch(read, popup) {
    let timer = null;
    let last;

    function poll() {
        if (!popup.isOpen()) {
            clearInterval(timer);
            timer = null;
            return;
        }

        let on = null;

        try {
            on = read();
        } catch (error) {
            console.warn('[Image Bench] Unable to read the Hires. fix switch:', error);
        }

        if (on !== last) {
            last = on;
            popup.sendMessage({type: "HIRES_FIX_STATE", on});
        }
    }

    // The popup (re)connected: send the state even if it did not change
    function subscribe() {
        last = undefined;

        if (!timer)
            timer = setInterval(poll, POLL_INTERVAL);

        poll();
    }

    return {subscribe};
}
