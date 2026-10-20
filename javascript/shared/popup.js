/**
 * Popup Window Management for Image Bench
 *
 * Unified popup window management with optional WebSocket integration.
 * Handles window lifecycle, message passing, and connection management.
 */

import {getGenerationState, setGenerationState} from "./state.js";
import {createWebSocket, isConnectionOpen} from "./websocket.js";
import {loadAppConfig} from "./utils.js";

/**
 * The Image Bench window that loads this host page in its iframe (embedded mode), which sets imageBenchEmbedded
 * @returns {Window|null}
 */
export function getEmbeddingWindow() {
  if (window.parent === window) {
    return null;
  }

  try {
    return window.parent.imageBenchEmbedded ? window.parent : null;
  } catch {
    // A parent of another origin
    return null;
  }
}

/**
 * Create a popup manager with the specified configuration
 * @param {Object} config - Configuration object
 * @param {string} config.endpoint - Popup window endpoint (default: '/image-bench/window')
 * @param {boolean} config.integrateWebSocket - Whether to integrate WebSocket (default: false)
 * @param {string} config.windowName - Window name for window.open (default: 'imageBenchPopup')
 * @param {string} config.windowFeatures - Window features string (default: 'width=1024,height=720,left=100,top=100')
 * @returns {Object} Popup manager instance
 */
export function createPopupManager(config = {}) {
  const {
    endpoint = '/image-bench/window',
    integrateWebSocket = false,
    windowName = 'imageBenchPopup',
    windowFeatures = 'width=1024,height=720,left=100,top=100'
  } = config;

  // Internal state
  let popupWindow = null;
  // Whether popupWindow is the Image Bench window embedding this page in its iframe, not a window opened here
  let attached = false;
  let websocket = null;
  let messageQueue = [];
  // The "openInWindow" setting, read ahead so that window.open() stays within the user gesture of the click.
  // It may be changed in the popup, the user then returns to this window
  let openInWindow = false;

  async function loadOpenInWindow() {
    const appConfig = await loadAppConfig();
    if (appConfig)
      openInWindow = !!appConfig.openInWindow;
  }

  loadOpenInWindow();
  window.addEventListener("focus", loadOpenInWindow);

  /**
   * Connect to WebSocket for real-time communication (ComfyUI mode)
   */
  function connectWebSocket() {
    if (isConnectionOpen(websocket)) {
      return;
    }

    websocket = createWebSocket({
      endpoint: '/image-bench/websocket',
      onOpen: () => {
        console.log('[Image Bench] WebSocket connected');
        // Send queued messages
        while (messageQueue.length > 0) {
          const msg = messageQueue.shift();
          sendMessage(msg);
        }
      },
      onClose: () => {
        console.log('[Image Bench] WebSocket disconnected');
        websocket = null;
      },
      onError: (error) => {
        console.error('[Image Bench] WebSocket error:', error);
      },
      onMessage: (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('[Image Bench] Received:', data);
          // Handle messages from backend if needed
        } catch (e) {
          console.error('[Image Bench] Failed to parse message:', e);
        }
      }
    });
  }

  /**
   * Open the popup window
   * @returns {boolean} True if window was created, false if already open
   */
  function openPopup() {
    // The Image Bench button of a page in the iframe of Image Bench shows its own tabs
    if (attached) {
      popupWindow.imageBenchShowApp?.();
      popupWindow.focus();
      return false;
    }

    if (popupWindow && !popupWindow.closed) {
      popupWindow.focus();
      return false;
    }

    // Without window features the browser opens a tab, which keeps window.opener like a popup
    popupWindow = openInWindow
      ? window.open(endpoint, windowName, windowFeatures)
      : window.open(endpoint, windowName);

    if (!popupWindow) {
      console.error('[Image Bench] Failed to open popup window. Check popup blocker settings.');
      return false;
    }

    setupPopup();
    return true;
  }

  // Set up a popup window opened by this page or by the page it replaced (adopt)
  function setupPopup() {
    // Set generation state
    setGenerationState("BATCH_GENERATION");

    // Inject getGenerationState function into popup window
    popupWindow.getGenerationState = getGenerationState;

    // Handle popup close
    const win = popupWindow;
    win.addEventListener("unload", () => {
      if (popupWindow === win && win.location.href !== "about:blank") {
        dispose();
      }
    });

    // Setup WebSocket if integrated mode
    if (integrateWebSocket) {
      connectWebSocket();
    }
  }

  /**
   * Forget the popup opened by this page without closing it: the popup reloads this page (its backend has
   * restarted), and the new page adopts it
   */
  function release() {
    if (!attached)
      dispose();
  }

  /**
   * Take over the popup opened by the page this one replaced (see release())
   * @param {Window} targetWindow
   * @returns {boolean} True if adopted, false if this page has a popup already
   */
  function adopt(targetWindow) {
    if (attached || (popupWindow && !popupWindow.closed)) {
      return false;
    }

    popupWindow = targetWindow;
    setupPopup();

    // The popup sends this page its state, as to a page attached in the embedded mode
    sendMessage({type: "HOST_READY"});
    return true;
  }

  /**
   * Use the Image Bench window that embeds this page in its iframe (getEmbeddingWindow()) in place of a popup
   * @param {Window} targetWindow
   * @returns {boolean} True if attached, false if already attached to it
   */
  function attach(targetWindow) {
    if (attached && popupWindow === targetWindow) {
      return false;
    }

    popupWindow = targetWindow;
    attached = true;

    setGenerationState("BATCH_GENERATION");
    popupWindow.getGenerationState = getGenerationState;

    if (integrateWebSocket) {
      connectWebSocket();
    }

    // Image Bench outlives this page: it sends its state again to the next page loaded in the iframe
    window.addEventListener("pagehide", () => sendMessage({type: "HOST_DETACHED"}));
    sendMessage({type: "HOST_READY"});

    return true;
  }

  /**
   * Send message to popup window
   * @param {Object} message - Message object to send
   * @returns {boolean} True if message was sent
   */
  function sendMessage(message) {
    // Try to send via window.postMessage first (direct method)
    if (popupWindow && !popupWindow.closed && popupWindow.onSDEvent) {
      popupWindow.onSDEvent(message);
      return true;
    }

    // Fallback: send via WebSocket (ComfyUI integrated mode)
    if (integrateWebSocket && isConnectionOpen(websocket)) {
      websocket.send(JSON.stringify(message));
      return true;
    }

    // Queue message for later (only in integrated mode)
    if (integrateWebSocket) {
      messageQueue.push(message);
    }

    return false;
  }

  /**
   * Check if popup is currently open
   * @returns {boolean} True if popup is open
   */
  function isOpen() {
    return popupWindow && !popupWindow.closed;
  }

  /**
   * Close the popup window
   */
  function close() {
    // The embedding window closes itself
    if (!attached && popupWindow && !popupWindow.closed) {
      popupWindow.close();
    }
  }

  /**
   * Dispose popup and close connections
   */
  function dispose() {
    popupWindow = null;
    attached = false;

    if (websocket) {
      websocket.close();
      websocket = null;
    }

    // Clear message queue
    messageQueue = [];
  }

  /**
   * Close WebSocket connection (separate from popup)
   */
  function closeWebSocket() {
    if (websocket) {
      websocket.close();
      websocket = null;
    }
  }

  /**
   * @returns {boolean} True if attached to an embedding window
   */
  function isAttached() {
    return attached;
  }

  // Return public API
  return {
    open: openPopup,
    attach,
    release,
    adopt,
    isAttached,
    close,
    dispose,
    sendMessage,
    isOpen,
    closeWebSocket
  };
}
