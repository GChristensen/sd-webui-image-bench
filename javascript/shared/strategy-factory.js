/**
 * Strategy Factory for Image Bench
 *
 * Creates strategy instances with dependency injection and sets up
 * the MessageBus → popup communication bridge.
 */

import {ModelExplorationStrategy} from "./strategies/ModelExplorationStrategy.js";
import {BatchGenerationStrategy} from "./strategies/BatchGenerationStrategy.js";
import {ImageProcessingStrategy} from "./strategies/ImageProcessingStrategy.js";
import {VaryingParametersStrategy} from "./strategies/VaryingParametersStrategy.js";
import {messageBus} from "./messaging/MessageBus.js";

/**
 * Create strategy instances with the provided UI operations facade
 * @param {Object} uiOperations - Platform-specific UI operations facade (UIOperations or ComfyUIOperations)
 * @param {Function} popupMessageSender - Function to send messages to popup (e.g., sendPopupMessage)
 * @returns {Object} Object containing all strategy instances
 */
export function createStrategies(uiOperations, popupMessageSender) {
  // Create strategy instances
  const strategies = {
    exploration: new ModelExplorationStrategy(uiOperations, messageBus),
    batch: new BatchGenerationStrategy(uiOperations, messageBus),
    processing: new ImageProcessingStrategy(uiOperations, messageBus),
    varying: new VaryingParametersStrategy(uiOperations, messageBus)
  };

  // Bridge MessageBus events to popup (unified across platforms)
  messageBus.subscribe('BEGIN_PROCESSING', (data) => {
    popupMessageSender({type: 'BEGIN_PROCESSING', ...data});
  });

  messageBus.subscribe('GENERATION_PROGRESS', (data) => {
    popupMessageSender({type: 'GENERATION_PROGRESS', ...data});
  });

  messageBus.subscribe('GENERATION_FINISHED', (data) => {
    popupMessageSender({type: 'GENERATION_FINISHED', ...data});
  });

  return strategies;
}
