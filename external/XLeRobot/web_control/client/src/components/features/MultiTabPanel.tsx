import { useState, type ReactNode } from 'react';
import type { SystemMessage } from '../../types';
import {
  BarChart3,
  FileText,
  Settings,
  TrendingUp,
  Battery,
  Rocket,
  Thermometer,
  Zap,
  Wifi,
  Monitor,
  Activity,
  CheckCircle,
  XCircle,
  AlertTriangle,
  Info,
  Circle,
  Inbox
} from 'lucide-react';
import { formatTime, formatTimestamp, formatLatency, formatFPS } from '../../utils/format';
import { MESSAGE_TYPES } from '../../config/constants';

interface MultiTabPanelProps {
  telemetry: {
    battery: string;
    speed: string;
    temp: string;
    voltage: string;
  };
  armAngles: Array<number | null>;
  latency: number | string | null;
  fps: number | string | null;
  messages: SystemMessage[];
  socketStatus: string;
  videoStatus: string;
  theme: 'light' | 'dark';
}

type TabType = 'telemetry' | 'logs' | 'diag';

export function MultiTabPanel({
  telemetry,
  armAngles,
  latency,
  fps,
  messages,
  socketStatus,
  videoStatus,
  theme
}: MultiTabPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('telemetry');


  return (
    <div className={`rounded-2xl p-4 shadow-sm flex flex-col gap-4 ${
      theme === 'dark' ? 'bg-gray-800' : 'bg-white'
    }`}>
      {/* Tabs */}
      <div className="flex items-center gap-3">
        <Tab 
          label="Telemetry" 
          active={activeTab === 'telemetry'} 
          onClick={() => setActiveTab('telemetry')}
          theme={theme}
          icon={<BarChart3 size={16} />}
        />
        <Tab 
          label="Logs" 
          active={activeTab === 'logs'} 
          onClick={() => setActiveTab('logs')}
          theme={theme}
          icon={<FileText size={16} />}
        />
        <Tab 
          label="Diagnostics" 
          active={activeTab === 'diag'} 
          onClick={() => setActiveTab('diag')}
          theme={theme}
          icon={<Settings size={16} />}
        />
        <div className="ml-auto text-xs text-gray-400 font-mono">
          Live Data
        </div>
      </div>

      {/* Tab Content */}
      <div className="flex-1 min-h-[320px]">
        {activeTab === 'telemetry' && (
          <TelemetryPanel 
            telemetry={telemetry} 
            armAngles={armAngles} 
            latency={latency}
            fps={fps}
            theme={theme}
          />
        )}
        {activeTab === 'logs' && (
          <LogPanel messages={messages} theme={theme} />
        )}
        {activeTab === 'diag' && (
          <DiagPanel 
            latency={latency} 
            fps={fps}
            socketStatus={socketStatus} 
            videoStatus={videoStatus}
            theme={theme}
          />
        )}
      </div>
    </div>
  );
}

interface TabProps {
  label: string;
  active: boolean;
  onClick: () => void;
  theme: 'light' | 'dark';
  icon: ReactNode;
}

