export const KEY_TO_DIRECTION: Record<string, string> = {
  'w': 'forward',
  'W': 'forward',
  's': 'backward',
  'S': 'backward',
  'a': 'left',
  'A': 'left',
  'd': 'right',
  'D': 'right',
  'q': 'rotate_left',
  'Q': 'rotate_left',
  'e': 'rotate_right',
  'E': 'rotate_right',
  'ArrowUp': 'forward',
  'ArrowDown': 'backward',
  'ArrowLeft': 'left',
  'ArrowRight': 'right'
};

export const SPEED_LEVELS = {
  LOW: { value: 0.5, label: 'Low', color: 'bg-green-500' },
  MEDIUM: { value: 1.0, label: 'Med', color: 'bg-yellow-500' },
  HIGH: { value: 1.5, label: 'High', color: 'bg-red-500' }
};

export const STATUS_COLORS = {
  connected: 'bg-green-400',
  connecting: 'bg-yellow-300',
  error: 'bg-red-500',
  disconnected: 'bg-yellow-400',
  streaming: 'bg-green-400'
};

export const MESSAGE_TYPES = {
  ERROR: 'error',
  WARNING: 'warning',
  SUCCESS: 'success',
  INFO: 'info'
} as const;
