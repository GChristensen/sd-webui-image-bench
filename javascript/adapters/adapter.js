/**
 * Adapter Instance
 * Provides a singleton instance of the DOM adapter
 */

import { SDWebuiAdapter } from './SDWebuiAdapter.js';

/**
 * Global adapter instance
 * This is the primary way to interact with the DOM in the extension
 */
export const adapter = new SDWebuiAdapter();

/**
 * Helper to check if Forge is being used
 * @returns {boolean}
 */
export function isForge() {
    return adapter.isForge();
}
