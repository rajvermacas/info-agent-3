/**
 * DAG Visualization Handler with SSE Integration
 *
 * Provides real-time updates to the POC dependency graph via SSE events.
 * Integrates with Cytoscape.js for dynamic graph updates.
 */

/**
 * Status to color mapping for POC nodes.
 */
const POC_STATUS_COLORS = {
    'pending': '#9ca3af',      // gray-400
    'in_progress': '#3b82f6',  // blue-500
    'waiting': '#eab308',      // yellow-500
    'completed': '#22c55e',    // green-500
    'failed': '#ef4444',       // red-500
};

/**
 * DAGStream - Handles SSE connection for real-time DAG updates.
 */
class DAGStream {
    /**
     * Create a new DAG stream.
     * @param {string} taskId - Task identifier
     * @param {Object} options - Configuration options
     */
    constructor(taskId, options = {}) {
        this.taskId = taskId;
        this.options = {
            pollInterval: options.pollInterval || 5000,
            maxRetries: options.maxRetries || 5,
            onUpdate: options.onUpdate || null,
            onError: options.onError || null,
            onComplete: options.onComplete || null,
        };

        this.eventSource = null;
        this.pollTimer = null;
        this.retryCount = 0;
        this.isConnected = false;
        this.isStopped = false;
        this.cyInstance = null;

        console.log(`DAGStream initialized for task: ${taskId}`);
    }

    /**
     * Set the Cytoscape instance for direct updates.
     * @param {Object} cy - Cytoscape instance
     */
    setCytoscapeInstance(cy) {
        this.cyInstance = cy;
    }

    /**
     * Connect to SSE stream for DAG updates.
     * Falls back to polling if SSE is not available.
     */
    connect() {
        if (this.isStopped) {
            console.log('DAGStream: Not connecting - stream stopped');
            return;
        }

        // Try SSE connection
        this._connectSSE();
    }

    /**
     * Connect to SSE stream.
     * @private
     */
    _connectSSE() {
        const url = `/api/sse/task/${this.taskId}/progress`;
        console.log(`DAGStream: Connecting to SSE at ${url}`);

        this.eventSource = new EventSource(url);

        this.eventSource.onopen = () => {
            console.log('DAGStream: SSE connected');
            this.isConnected = true;
            this.retryCount = 0;
        };

        // Listen for dag_updated events
        this.eventSource.addEventListener('dag_updated', (event) => {
            this._handleDAGUpdate(event);
        });

        // Listen for POC-level events that affect the DAG
        const pocEvents = [
            'poc_started', 'poc_email_sent', 'poc_waiting',
            'poc_reply_received', 'poc_validated', 'poc_retry',
            'poc_redirect', 'poc_completed', 'poc_failed',
            'dynamic_pocs_spawned',
        ];

        pocEvents.forEach(eventType => {
            this.eventSource.addEventListener(eventType, (event) => {
                this._handlePOCEvent(event, eventType);
            });
        });

        // Handle standard progress events
        this.eventSource.addEventListener('progress', (event) => {
            this._handleProgressEvent(event);
        });

        // Handle completion
        this.eventSource.addEventListener('complete', (event) => {
            this._handleCompletion(event);
        });

        // Handle errors
        this.eventSource.onerror = (event) => {
            this._handleSSEError(event);
        };
    }

    /**
     * Handle DAG update event.
     * @private
     */
    _handleDAGUpdate(event) {
        try {
            const data = JSON.parse(event.data);
            console.log('DAGStream: DAG update received', data);

            if (this.cyInstance) {
                this._updateCytoscape(data);
            }

            if (this.options.onUpdate) {
                this.options.onUpdate(data, 'dag_updated');
            }
        } catch (e) {
            console.error('DAGStream: Error handling DAG update:', e);
        }
    }

    /**
     * Handle POC-level event.
     * @private
     */
    _handlePOCEvent(event, eventType) {
        try {
            const data = JSON.parse(event.data);
            console.log(`DAGStream: POC event [${eventType}]:`, data);

            // Update node status if we have POC info
            if (data.poc_id && this.cyInstance) {
                this._updateNodeStatus(data.poc_id, data);
            }

            // Trigger update callback
            if (this.options.onUpdate) {
                this.options.onUpdate(data, eventType);
            }

            // Fetch full DAG for dynamic POC spawns
            if (eventType === 'dynamic_pocs_spawned') {
                this._refreshDAG();
            }
        } catch (e) {
            console.error('DAGStream: Error handling POC event:', e);
        }
    }

    /**
     * Handle standard progress event.
     * @private
     */
    _handleProgressEvent(event) {
        try {
            const data = JSON.parse(event.data);

            // Update progress indicators if available
            if (data.poc_progress) {
                this._updateProgressIndicators(data.poc_progress);
            }

            // Update phase if available
            if (data.phase) {
                this._updatePhase(data.phase);
            }
        } catch (e) {
            console.error('DAGStream: Error handling progress event:', e);
        }
    }

    /**
     * Handle task completion.
     * @private
     */
    _handleCompletion(event) {
        console.log('DAGStream: Task completed');
        this.disconnect();

        if (this.options.onComplete) {
            try {
                const data = JSON.parse(event.data);
                this.options.onComplete(data);
            } catch (e) {
                this.options.onComplete({});
            }
        }
    }

