export const formatValue = (value: any): string => {
  if (value === null || value === undefined) return 'N/A';
  return String(value);
};

export const formatLatency = (latency: any): string => {
  const value = formatValue(latency);
  return value === 'N/A' ? value : `${value}ms`;
};

export const formatFPS = (fps: any): string => {
  const value = formatValue(fps);
  return value === 'N/A' ? value : `${value} FPS`;
};

export const formatTime = (): string => {
  return new Date().toLocaleTimeString();
};

export const formatTimestamp = (timestamp: number): string => {
  return new Date(timestamp).toLocaleTimeString();
};