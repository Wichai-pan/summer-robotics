import { useState, useEffect } from 'react';
import { Moon, Sun, Radio } from 'lucide-react';
import { useSocket } from './hooks/useSocket';
import { RobotVideoCanvas } from './components/features/RobotVideoCanvas';
import { MultiTabPanel } from './components/features/MultiTabPanel';
import { BottomControlConsole } from './components/features/BottomControlConsole';
import { formatValue, formatLatency } from './utils/format';
import { STATUS_COLORS, SPEED_LEVELS } from './config/constants';

export default function App() {
  const {
    socket,
    status,
    messages,
    sendPing,
    sendMoveCommand,
    startVideoStream,
    stopVideoStream,
    telemetry: realTelemetry,
    networkMetrics,
    armPositions,
    pressedKeys,
    stopContinuousMovement
  } = useSocket();

  const [theme, setTheme] = useState<'light' | 'dark'>('light');
  const [speedLevel, setSpeedLevel] = useState<'low' | 'medium' | 'high'>('medium');
  const [recording, setRecording] = useState(false);

  const displayTelemetry = {
    battery: formatValue(realTelemetry.battery),
    speed: formatValue(realTelemetry.speed),
    temp: formatValue(realTelemetry.temp),
    voltage: formatValue(realTelemetry.voltage)
  };

  const displayLatency = formatValue(networkMetrics.latency);
  const displayFps = formatValue(networkMetrics.fps);
  const displayArmAngles = Array.isArray(armPositions.angles) ? armPositions.angles : [];

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    if (theme === 'dark') {
      document.body.classList.add('dark');
    } else {
      document.body.classList.remove('dark');
    }
  }, [theme]);

  const handleQuickMove = (direction: string) => {
    const speedMultiplier = direction === 'stop'
      ? 0
      : SPEED_LEVELS[speedLevel.toUpperCase() as keyof typeof SPEED_LEVELS].value;

    sendMoveCommand(direction, speedMultiplier);
  };

  const handleEmergencyStop = () => {
    stopContinuousMovement();
    sendMoveCommand('stop', 0);
  };

  const handleResetCamera = () => {
    if (socket) {
      socket.emit('reset_camera');
    }
  };


  const toggleRecording = () => {
    setRecording(prev => !prev);
  };

  const toggleVideoStream = () => {
    if (status.video === 'streaming') {
      stopVideoStream();
    } else {
      startVideoStream();
    }
  };

  return (
    <div className={`min-h-screen transition-colors duration-200 ${
      theme === 'dark' ? 'bg-gray-900 text-gray-100' : 'bg-gray-50 text-gray-900'
    }`}>
      <div className="max-w-7xl mx-auto px-6 py-6">
        {/* Header */}
        <header className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <h1 className="text-2xl font-bold">XLeRobot Control Console</h1>
            <div className="text-sm text-gray-500">
              Session: <span className="font-mono">DEFAULT</span>
            </div>
          </div>

          <div className="flex items-center gap-6">
            {/* Status Panel */}
            <div className={`flex items-center gap-3 p-3 rounded-lg shadow-sm ${
              theme === 'dark' ? 'bg-gray-800' : 'bg-white/80'
            }`}>
              <div className={`w-3 h-3 rounded-full ${STATUS_COLORS[status.socket] || 'bg-gray-400'}`} />
              <div className="text-xs">
                Socket: <span className="font-medium">{status.socket}</span>
              </div>
              <div className="text-xs pl-4 border-l border-gray-200">
                Video: <span className="font-medium">{status.video}</span>
              </div>
              <div className="text-xs pl-4 border-l border-gray-200">
                Latency: <span className="font-mono">{formatLatency(displayLatency)}</span>
              </div>
              {pressedKeys.size > 0 && (
                <div className="text-xs pl-4 border-l border-green-300">
                  <div className="flex items-center gap-1">
                    <div className="w-2 h-2 bg-green-400 rounded-full animate-pulse"></div>
                    <span className="text-green-600 font-medium">
                      Keys: {Array.from(pressedKeys).join(', ')}
                    </span>
                  </div>
                </div>
              )}
            </div>

            <div className="flex items-center gap-2">
              <button
                onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
                className={`flex items-center gap-2 px-3 py-2 rounded-md shadow-sm text-sm transition-colors ${
                  theme === 'dark' ? 'bg-gray-800 hover:bg-gray-700' : 'bg-white/80 hover:bg-white'
                }`}
              >
                {theme === 'light' ? (
                  <>
                    <Moon size={16} />
                    Dark
                  </>
                ) : (
                  <>
                    <Sun size={16} />
                    Light
                  </>
                )}
              </button>
              <button 
                onClick={sendPing}
                className={`flex items-center gap-2 px-3 py-2 rounded-md shadow-sm text-sm transition-colors ${
                  theme === 'dark' ? 'bg-gray-800 hover:bg-gray-700' : 'bg-white/80 hover:bg-white'
                }`}
              >
                <Radio size={16} />
                Ping
              </button>
            </div>
          </div>
        </header>

        {/* Main Layout - 7:5 ratio */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Video Stream Area - 7 columns */}
          <div className="lg:col-span-7">
            <RobotVideoCanvas
              socket={socket}
              videoStatus={status.video}
              telemetry={displayTelemetry}
              latency={displayLatency}
              fps={displayFps}
              recording={recording}
              onToggleRecording={toggleRecording}
              onToggleVideoStream={toggleVideoStream}
            />
            <div className="mt-3 text-xs text-gray-500">
              <strong>Keyboard:</strong> WASD/Arrow Keys for movement, Q/E for rotation. Hold for continuous movement.
            </div>
          </div>

          {/* Side Panel - 5 columns */}
          <div className="lg:col-span-5">
            <MultiTabPanel
              telemetry={displayTelemetry}
              armAngles={displayArmAngles}
              latency={displayLatency}
              fps={displayFps}
              messages={messages}
              socketStatus={status.socket}
              videoStatus={status.video}
              theme={theme}
            />
          </div>
        </div>
      </div>

      <BottomControlConsole
        speedLevel={speedLevel}
        onSpeedChange={setSpeedLevel}
        onQuickMove={handleQuickMove}
        onEmergencyStop={handleEmergencyStop}
        onResetCamera={handleResetCamera}
        telemetrySpeed={displayTelemetry.speed}
        theme={theme}
        connected={status.socket === 'connected'}
      />
    </div>
  );
}
