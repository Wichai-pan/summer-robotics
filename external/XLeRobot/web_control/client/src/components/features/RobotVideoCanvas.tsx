import { useEffect, useRef } from 'react';
import type { Socket } from 'socket.io-client';
import {
  Battery,
  Thermometer,
  Zap,
  Square,
  Play,
  Circle,
  Gauge,
  Monitor,
  Wifi,
  Radio,
  WifiOff,
  AlertTriangle,
  RefreshCw,
  Settings
} from 'lucide-react';
import { formatLatency, formatFPS, formatTime } from '../../utils/format';
import { ENV } from '../../config/environment';

interface RobotVideoCanvasProps {
  socket: Socket | null;
  videoStatus: string;
  telemetry: {
    battery: string;
    temp: string;
    speed: string;
    voltage: string;
  };
  latency: number | string;
  fps: number | string;
  recording: boolean;
  onToggleRecording: () => void;
  onToggleVideoStream: () => void;
}

export function RobotVideoCanvas({
  socket,
  videoStatus,
  telemetry,
  latency,
  fps,
  recording,
  onToggleRecording,
  onToggleVideoStream
}: RobotVideoCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const resizeCanvas = () => {
      const rect = canvas.getBoundingClientRect();
      canvas.width = rect.width * devicePixelRatio;
      canvas.height = rect.height * devicePixelRatio;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.scale(devicePixelRatio, devicePixelRatio);
      canvas.style.width = rect.width + 'px';
      canvas.style.height = rect.height + 'px';
    };

    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);

    return () => {
      window.removeEventListener('resize', resizeCanvas);
    };
  }, []);

  useEffect(() => {
    if (!socket) return;

    const handleVideoFrame = (data: any) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      const dpr = window.devicePixelRatio || 1;
      const logicalWidth = canvas.width / dpr;
      const logicalHeight = canvas.height / dpr;

      if (data.frame) {
        const img = new Image();
        img.onload = () => {
          ctx.clearRect(0, 0, logicalWidth, logicalHeight);
          ctx.drawImage(img, 0, 0, logicalWidth, logicalHeight);
          drawVideoOverlays(ctx, logicalWidth, logicalHeight);
        };
        img.src = `data:image/${ENV.VIDEO_FORMAT};base64,${data.frame}`;
      }
    };

    socket.on('video_frame', handleVideoFrame);
    return () => {
      socket.off('video_frame', handleVideoFrame);
    };
  }, [socket]);

  const drawVideoOverlays = (ctx: CanvasRenderingContext2D, width: number, height: number) => {
    ctx.strokeStyle = 'rgba(0, 255, 255, 0.3)';
    ctx.lineWidth = 1;
    const gridSize = 50;

    for (let x = 0; x < width; x += gridSize) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, height);
      ctx.stroke();
    }
    for (let y = 0; y < height; y += gridSize) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }

    ctx.strokeStyle = 'rgba(0, 255, 255, 0.8)';
    ctx.lineWidth = 2;
    const centerX = width / 2;
    const centerY = height / 2;
    const crossSize = 20;

    ctx.beginPath();
    ctx.moveTo(centerX - crossSize, centerY);
    ctx.lineTo(centerX + crossSize, centerY);
    ctx.moveTo(centerX, centerY - crossSize);
    ctx.lineTo(centerX, centerY + crossSize);
    ctx.stroke();
  };

  return (
    <div className="rounded-2xl overflow-hidden shadow-lg relative bg-black">
      <div className="relative" style={{ paddingTop: '56.25%' }}>
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full"
        />

        <div className="absolute top-4 left-4 flex gap-3">
          <div className="flex items-center gap-2 px-3 py-2 bg-black/50 backdrop-blur-sm rounded-md text-white text-xs border border-white/20">
            <Battery size={14} />
            {telemetry.battery}
          </div>
          <div className="flex items-center gap-2 px-3 py-2 bg-black/50 backdrop-blur-sm rounded-md text-white text-xs border border-white/20">
            <Thermometer size={14} />
            {telemetry.temp}
          </div>
          <div className="flex items-center gap-2 px-3 py-2 bg-black/50 backdrop-blur-sm rounded-md text-white text-xs border border-white/20">
            <Zap size={14} />
            {telemetry.voltage}
          </div>
        </div>

        <div className="absolute top-4 right-4 flex gap-2">
          <button
            onClick={onToggleVideoStream}
            className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm shadow transition-all ${
              videoStatus === 'streaming'
                ? 'bg-red-500 hover:bg-red-600 text-white'
                : 'bg-white/90 hover:bg-white text-gray-900'
            }`}
          >
            {videoStatus === 'streaming' ? <Square size={14} /> : <Play size={14} />}
            {videoStatus === 'streaming' ? 'Stop' : 'Start'}
          </button>
          <button
            onClick={onToggleRecording}
            className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm shadow transition-all ${
              recording
                ? 'bg-red-500 hover:bg-red-600 text-white animate-pulse'
                : 'bg-white/90 hover:bg-white text-gray-900'
            }`}
          >
            <Circle size={14} className={recording ? "fill-current" : ""} />
            {recording ? 'Recording' : 'Record'}
          </button>
        </div>

        {recording && (
          <div className="absolute top-4 left-1/2 transform -translate-x-1/2">
            <div className="bg-red-500 text-white px-4 py-2 rounded-full text-sm font-bold animate-pulse border-2 border-red-300">
              <Circle size={12} className="fill-current inline mr-2" />
              REC {formatTime()}
            </div>
          </div>
        )}

        <div className="absolute left-1/2 -translate-x-1/2 bottom-4 bg-black/60 backdrop-blur-sm px-6 py-3 rounded-full text-white text-sm flex items-center gap-4 border border-white/20">
          <div className="flex items-center gap-2">
            <Gauge size={14} />
            Speed: <span className="font-mono text-blue-300">{telemetry.speed}</span>
          </div>
          <div className="w-px h-4 bg-white/30"></div>
          <div className="flex items-center gap-2">
            <Monitor size={14} />
            FPS: <span className="font-mono text-green-300">{formatFPS(fps)}</span>
          </div>
          <div className="w-px h-4 bg-white/30"></div>
          <div className="flex items-center gap-2">
            <Wifi size={14} />
            Latency: <span className="font-mono text-yellow-300">{formatLatency(latency)}</span>
          </div>
          <div className="w-px h-4 bg-white/30"></div>
          <div className="flex items-center gap-2">
            <Radio size={14} />
            Status:
            <span className={`font-mono ${
              videoStatus === 'streaming' ? 'text-green-300' :
              videoStatus === 'error' ? 'text-red-300' : 'text-gray-300'
            }`}>
              {videoStatus.toUpperCase()}
            </span>
          </div>
        </div>

        {videoStatus === 'disconnected' && (
          <div className="absolute inset-0 bg-black/80 flex items-center justify-center">
            <div className="text-center text-white">
              <WifiOff size={64} className="mx-auto text-gray-400 mb-4" />
              <div className="text-xl font-bold mb-2">Video Stream Disconnected</div>
              <div className="text-gray-300 mb-4">Click "Start" to begin video stream</div>
              <button
                onClick={onToggleVideoStream}
                className="flex items-center px-6 py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-bold transition-colors mx-auto"
              >
                <Play size={16} className="mr-2" />
                Start Video Stream
              </button>
            </div>
          </div>
        )}

        {videoStatus === 'error' && (
          <div className="absolute inset-0 bg-red-900/80 flex items-center justify-center">
            <div className="text-center text-white">
              <AlertTriangle size={64} className="mx-auto text-red-400 mb-4" />
              <div className="text-xl font-bold mb-2">Video Stream Error</div>
              <div className="text-red-200 mb-4">Unable to connect to video stream</div>
              <button
                onClick={onToggleVideoStream}
                className="flex items-center px-6 py-3 bg-red-600 hover:bg-red-700 text-white rounded-lg font-bold transition-colors mx-auto"
              >
                <RefreshCw size={16} className="mr-2" />
                Retry Connection
              </button>
            </div>
          </div>
        )}

        {videoStatus === 'connecting' && (
          <div className="absolute inset-0 bg-blue-900/80 flex items-center justify-center">
            <div className="text-center text-white">
              <Settings size={64} className="mx-auto text-blue-400 animate-spin mb-4" />
              <div className="text-xl font-bold mb-2">Connecting...</div>
              <div className="text-blue-200">Establishing video stream connection</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
