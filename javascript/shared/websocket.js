/**
 * WebSocket Factory for Image Bench
 *
 * Creates and manages WebSocket connections with platform-agnostic configuration.
 */

/**
 * Create a WebSocket connection with the specified configuration
 * @param {Object} config - Configuration object
 * @param {string} config.endpoint - WebSocket endpoint path (default: '/image-bench/websocket')
 * @param {Function} config.onMessage - Message handler
 * @param {Function} config.onOpen - Open handler
 * @param {Function} config.onClose - Close handler
 * @param {Function} config.onError - Error handler
 * @returns {WebSocket} WebSocket instance
 */
export function createWebSocket(config) {
  const {
    endpoint = '/image-bench/websocket',
    onMessage,
    onOpen,
    onClose,
    onError
  } = config;

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}${endpoint}`;

  const socket = new WebSocket(wsUrl);

  if (onMessage) socket.onmessage = onMessage;
  if (onOpen) socket.onopen = onOpen;
  if (onClose) socket.onclose = onClose;
  if (onError) socket.onerror = onError;

  return socket;
}

/**
 * Check if a WebSocket connection is open
 * @param {WebSocket} socket - WebSocket instance
 * @returns {boolean} True if connection is open
 */
export function isConnectionOpen(socket) {
  return socket && socket.readyState === WebSocket.OPEN;
}

/**
 * Check if a WebSocket connection is closed
 * @param {WebSocket} socket - WebSocket instance
 * @returns {boolean} True if connection is closed
 */
export function isConnectionClosed(socket) {
  return !socket || socket.readyState === WebSocket.CLOSED;
}