function Tab({ label, active, onClick, theme, icon }: TabProps) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-all ${
        active
          ? 'bg-blue-100 text-blue-700 shadow-sm border border-blue-200'
          : theme === 'dark'
          ? 'text-gray-400 hover:bg-gray-700 hover:text-gray-200'
          : 'text-gray-500 hover:bg-gray-50 hover:text-gray-700'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

interface TelemetryPanelProps {
  telemetry: any;
  armAngles: Array<number | null>;
  latency: number | string | null;
  fps: number | string | null;
  theme: 'light' | 'dark';
}

function TelemetryPanel({ telemetry, armAngles, latency, fps, theme }: TelemetryPanelProps) {

  return (
    <div className="space-y-4">
      {/* System Overview */}
      <div className={`rounded-lg p-4 ${
        theme === 'dark' ? 'bg-gray-700' : 'bg-gray-50'
      }`}>
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-semibold flex items-center gap-2">
            <TrendingUp size={16} />
            System Overview
          </div>
          <div className="text-xs text-gray-400 font-mono">
            {formatTime()}
          </div>
        </div>
        
        <div className="grid grid-cols-2 gap-3">
          <MetricCard 
            label="Battery Level" 
            value={telemetry.battery}
            icon={<Battery size={16} />}
            color="text-green-600"
            theme={theme}
          />
          <MetricCard 
            label="Movement Speed" 
            value={telemetry.speed}
            icon={<Rocket size={16} />}
            color="text-blue-600"
            theme={theme}
          />
          <MetricCard 
            label="System Temperature" 
            value={telemetry.temp}
            icon={<Thermometer size={16} />}
            color="text-orange-600"
            theme={theme}
          />
          <MetricCard 
            label="System Voltage" 
            value={telemetry.voltage}
            icon={<Zap size={16} />}
            color="text-purple-600"
            theme={theme}
          />
        </div>
      </div>

      {/* Network Performance */}
      <div className={`rounded-lg p-4 ${
        theme === 'dark' ? 'bg-gray-700' : 'bg-gray-50'
      }`}>
        <div className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Activity size={16} />
          Network Performance
        </div>
        
        <div className="grid grid-cols-2 gap-3">
          <MetricCard 
            label="Latency" 
            value={formatLatency(latency)}
            icon={<Wifi size={16} />}
            color="text-yellow-600"
            theme={theme}
          />
          <MetricCard 
            label="Frame Rate" 
            value={formatFPS(fps)}
            icon={<Monitor size={16} />}
            color="text-green-600"
            theme={theme}
          />
        </div>
      </div>

      {/* Arm Joint Angles */}
      <div className={`rounded-lg p-4 ${
        theme === 'dark' ? 'bg-gray-700' : 'bg-gray-50'
      }`}>
        <div className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Settings size={16} />
          Robot Arm Joint Angles
        </div>
        
        {armAngles.length > 0 ? (
          <div className="grid grid-cols-2 gap-3">
            {armAngles.map((angle, index) => {
              const isNumber = typeof angle === 'number' && Number.isFinite(angle);
              const normalizedWidth = isNumber ? Math.min(Math.abs(angle) / 180 * 100, 100) : 0;

              return (
                <div key={index} className={`p-3 border rounded-lg text-center ${
                  theme === 'dark' ? 'border-gray-600 bg-gray-800' : 'border-gray-200 bg-white'
                }`}>
                  <div className="text-xs text-gray-400 mb-1">Joint {index + 1}</div>
                  <div className="font-mono text-lg font-bold">
                    {isNumber ? `${angle} deg` : 'N/A'}
                  </div>
                  <div className="mt-1">
                    <div className={`h-2 rounded-full overflow-hidden ${
                      theme === 'dark' ? 'bg-gray-700' : 'bg-gray-200'
                    }`}>
                      <div 
                        className="h-full bg-blue-500 transition-all duration-300"
                        style={{ width: `${normalizedWidth}%` }}
                      ></div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className={`p-3 rounded-lg text-center text-sm text-gray-400 ${
            theme === 'dark' ? 'bg-gray-800 border border-gray-600' : 'bg-gray-100 border border-gray-200'
          }`}>
            Arm telemetry not available
          </div>
        )}
      </div>
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: string;
  icon: React.ReactNode;
  color: string;
  theme: 'light' | 'dark';
}

function MetricCard({ label, value, icon, color, theme }: MetricCardProps) {
  return (
    <div className={`p-3 rounded-lg shadow-sm border ${
      theme === 'dark' ? 'bg-gray-800 border-gray-600' : 'bg-white border-gray-200'
    }`}>
      <div className="flex items-center gap-2 mb-1">
        {icon}
        <span className="text-xs text-gray-400">{label}</span>
      </div>
      <div className={`font-mono font-bold text-lg ${color}`}>
        {value}
      </div>
    </div>
  );
}

interface LogPanelProps {
  messages: SystemMessage[];
  theme: 'light' | 'dark';
}

function LogPanel({ messages, theme }: LogPanelProps) {
  const getLogIcon = (type: SystemMessage['type']) => {
    switch (type) {
      case MESSAGE_TYPES.ERROR: return <XCircle size={16} className="text-red-500" />;
      case MESSAGE_TYPES.WARNING: return <AlertTriangle size={16} className="text-yellow-500" />;
      case MESSAGE_TYPES.SUCCESS: return <CheckCircle size={16} className="text-green-500" />;
      default: return <Info size={16} className="text-blue-500" />;
    }
  };

  const getLogStyle = (type: SystemMessage['type']) => {
    switch (type) {
      case MESSAGE_TYPES.ERROR:
        return 'bg-red-50 border-red-200 text-red-900';
      case MESSAGE_TYPES.WARNING:
        return 'bg-yellow-50 border-yellow-200 text-yellow-900';
      case MESSAGE_TYPES.SUCCESS:
        return 'bg-green-50 border-green-200 text-green-900';
      default:
        return theme === 'dark' ? 'bg-gray-700 border-gray-600' : 'bg-gray-50 border-gray-200';
    }
  };

  return (
    <div className="space-y-2 overflow-auto h-full">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-semibold flex items-center gap-2">
          <FileText size={16} />
          System Logs
        </div>
        <div className="text-xs text-gray-400">
          Total {messages.length} records
        </div>
      </div>
      
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {messages.length === 0 ? (
          <div className={`text-center py-8 text-gray-400 ${
            theme === 'dark' ? 'bg-gray-700' : 'bg-gray-50'
          } rounded-lg`}>
            <div className="mb-2">
              <Inbox size={32} className="mx-auto text-gray-400" />
            </div>
            <div>No log records</div>
          </div>
        ) : (
          messages.slice(-10).reverse().map((message) => (
            <div
              key={message.id}
              className={`p-3 rounded-lg border ${getLogStyle(message.type)}`}
            >
              <div className="flex items-start gap-2">
                {getLogIcon(message.type)}
                <div className="flex-1 min-w-0">
                  <div className="text-xs text-gray-500 mb-1">
                    {formatTimestamp(message.timestamp)}
                  </div>
                  <div className="text-sm font-mono break-words">
                    {message.content}
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

interface DiagPanelProps {
  latency: number | string | null;
  fps: number | string | null;
  socketStatus: string;
  videoStatus: string;
  theme: 'light' | 'dark';
}

function DiagPanel({ latency, fps, socketStatus, videoStatus, theme }: DiagPanelProps) {
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'connected': 
      case 'streaming':
        return 'text-green-600';
      case 'disconnected':
        return 'text-gray-600';
      case 'error':
        return 'text-red-600';
      case 'connecting':
        return 'text-yellow-600';
      default:
        return 'text-gray-600';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'connected': 
      case 'streaming':
        return <CheckCircle size={16} className="text-green-500" />;
      case 'disconnected':
        return <XCircle size={16} className="text-red-500" />;
      case 'error':
        return <AlertTriangle size={16} className="text-red-500" />;
      case 'connecting':
        return <Circle size={16} className="text-yellow-500" />;
      default:
        return <Circle size={16} className="text-gray-500" />;
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-4">
        <Settings size={16} />
        <div className="text-sm font-semibold">System Diagnostics</div>
      </div>

      {/* Connection Status */}
      <div className={`p-4 rounded-lg ${
        theme === 'dark' ? 'bg-gray-700' : 'bg-gray-50'
      }`}>
        <div className="text-sm font-medium mb-3">Connection Status</div>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">Socket Connection</span>
            <div className="flex items-center gap-2">
              {getStatusIcon(socketStatus)}
              <span className={`font-mono text-sm font-bold ${getStatusColor(socketStatus)}`}>
                {socketStatus.toUpperCase()}
              </span>
            </div>
          </div>
          <div className="flex items-center justify-between">
            <span className="text-sm text-gray-500">Video Stream</span>
            <div className="flex items-center gap-2">
              {getStatusIcon(videoStatus)}
              <span className={`font-mono text-sm font-bold ${getStatusColor(videoStatus)}`}>
                {videoStatus.toUpperCase()}
              </span>
            </div>
          </div>
        </div>
      </div>

      <div className={`p-4 rounded-lg ${
        theme === 'dark' ? 'bg-gray-700' : 'bg-gray-50'
      }`}>
        <div className="text-sm font-medium mb-3">Performance Metrics</div>
        <div className="grid grid-cols-2 gap-3">
          <div className="text-center">
            <div className="text-2xl font-mono font-bold text-purple-600">{formatLatency(latency)}</div>
            <div className="text-xs text-gray-400">Network Latency</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-mono font-bold text-green-600">{formatFPS(fps)}</div>
            <div className="text-xs text-gray-400">Frame Rate (FPS)</div>
          </div>
        </div>
      </div>
    </div>
  );
}