    /**
     * Handle SSE error with retry/fallback logic.
     * @private
     */
    _handleSSEError(event) {
        console.warn('DAGStream: SSE error');
        this.isConnected = false;

        if (this.isStopped) return;

        // Check retry limit
        if (this.retryCount >= this.options.maxRetries) {
            console.log('DAGStream: Max retries exceeded, falling back to polling');
            this._startPolling();
            return;
        }

        // Retry SSE connection
        this.retryCount++;
        const delay = Math.min(1000 * Math.pow(2, this.retryCount), 30000);
        console.log(`DAGStream: Retrying SSE in ${delay}ms (attempt ${this.retryCount})`);

        setTimeout(() => {
            if (!this.isStopped) {
                this._connectSSE();
            }
        }, delay);
    }

    /**
     * Start polling for DAG updates (fallback).
     * @private
     */
    _startPolling() {
        if (this.pollTimer) return;

        console.log(`DAGStream: Starting polling with interval ${this.options.pollInterval}ms`);

        const poll = async () => {
            if (this.isStopped) return;

            try {
                await this._refreshDAG();
            } catch (e) {
                console.error('DAGStream: Polling error:', e);
            }

            this.pollTimer = setTimeout(poll, this.options.pollInterval);
        };

        poll();
    }

    /**
     * Refresh DAG data from server.
     * @private
     */
    async _refreshDAG() {
        const url = `/api/dashboard/task/${this.taskId}/dag/data`;

        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }

            const data = await response.json();
            console.log('DAGStream: DAG refreshed', data);

            if (this.cyInstance) {
                this._updateCytoscape(data);
            }

            if (this.options.onUpdate) {
                this.options.onUpdate(data, 'refresh');
            }
        } catch (e) {
            console.error('DAGStream: Error refreshing DAG:', e);
        }
    }

    /**
     * Update Cytoscape graph with new data.
     * @private
     */
    _updateCytoscape(dagData) {
        if (!this.cyInstance || !dagData.nodes) return;

        const cy = this.cyInstance;

        // Update existing nodes and add new ones
        dagData.nodes.forEach(nodeData => {
            const node = cy.getElementById(nodeData.id);

            if (node.length > 0) {
                // Update existing node
                node.data('status', nodeData.status);
                node.data('attempts', nodeData.attempts || 0);
                node.data('isDynamic', nodeData.is_dynamic);
            } else {
                // Add new node
                cy.add({
                    data: {
                        id: nodeData.id,
                        label: nodeData.label || nodeData.email,
                        email: nodeData.email,
                        status: nodeData.status,
                        isDynamic: nodeData.is_dynamic,
                        attempts: nodeData.attempts || 0,
                        maxAttempts: nodeData.max_attempts || 15,
                    },
                });
            }
        });

        // Add new edges
        if (dagData.edges) {
            dagData.edges.forEach(edgeData => {
                const edgeId = `${edgeData.source}->${edgeData.target}`;
                if (cy.getElementById(edgeId).length === 0) {
                    cy.add({
                        data: {
                            id: edgeId,
                            source: edgeData.source,
                            target: edgeData.target,
                        },
                    });
                }
            });
        }

        // Re-run layout if structure changed
        cy.layout({
            name: 'dagre',
            rankDir: 'TB',
            animate: true,
            animationDuration: 300,
        }).run();

        // Update style (force re-render)
        cy.style().update();
    }

    /**
     * Update single node status.
     * @private
     */
    _updateNodeStatus(pocId, data) {
        if (!this.cyInstance) return;

        const node = this.cyInstance.getElementById(pocId);
        if (node.length === 0) return;

        // Map event types to statuses
        const eventToStatus = {
            'poc_started': 'in_progress',
            'poc_email_sent': 'in_progress',
            'poc_waiting': 'waiting',
            'poc_reply_received': 'in_progress',
            'poc_validated': 'in_progress',
            'poc_retry': 'in_progress',
            'poc_redirect': 'in_progress',
            'poc_completed': 'completed',
            'poc_failed': 'failed',
        };

        const newStatus = data.status || eventToStatus[data.event_type] || node.data('status');
        node.data('status', newStatus);

        if (data.attempts !== undefined) {
            node.data('attempts', data.attempts);
        }

        // Force style update
        this.cyInstance.style().update();
    }

    /**
     * Update progress indicators in the UI.
     * @private
     */
    _updateProgressIndicators(progress) {
        // Update progress summary elements if they exist
        const container = document.getElementById(`dag-container-${this.taskId}`);
        if (!container) return;

        // This is a basic implementation - could be enhanced with more DOM updates
        console.log('DAGStream: Progress update:', progress);
    }

    /**
     * Update phase indicator in the UI.
     * @private
     */
    _updatePhase(phase) {
        const phaseEl = document.getElementById(`dag-phase-${this.taskId}`);
        if (phaseEl) {
            phaseEl.textContent = phase.charAt(0).toUpperCase() + phase.slice(1);
        }
    }

    /**
     * Disconnect from stream.
     */
    disconnect() {
        console.log('DAGStream: Disconnecting');
        this.isStopped = true;

        if (this.eventSource) {
            this.eventSource.close();
            this.eventSource = null;
        }

        if (this.pollTimer) {
            clearTimeout(this.pollTimer);
            this.pollTimer = null;
        }

        this.isConnected = false;
    }
}

/**
 * Initialize DAG with SSE streaming.
 *
 * @param {string} taskId - Task identifier
 * @param {Object} cyInstance - Cytoscape instance
 * @param {Object} options - Configuration options
 * @returns {DAGStream} Stream instance
 */
function initDAGStream(taskId, cyInstance, options = {}) {
    const stream = new DAGStream(taskId, options);
    stream.setCytoscapeInstance(cyInstance);
    stream.connect();
    return stream;
}

// Export for use in templates
window.DAGStream = DAGStream;
window.initDAGStream = initDAGStream;
window.POC_STATUS_COLORS = POC_STATUS_COLORS;
