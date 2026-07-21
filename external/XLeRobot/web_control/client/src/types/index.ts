export interface SocketStatus {
  socket: 'connected' | 'connecting' | 'disconnected' | 'error';
  video: 'connected' | 'connecting' | 'disconnected' | 'error' | 'streaming';
}

export interface SystemMessage {
  id: string;
  content: string;
  timestamp: number;
  type: 'info' | 'success' | 'warning' | 'error';
}
