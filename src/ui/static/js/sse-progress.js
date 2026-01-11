/**
 * SSE Progress Stream Handler
 *
 * Provides real-time task progress updates via Server-Sent Events.
 * Handles connection, reconnection, and UI updates.
 */

/**
 * Node type to display configuration mapping.
 * Maps agent node names to human-readable labels and colors.
 */
const NODE_CONFIG = {
    'start': { label: 'Start', color: 'gray', icon: 'play' },
    'parse_instruction': { label: 'Parse', color: 'purple', icon: 'document' },
    'compose_email': { label: 'Compose', color: 'blue', icon: 'pencil' },
    'send_email': { label: 'Send', color: 'green', icon: 'paper-airplane' },
    'wait_for_reply': { label: 'Wait', color: 'yellow', icon: 'clock' },
    'fetch_email': { label: 'Fetch', color: 'orange', icon: 'inbox' },
    'extract_content': { label: 'Extract', color: 'pink', icon: 'document-text' },
    'validate_response': { label: 'Validate', color: 'teal', icon: 'check-circle' },
    'decide_next': { label: 'Decide', color: 'indigo', icon: 'question' },
    'handle_success': { label: 'Success', color: 'emerald', icon: 'check' },
    'handle_failure': { label: 'Failed', color: 'red', icon: 'x-circle' },
};

/**
 * State to display configuration mapping.
 */
const STATE_CONFIG = {
    'created': { label: 'Created', color: 'gray' },
    'working': { label: 'Working', color: 'blue' },
    'suspended': { label: 'Waiting', color: 'yellow' },
    'resumed': { label: 'Resumed', color: 'blue' },
    'completed': { label: 'Completed', color: 'green' },
    'failed': { label: 'Failed', color: 'red' },
};

/**
 * TaskProgressStream - Handles SSE connection and progress events.
 */
class TaskProgressStream {
    /**
     * Create a new task progress stream.
     * @param {string} taskId - Task identifier
     * @param {string} containerId - ID of container element for progress entries
     * @param {Object} options - Configuration options
     */
    constructor(taskId, containerId, options = {}) {
        this.taskId = taskId;
        this.containerId = containerId;
        this.container = document.getElementById(containerId);

        if (!this.container) {
            throw new Error(`Container element not found: ${containerId}`);
        }

        this.options = {
            maxRetries: options.maxRetries || 5,
            initialDelay: options.initialDelay || 1000,
            maxDelay: options.maxDelay || 30000,
            showTimestamp: options.showTimestamp !== false,
            autoScroll: options.autoScroll !== false,
            onEvent: options.onEvent || null,
            onError: options.onError || null,
            onComplete: options.onComplete || null,
            onSuspended: options.onSuspended || null,
        };

        this.eventSource = null;
        this.retryCount = 0;
        this.retryDelay = this.options.initialDelay;
        this.lastEventId = null;
        this.isConnected = false;
        this.isStopped = false;
        this.seenEventIds = new Set();  // Track event IDs to prevent duplicates

        console.log(`TaskProgressStream initialized: taskId=${taskId}, containerId=${containerId}`);
    }

    /**
     * Connect to SSE stream.
     */
    connect() {
        if (this.isStopped) {
            console.log(`TaskProgressStream: Not connecting - stream stopped`);
            return;
        }

        if (this.eventSource) {
            this.eventSource.close();
        }

        let url = `/api/sse/task/${this.taskId}/progress`;

        console.log(`TaskProgressStream: Connecting to ${url}`);

        this.eventSource = new EventSource(url);

        // Handle connection open
        this.eventSource.onopen = () => {
            console.log(`TaskProgressStream: Connected`);
            this.isConnected = true;
            this.retryCount = 0;
            this.retryDelay = this.options.initialDelay;
            this._updateConnectionStatus(true);
        };

        // Handle progress events
        this.eventSource.addEventListener('progress', (event) => {
            this._handleEvent(event, 'progress');
        });

        // Handle suspended events
        this.eventSource.addEventListener('suspended', (event) => {
            this._handleEvent(event, 'suspended');
        });

        // Handle complete events
        this.eventSource.addEventListener('complete', (event) => {
            this._handleEvent(event, 'complete');
        });

        // Handle error events from server
        this.eventSource.addEventListener('error', (event) => {
            // Check if it's a server-sent error event
            if (event.data) {
                this._handleEvent(event, 'error');
            } else {
                // Connection error
                this._handleConnectionError(event);
            }
        });

        // Handle generic messages
        this.eventSource.onmessage = (event) => {
            this._handleEvent(event, 'message');
        };
    }

