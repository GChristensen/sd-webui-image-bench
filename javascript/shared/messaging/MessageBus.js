/**
 * MessageBus - Simple pub-sub message bus
 * Enables decoupled communication between modules
 */

export class MessageBus {
    constructor() {
        this.subscribers = new Map();
    }

    /**
     * Subscribe to a message type
     * @param {string} messageType - Type of message to subscribe to
     * @param {Function} callback - Callback function
     * @returns {Function} Unsubscribe function
     */
    subscribe(messageType, callback) {
        if (!this.subscribers.has(messageType)) {
            this.subscribers.set(messageType, []);
        }

        this.subscribers.get(messageType).push(callback);

        // Return unsubscribe function
        return () => {
            const callbacks = this.subscribers.get(messageType);
            const index = callbacks.indexOf(callback);
            if (index > -1) {
                callbacks.splice(index, 1);
            }
        };
    }

    /**
     * Publish a message
     * @param {string} messageType - Type of message
     * @param {Object} data - Message data
     */
    publish(messageType, data = {}) {
        const callbacks = this.subscribers.get(messageType);
        
        if (callbacks && callbacks.length > 0) {
            callbacks.forEach(callback => {
                try {
                    callback(data);
                } catch (error) {
                    console.error(`Error in message handler for ${messageType}:`, error);
                }
            });
        }
    }

    /**
     * Unsubscribe all callbacks for a message type
     * @param {string} messageType - Type of message
     */
    unsubscribeAll(messageType) {
        this.subscribers.delete(messageType);
    }

    /**
     * Clear all subscriptions
     */
    clear() {
        this.subscribers.clear();
    }
}

// Create singleton instance
export const messageBus = new MessageBus();
