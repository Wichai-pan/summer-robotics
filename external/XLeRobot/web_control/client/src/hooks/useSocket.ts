import { useEffect, useState, useCallback, useRef } from 'react';
import { io, Socket } from 'socket.io-client';
import type { SocketStatus, SystemMessage } from '../types';
import { ENV } from '../config/environment';
import { KEY_TO_DIRECTION, MESSAGE_TYPES } from '../config/constants';

interface RobotTelemetry {
  battery: string | null;
  temp: string | null;
  speed: string | null;
  voltage: string | null;
}

interface NetworkMetrics {
  latency: number | null;
  fps: number | null;
}

interface ArmPositions {
  angles: number[] | null;
}

export const useSocket = () => {
  const [socket, setSocket] = useState<Socket | null>(null);
  const [status, setStatus] = useState<SocketStatus>({
    socket: 'disconnected',
    video: 'disconnected'
  });
  const [messages, setMessages] = useState<SystemMessage[]>([]);

  const [telemetry, setTelemetry] = useState<RobotTelemetry>({
    battery: null,
    temp: null,
    speed: null,
    voltage: null
  });
  
  const [networkMetrics, setNetworkMetrics] = useState<NetworkMetrics>({
    latency: null,
    fps: null
  });
  
  const [armPositions, setArmPositions] = useState<ArmPositions>({
    angles: null
  });

  const [pressedKeys, setPressedKeys] = useState<Set<string>>(new Set());
  const continuousIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const pressedKeysRef = useRef<Set<string>>(new Set());


  const addMessage = useCallback((content: string, type: SystemMessage['type'] = MESSAGE_TYPES.INFO) => {
    const message: SystemMessage = {
      id: Date.now().toString(),
      content,
      timestamp: Date.now(),
      type
    };
    setMessages(prev => [...prev.slice(-(ENV.LOG_MAX_ENTRIES - 1)), message]);
  }, []);

  useEffect(() => {
    const newSocket = io(ENV.SERVER_URL, {
      transports: ['websocket'],
      reconnection: ENV.SOCKET_RECONNECTION,
      reconnectionDelay: ENV.SOCKET_RECONNECTION_DELAY,
      reconnectionAttempts: ENV.SOCKET_RECONNECTION_ATTEMPTS,
    });

    newSocket.on('connect', () => {
      setStatus(prev => ({ ...prev, socket: 'connected' }));
      addMessage(`Connected to server (ID: ${newSocket.id})`, MESSAGE_TYPES.SUCCESS);
    });

    newSocket.on('disconnect', () => {
      setStatus(prev => ({ ...prev, socket: 'disconnected' }));
      addMessage('Disconnected from server', MESSAGE_TYPES.WARNING);
    });

    newSocket.on('connect_error', (error) => {
      setStatus(prev => ({ ...prev, socket: 'error' }));
      addMessage(`Connection error: ${error.message}`, MESSAGE_TYPES.ERROR);
    });

    newSocket.on('connection_established', (data) => {
      addMessage(data.message, MESSAGE_TYPES.SUCCESS);
    });



    newSocket.on('stream_status', (data) => {
      if (data.status === 'streaming_started') {
        setStatus(prev => ({ ...prev, video: 'streaming' }));
        addMessage('Video stream started successfully', MESSAGE_TYPES.SUCCESS);
      } else if (data.status === 'streaming_stopped') {
        setStatus(prev => ({ ...prev, video: 'disconnected' }));
        addMessage('Video stream stopped', MESSAGE_TYPES.INFO);
      }
    });

    newSocket.on('video_stream_error', (error) => {
      setStatus(prev => ({ ...prev, video: 'error' }));
      addMessage(`Video stream error: ${error.message || error}`, MESSAGE_TYPES.ERROR);
    });


    newSocket.on('telemetry_update', (data) => {
      setTelemetry({
        battery: data.battery || null,
        temp: data.temperature || null,
        speed: data.speed || null,
        voltage: data.voltage || null
      });
    });

    newSocket.on('network_metrics', (data) => {
      setNetworkMetrics({
        latency: data.latency || null,
        fps: data.fps || null
      });
    });

    newSocket.on('arm_position_update', (data) => {
      setArmPositions({
        angles: data.angles || null
      });
    });

    newSocket.on('camera_action_result', (data) => {
      if (data.action === 'reset') {
        const msg = data.status === 'success'
          ? 'Camera reset successful'
          : `Camera reset failed: ${data.message || 'Unknown error'}`;
        addMessage(msg, data.status === 'success' ? MESSAGE_TYPES.SUCCESS : MESSAGE_TYPES.ERROR);
      }
    });

    setSocket(newSocket);

    return () => {
      newSocket.close();
    };
  }, [addMessage]);

  const startContinuousMovement = useCallback(() => {
    if (continuousIntervalRef.current) {
      clearInterval(continuousIntervalRef.current);
    }

    continuousIntervalRef.current = setInterval(() => {
      const currentKeys = pressedKeysRef.current;
      if (currentKeys.size === 0) return;

      const keysArray = Array.from(currentKeys);
      const primaryKey = keysArray[keysArray.length - 1];
      const direction = KEY_TO_DIRECTION[primaryKey];

      if (direction && socket && status.socket === 'connected') {
        socket.emit('move_command', { direction, speed: ENV.DEFAULT_SPEED });
      }
    }, ENV.MOVEMENT_INTERVAL_MS);
  }, [socket, status.socket]);

  const stopContinuousMovement = useCallback(() => {
    if (continuousIntervalRef.current) {
      clearInterval(continuousIntervalRef.current);
      continuousIntervalRef.current = null;
    }

    if (socket && status.socket === 'connected') {
      socket.emit('move_command', { direction: 'stop', speed: 0 });
    }
  }, [socket, status.socket]);

  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    const key = event.key;

    if (!KEY_TO_DIRECTION[key]) return;

    event.preventDefault();

    if (pressedKeysRef.current.has(key)) return;

    pressedKeysRef.current.add(key);
    setPressedKeys(new Set(pressedKeysRef.current));

    if (pressedKeysRef.current.size === 1) {
      startContinuousMovement();
    }
  }, [startContinuousMovement]);

  const handleKeyUp = useCallback((event: KeyboardEvent) => {
    const key = event.key;

    if (!KEY_TO_DIRECTION[key]) return;

    event.preventDefault();

    pressedKeysRef.current.delete(key);
    setPressedKeys(new Set(pressedKeysRef.current));

    if (pressedKeysRef.current.size === 0) {
      stopContinuousMovement();
    }
  }, [stopContinuousMovement]);

  useEffect(() => {
    if (status.socket === 'connected') {
      window.addEventListener('keydown', handleKeyDown);
      window.addEventListener('keyup', handleKeyUp);

      return () => {
        window.removeEventListener('keydown', handleKeyDown);
        window.removeEventListener('keyup', handleKeyUp);

        if (continuousIntervalRef.current) {
          clearInterval(continuousIntervalRef.current);
          continuousIntervalRef.current = null;
        }

        pressedKeysRef.current.clear();
        setPressedKeys(new Set());
      };
    }
  }, [status.socket, handleKeyDown, handleKeyUp]);

  const sendPing = useCallback(() => {
    if (socket && status.socket === 'connected') {
      const timestamp = Date.now();
      socket.emit('ping', { timestamp, message: 'ping from client' });
      addMessage(`Sent Ping (timestamp: ${timestamp})`, MESSAGE_TYPES.INFO);
    }
  }, [socket, status.socket]);

  const sendMoveCommand = useCallback((direction: string, speed = 1.0) => {
    if (socket && status.socket === 'connected') {
      socket.emit('move_command', { direction, speed });
    }
  }, [socket, status.socket]);

  const startVideoStream = useCallback(() => {
    if (socket && status.socket === 'connected') {
      socket.emit('start_video_stream');
      setStatus(prev => ({ ...prev, video: 'connecting' }));
      addMessage('Starting video stream', MESSAGE_TYPES.INFO);
    }
  }, [socket, status.socket]);

  const stopVideoStream = useCallback(() => {
    if (socket && status.socket === 'connected') {
      socket.emit('stop_video_stream');
      setStatus(prev => ({ ...prev, video: 'disconnected' }));
      addMessage('Stopping video stream', MESSAGE_TYPES.INFO);
    }
  }, [socket, status.socket]);

  return {
    socket,
    status,
    messages,
    sendPing,
    sendMoveCommand,
    startVideoStream,
    stopVideoStream,
    telemetry,
    networkMetrics,
    armPositions,
    pressedKeys,
    stopContinuousMovement,
  };
};
