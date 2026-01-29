import { useEffect, useRef } from 'react';

interface WebSocketMessage {
    type: string;
    doc_id: string;
    status: string;
    filename: string;
}

interface UseWebSocketProps {
    kbId: string | undefined;
    onMessage?: (message: WebSocketMessage) => void;
    enabled?: boolean;
}

export function useWebSocket({ kbId, onMessage, enabled = true }: UseWebSocketProps) {
    const wsRef = useRef<WebSocket | null>(null);
    const onMessageRef = useRef(onMessage);
    const kbIdRef = useRef(kbId);
    const enabledRef = useRef(enabled);

    // Keep refs updated without triggering re-renders
    onMessageRef.current = onMessage;
    kbIdRef.current = kbId;
    enabledRef.current = enabled;

    useEffect(() => {
        if (!kbId || !enabled) return;

        let reconnectTimeout: number | undefined;
        let reconnectAttempts = 0;
        const MAX_RECONNECT_ATTEMPTS = 5;
        const RECONNECT_DELAY = 2000;

        const connect = () => {
            if (!kbIdRef.current || !enabledRef.current) return;

            try {
                if (wsRef.current) {
                    wsRef.current.close();
                }

                const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                const wsUrl = `${protocol}//localhost:8000/api/ws/${kbIdRef.current}`;

                console.log(`[WebSocket] Connecting to ${wsUrl}`);
                const ws = new WebSocket(wsUrl);

                ws.onopen = () => {
                    console.log('[WebSocket] Connected');
                    reconnectAttempts = 0;
                };

                ws.onmessage = (event) => {
                    try {
                        const message: WebSocketMessage = JSON.parse(event.data);
                        console.log('[WebSocket] Message received:', message);
                        onMessageRef.current?.(message);
                    } catch (error) {
                        console.error('[WebSocket] Error parsing message:', error);
                    }
                };

                ws.onerror = (error) => {
                    console.error('[WebSocket] Error:', error);
                };

                ws.onclose = () => {
                    console.log('[WebSocket] Disconnected');
                    wsRef.current = null;

                    if (enabledRef.current && reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
                        reconnectAttempts += 1;
                        console.log(`[WebSocket] Reconnecting in ${RECONNECT_DELAY}ms`);
                        reconnectTimeout = window.setTimeout(connect, RECONNECT_DELAY);
                    }
                };

                wsRef.current = ws;
            } catch (error) {
                console.error('[WebSocket] Connection error:', error);
            }
        };

        connect();

        return () => {
            if (reconnectTimeout) {
                clearTimeout(reconnectTimeout);
            }
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
        };
    }, [kbId, enabled]);
}
