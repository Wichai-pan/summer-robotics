import {
  useState,
  useRef,
  useEffect,
  useCallback,
  type MouseEvent as ReactMouseEvent,
  type TouchEvent as ReactTouchEvent
} from 'react';
import {
  ChevronUp,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Square,
  AlertTriangle,
  RotateCcw
} from 'lucide-react';
import { ENV } from '../../config/environment';
import { SPEED_LEVELS } from '../../config/constants';
import { formatTime } from '../../utils/format';

interface BottomControlConsoleProps {
  speedLevel: 'low' | 'medium' | 'high';
  onSpeedChange: (speed: 'low' | 'medium' | 'high') => void;
  onQuickMove: (direction: string) => void;
  onEmergencyStop: () => void;
  onResetCamera: () => void;
  telemetrySpeed: string;
  theme: 'light' | 'dark';
  connected: boolean;
}

interface JoystickPosition {
  x: number;
  y: number;
}

interface MovementState {
  isActive: boolean;
  direction: string | null;
}

export function BottomControlConsole({
  speedLevel,
  onSpeedChange,
  onQuickMove,
  onEmergencyStop,
  onResetCamera,
  telemetrySpeed,
  theme,
  connected
}: BottomControlConsoleProps) {
  const [joystickActive, setJoystickActive] = useState(false);
  const [joystickPosition, setJoystickPosition] = useState<JoystickPosition>({ x: 0, y: 0 });
  const [movementState, setMovementState] = useState<MovementState>({
    isActive: false,
    direction: null
  });

  const joystickRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);
  const movementIntervalRef = useRef<NodeJS.Timeout | null>(null);

  const startContinuousMovement = useCallback((direction: string) => {
    if (!connected) return;

    if (movementIntervalRef.current) {
      clearInterval(movementIntervalRef.current);
    }

    setMovementState({
      isActive: true,
      direction
    });

    onQuickMove(direction);

    movementIntervalRef.current = setInterval(() => {
      onQuickMove(direction);
    }, ENV.MOVEMENT_INTERVAL_MS);
  }, [connected, onQuickMove]);

  const stopContinuousMovement = useCallback(() => {
    if (movementIntervalRef.current) {
      clearInterval(movementIntervalRef.current);
      movementIntervalRef.current = null;
    }

    setMovementState({
      isActive: false,
      direction: null
    });

    // Send stop command
    if (connected) {
      onQuickMove('stop');
    }
  }, [connected, onQuickMove]);

  // Virtual joystick functionality with continuous control
  const updateJoystickPosition = useCallback((event: ReactMouseEvent | ReactTouchEvent | MouseEvent | TouchEvent) => {
    const rect = joystickRef.current?.getBoundingClientRect();
    if (!rect) return;

    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    const clientX = 'touches' in event ? event.touches[0].clientX : (event as MouseEvent).clientX;
    const clientY = 'touches' in event ? event.touches[0].clientY : (event as MouseEvent).clientY;

    const deltaX = clientX - centerX;
    const deltaY = clientY - centerY;

    const maxDistance = rect.width / 2 - 20;
    const distance = Math.sqrt(deltaX * deltaX + deltaY * deltaY);

    let finalX = deltaX;
    let finalY = deltaY;

    if (distance > maxDistance) {
      const angle = Math.atan2(deltaY, deltaX);
      finalX = Math.cos(angle) * maxDistance;
      finalY = Math.sin(angle) * maxDistance;
    }

    setJoystickPosition({ x: finalX, y: finalY });

    // Calculate direction based on joystick offset
    const normalizedX = finalX / maxDistance;
    const normalizedY = -finalY / maxDistance; // Invert Y for intuitive control
    const distanceRatio = Math.min(distance / maxDistance, 1.0);

    if (distanceRatio > ENV.JOYSTICK_DEAD_ZONE) {
      let direction = 'stop';
      if (Math.abs(normalizedY) > Math.abs(normalizedX)) {
        direction = normalizedY > 0 ? 'forward' : 'backward';
      } else {
        direction = normalizedX > 0 ? 'right' : 'left';
      }

      // Start or update continuous movement
      if (!movementState.isActive || movementState.direction !== direction) {
        startContinuousMovement(direction);
      }
    } else {
      // In dead zone, stop movement
      if (movementState.isActive) {
        stopContinuousMovement();
      }
    }
  }, [startContinuousMovement, stopContinuousMovement, movementState]);

  const handleJoystickStart = useCallback((event: ReactMouseEvent | ReactTouchEvent) => {
    if (!connected) return;

    setJoystickActive(true);
    isDraggingRef.current = true;
    updateJoystickPosition(event);
  }, [connected, updateJoystickPosition]);

  const handleJoystickMove = useCallback((event: MouseEvent | TouchEvent) => {
    if (!isDraggingRef.current || !connected) return;
    updateJoystickPosition(event);
  }, [connected, updateJoystickPosition]);

  const handleJoystickEnd = useCallback(() => {
    isDraggingRef.current = false;
    setJoystickActive(false);
    setJoystickPosition({ x: 0, y: 0 });
    stopContinuousMovement();
  }, [stopContinuousMovement]);

  // Direction button handlers with continuous control
  const handleButtonPress = useCallback((direction: string) => {
    if (!connected) return;
    startContinuousMovement(direction);
  }, [connected, startContinuousMovement]);

  const handleButtonRelease = useCallback(() => {
    stopContinuousMovement();
  }, [stopContinuousMovement]);

  useEffect(() => {
    if (isDraggingRef.current) {
      document.addEventListener('mousemove', handleJoystickMove);
      document.addEventListener('mouseup', handleJoystickEnd);
      document.addEventListener('touchmove', handleJoystickMove);
      document.addEventListener('touchend', handleJoystickEnd);
    }

    return () => {
      document.removeEventListener('mousemove', handleJoystickMove);
      document.removeEventListener('mouseup', handleJoystickEnd);
      document.removeEventListener('touchmove', handleJoystickMove);
      document.removeEventListener('touchend', handleJoystickEnd);
    };
  }, [handleJoystickMove, handleJoystickEnd]);

  // Cleanup movement intervals on unmount
  useEffect(() => {
    return () => {
      if (movementIntervalRef.current) {
        clearInterval(movementIntervalRef.current);
      }
    };
  }, []);

  // Auto-stop movement on disconnection
  useEffect(() => {
    if (!connected && movementState.isActive) {
      stopContinuousMovement();
    }
  }, [connected, movementState.isActive, stopContinuousMovement]);


  return (
    <div className={`fixed bottom-0 left-0 right-0 z-50 ${
      theme === 'dark' ? 'bg-gray-900/95' : 'bg-white/95'
    } backdrop-blur-sm border-t border-gray-200 dark:border-gray-700 shadow-xl`}>
      <div className="max-w-7xl mx-auto px-6 py-4">
        <div className="flex items-center justify-between">
          
          {/* Left Section - Speed Control */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-700 dark:text-gray-300">Speed:</span>
              <div className="flex bg-gray-200 dark:bg-gray-700 rounded-lg p-1">
                {(['low', 'medium', 'high'] as const).map((speed) => (
                  <button
                    key={speed}
                    onClick={() => onSpeedChange(speed)}
                    disabled={!connected}
                    className={`px-3 py-1 text-xs rounded-md transition-all ${
                      speedLevel === speed
                        ? `${SPEED_LEVELS[speed.toUpperCase() as keyof typeof SPEED_LEVELS].color} text-white shadow-sm`
                        : 'text-gray-600 dark:text-gray-400 hover:bg-white dark:hover:bg-gray-600'
                    } ${!connected ? 'opacity-50 cursor-not-allowed' : ''}`}
                  >
                    {SPEED_LEVELS[speed.toUpperCase() as keyof typeof SPEED_LEVELS].label}
                  </button>
                ))}
              </div>
            </div>
            
            <div className="text-sm text-gray-500 dark:text-gray-400">
              Current: <span className="font-mono text-blue-600 dark:text-blue-400">{telemetrySpeed}</span>
            </div>
          </div>

          {/* Center Section - Virtual Joystick */}
          <div className="flex items-center gap-8">
            
            {/* Directional Buttons */}
            <div className="grid grid-cols-3 gap-1">
              <div></div>
              <button
                onMouseDown={() => handleButtonPress('forward')}
                onMouseUp={handleButtonRelease}
                onMouseLeave={handleButtonRelease}
                onTouchStart={() => handleButtonPress('forward')}
                onTouchEnd={handleButtonRelease}
                disabled={!connected}
                className={`w-8 h-8 rounded-md transition-all ${
                  theme === 'dark' ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-200 hover:bg-gray-300'
                } flex items-center justify-center ${!connected ? 'opacity-50 cursor-not-allowed' : ''} ${
                  movementState.isActive && movementState.direction === 'forward' ? 'ring-2 ring-blue-500 bg-blue-600 text-white' : ''
                }`}
              >
                <ChevronUp size={16} />
              </button>
              <div></div>

              <button
                onMouseDown={() => handleButtonPress('left')}
                onMouseUp={handleButtonRelease}
                onMouseLeave={handleButtonRelease}
                onTouchStart={() => handleButtonPress('left')}
                onTouchEnd={handleButtonRelease}
                disabled={!connected}
                className={`w-8 h-8 rounded-md transition-all ${
                  theme === 'dark' ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-200 hover:bg-gray-300'
                } flex items-center justify-center ${!connected ? 'opacity-50 cursor-not-allowed' : ''} ${
                  movementState.isActive && movementState.direction === 'left' ? 'ring-2 ring-blue-500 bg-blue-600 text-white' : ''
                }`}
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={() => onQuickMove('stop')}
                disabled={!connected}
                className={`w-8 h-8 rounded-md transition-all ${
                  theme === 'dark' ? 'bg-gray-600 hover:bg-gray-500' : 'bg-gray-300 hover:bg-gray-400'
                } flex items-center justify-center text-xs ${!connected ? 'opacity-50 cursor-not-allowed' : ''}`}
              >
                <Square size={12} />
              </button>
              <button
                onMouseDown={() => handleButtonPress('right')}
                onMouseUp={handleButtonRelease}
                onMouseLeave={handleButtonRelease}
                onTouchStart={() => handleButtonPress('right')}
                onTouchEnd={handleButtonRelease}
                disabled={!connected}
                className={`w-8 h-8 rounded-md transition-all ${
                  theme === 'dark' ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-200 hover:bg-gray-300'
                } flex items-center justify-center ${!connected ? 'opacity-50 cursor-not-allowed' : ''} ${
                  movementState.isActive && movementState.direction === 'right' ? 'ring-2 ring-blue-500 bg-blue-600 text-white' : ''
                }`}
              >
                <ChevronRight size={16} />
              </button>

              <div></div>
              <button
                onMouseDown={() => handleButtonPress('backward')}
                onMouseUp={handleButtonRelease}
                onMouseLeave={handleButtonRelease}
                onTouchStart={() => handleButtonPress('backward')}
                onTouchEnd={handleButtonRelease}
                disabled={!connected}
                className={`w-8 h-8 rounded-md transition-all ${
                  theme === 'dark' ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-200 hover:bg-gray-300'
                } flex items-center justify-center ${!connected ? 'opacity-50 cursor-not-allowed' : ''} ${
                  movementState.isActive && movementState.direction === 'backward' ? 'ring-2 ring-blue-500 bg-blue-600 text-white' : ''
                }`}
              >
                <ChevronDown size={16} />
              </button>
              <div></div>
            </div>

            {/* Virtual Joystick */}
            <div className="relative">
              <div
                ref={joystickRef}
                className={`w-20 h-20 rounded-full border-4 ${
                  connected 
                    ? (theme === 'dark' ? 'border-gray-600 bg-gray-800' : 'border-gray-300 bg-gray-100')
                    : 'border-gray-400 bg-gray-200 opacity-50'
                } relative cursor-pointer select-none ${
                  joystickActive ? 'ring-2 ring-blue-500' : ''
                }`}
                onMouseDown={handleJoystickStart}
                onTouchStart={handleJoystickStart}
              >
                {/* Joystick Knob */}
                <div
                  className={`absolute w-6 h-6 rounded-full transition-all duration-75 ${
                    connected
                      ? (joystickActive ? 'bg-blue-500' : (theme === 'dark' ? 'bg-gray-400' : 'bg-gray-500'))
                      : 'bg-gray-400'
                  }`}
                  style={{
                    left: `calc(50% + ${joystickPosition.x}px - 12px)`,
                    top: `calc(50% + ${joystickPosition.y}px - 12px)`,
                  }}
                />
                
                {/* Center dot */}
                <div className={`absolute w-2 h-2 rounded-full top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 ${
                  theme === 'dark' ? 'bg-gray-500' : 'bg-gray-400'
                }`} />
              </div>
              
              <div className="text-xs text-center mt-2 text-gray-500 dark:text-gray-400">
                Virtual Joystick
              </div>
            </div>
          </div>

          {/* Right Section - Camera Reset & Emergency Stop */}
          <div className="flex items-center gap-4">
            <button
              onClick={onResetCamera}
              disabled={!connected}
              className={`flex items-center px-4 py-2 rounded-lg text-sm shadow-md transition-all transform hover:scale-105 active:scale-95 border-2 ${
                connected
                  ? 'bg-blue-600 hover:bg-blue-700 text-white border-blue-800'
                  : 'bg-gray-400 text-gray-600 border-gray-500 cursor-not-allowed opacity-50'
              }`}
            >
              <RotateCcw size={16} className="mr-2" />
              Reset Camera
            </button>

            <button
              onClick={onEmergencyStop}
              className="flex items-center bg-red-600 hover:bg-red-700 text-white px-6 py-3 rounded-lg font-bold text-lg shadow-lg transition-all transform hover:scale-105 active:scale-95 border-2 border-red-800"
            >
              <AlertTriangle size={20} className="mr-2" />
              Emergency Stop
            </button>
            
            <div className={`flex items-center gap-2 px-3 py-2 rounded-lg ${
              theme === 'dark' ? 'bg-gray-800' : 'bg-gray-100'
            }`}>
              <div className={`w-3 h-3 rounded-full ${
                connected ? 'bg-green-400 animate-pulse' : 'bg-red-500'
              }`} />
              <span className="text-xs text-gray-600 dark:text-gray-400">
                {connected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
          </div>
        </div>
        
        {/* Status Bar */}
        <div className={`mt-3 pt-3 border-t ${
          theme === 'dark' ? 'border-gray-700' : 'border-gray-200'
        }`}>
          <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
            <div className="flex items-center gap-4">
              <span>XLeRobot Console</span>
              <span>•</span>
              <span>Speed Level: {speedLevel.toUpperCase()}</span>
            </div>
            <div className="flex items-center gap-4">
              <span>Movement Control: {connected ? 'Available' : 'Unavailable'}</span>
              <span>•</span>
              <span>Current Time: {formatTime()}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