    /**
     * Disconnect from SSE stream.
     */
    disconnect() {
        console.log(`TaskProgressStream: Disconnecting`);
        this.isStopped = true;

        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }

        this.seenEventIds.clear();  // Clear dedup cache on disconnect
        this.isConnected = false;
        this._updateConnectionStatus(false);
    }

    /**
     * Handle incoming event.
     * @private
     */
    _handleEvent(event, eventType) {
        try {
            const data = JSON.parse(event.data);
            console.log(`TaskProgressStream: Event received - type=${eventType}, state=${data.state}`);

            // Generate event identifier for deduplication
            const eventId = this._getEventIdentifier(data, event);

            // Skip if we've already processed this event
            if (this.seenEventIds.has(eventId)) {
                console.log(`TaskProgressStream: Skipping duplicate event - id=${eventId}`);
                return;  // Early return - do not process duplicate
            }

            // Mark this event as seen
            this.seenEventIds.add(eventId);

            // Update last event ID
            if (event.lastEventId) {
                this.lastEventId = event.lastEventId;
            }

            // Add progress entry to UI
            this._addProgressEntry(data, eventType);

            // Call event callback
            if (this.options.onEvent) {
                this.options.onEvent(data, eventType);
            }

            // Handle terminal states
            if (data.state === 'completed') {
                this._handleCompletion(data);
            } else if (data.state === 'failed') {
                this._handleFailure(data);
            } else if (data.state === 'suspended') {
                this._handleSuspension(data);
            }

        } catch (e) {
            console.error(`TaskProgressStream: Error parsing event:`, e, event.data);
        }
    }

    /**
     * Handle connection error with retry logic.
     * @private
     */
    _handleConnectionError(event) {
        console.warn(`TaskProgressStream: Connection error`);
        this.isConnected = false;
        this._updateConnectionStatus(false);

        // Check if we've been stopped
        if (this.isStopped) {
            return;
        }

        // Check retry limit
        if (this.retryCount >= this.options.maxRetries) {
            console.error(`TaskProgressStream: Max retries exceeded`);
            if (this.options.onError) {
                this.options.onError(new Error('Connection failed after max retries'));
            }
            this._showErrorMessage('Connection lost. Please refresh the page.');
            return;
        }

        // Schedule retry with exponential backoff
        this.retryCount++;
        console.log(`TaskProgressStream: Retrying in ${this.retryDelay}ms (attempt ${this.retryCount}/${this.options.maxRetries})`);

        setTimeout(() => {
            if (!this.isStopped) {
                this.connect();
            }
        }, this.retryDelay);

        // Exponential backoff
        this.retryDelay = Math.min(this.retryDelay * 2, this.options.maxDelay);
    }

    /**
     * Handle task completion.
     * @private
     */
    _handleCompletion(data) {
        console.log(`TaskProgressStream: Task completed`);
        this.disconnect();

        if (this.options.onComplete) {
            this.options.onComplete(data);
        }
    }

    /**
     * Handle task failure.
     * @private
     */
    _handleFailure(data) {
        console.log(`TaskProgressStream: Task failed`);
        this.disconnect();

        if (this.options.onError) {
            this.options.onError(new Error(data.error || data.message));
        }
    }

    /**
     * Handle task suspension (waiting for reply).
     * @private
     */
    _handleSuspension(data) {
        console.log(`TaskProgressStream: Task suspended, waiting for ${data.poc_email}`);
        // Don't disconnect - keep listening for resume

        if (this.options.onSuspended) {
            this.options.onSuspended(data);
        }
    }

    /**
     * Add progress entry to container.
     * @private
     */
    _addProgressEntry(data, eventType) {
        const entry = document.createElement('div');
        entry.className = 'flex items-start space-x-3 p-2 bg-gray-50 rounded mb-2 animate-fadeIn';

        // Get node configuration (fall back to state config if node is missing)
        const nodeConfig = NODE_CONFIG[data.node] || STATE_CONFIG[data.state] || { label: data.state || 'Unknown', color: 'gray' };
        const stateConfig = STATE_CONFIG[data.state] || { label: data.state, color: 'gray' };

        // Build entry HTML
        let html = '';

        // Node badge
        html += `<span class="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-${nodeConfig.color}-100 text-${nodeConfig.color}-800">`;
        html += nodeConfig.label;
        html += '</span>';

        // Message
        html += `<span class="flex-1 text-sm text-gray-700">${this._escapeHtml(data.message)}</span>`;

        // Timestamp
        if (this.options.showTimestamp && data.timestamp) {
            const time = new Date(data.timestamp).toLocaleTimeString();
            html += `<span class="text-xs text-gray-400">${time}</span>`;
        }

        entry.innerHTML = html;

        // Add to container
        this.container.appendChild(entry);

        // Auto-scroll
        if (this.options.autoScroll) {
            entry.scrollIntoView({ behavior: 'smooth', block: 'end' });
        }
    }

    /**
     * Show error message in container.
     * @private
     */
    _showErrorMessage(message) {
        const entry = document.createElement('div');
        entry.className = 'flex items-center space-x-2 p-3 bg-red-50 border border-red-200 rounded text-red-700 mb-2';
        entry.innerHTML = `
            <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20">
                <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/>
            </svg>
            <span>${this._escapeHtml(message)}</span>
        `;
        this.container.appendChild(entry);
    }

    /**
     * Update connection status indicator.
     * @private
     */
    _updateConnectionStatus(connected) {
        const statusEl = document.getElementById('sse-status');
        if (statusEl) {
            if (connected) {
                statusEl.textContent = 'Connected';
                statusEl.className = 'text-green-600';
            } else {
                statusEl.textContent = 'Disconnected';
                statusEl.className = 'text-red-600';
            }
        }
    }

    /**
     * Escape HTML special characters.
     * @private
     */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Generate a unique identifier for deduplication.
     * Uses event_id if available, otherwise falls back to content hash.
     * @private
     */
    _getEventIdentifier(data, event) {
        // Prefer event_id from SSE lastEventId
        if (event.lastEventId) {
            return `sse-${event.lastEventId}`;
        }

        // Prefer event_id from data payload
        if (data.event_id !== undefined && data.event_id !== null) {
            return `data-${data.event_id}`;
        }

        // Fallback: Content-based hash for events without IDs
        const contentKey = `${data.state}-${data.node || 'none'}-${data.message}`;
        return `content-${this._hashCode(contentKey)}`;
    }

    /**
     * Simple hash function for string content.
     * @private
     */
    _hashCode(str) {
        let hash = 0;
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return hash.toString(16);
    }
}

/**
 * Initialize progress stream for a task.
 *
 * @param {string} taskId - Task identifier
 * @param {string} containerId - Container element ID
 * @param {Object} options - Configuration options
 * @returns {TaskProgressStream} Stream instance
 */
function initTaskProgress(taskId, containerId, options = {}) {
    const stream = new TaskProgressStream(taskId, containerId, options);
    stream.connect();
    return stream;
}

// Export for use in templates
window.TaskProgressStream = TaskProgressStream;
window.initTaskProgress = initTaskProgress;
