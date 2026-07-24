import time
import asyncio

import socketio
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.streaming import video_manager
from core.config import ServerConfig
from core.remote_core import RemoteCore

# Load simplified configuration
config = ServerConfig.from_env('.env')
config.validate()

print(f"Server Configuration:")
print(config)

# Create unified remote control core
remote_core = RemoteCore(config)
video_manager.attach_remote_core(remote_core)


def _init_client_state() -> dict:
    now = time.time()
    return {
        'last_command_time': 0.0,
        'command_count': 0,
        'window_start': now,
        'throttle_violations': 0,
        'last_throttle_time': 0.0
    }


client_states: dict[str, dict] = {}

RATE_LIMIT_CONFIG = {
    'max_commands_per_second': 20,
    'min_command_interval': 0.05,
    'rate_limit_window': 1.0,
    'throttle_penalty_duration': 2.0,
    'max_throttle_violations': 3,
}

async def startup_event():
    print("Initializing remote control core...")
    success = await remote_core.connect()
    if success:
        print(f"Remote core connected to {config.robot_type} host successfully")
    else:
        print("Remote core connection failed")

async def shutdown_event():
    # Cleanup resources on shutdown
    print("Shutting down remote control core...")
    await remote_core.disconnect()
    print("Remote core shut down")

sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=True,
    engineio_logger=True
)

app = FastAPI(title="XLeRobot Web Control API", version="0.1.0")

app.add_event_handler("startup", startup_event)
app.add_event_handler("shutdown", shutdown_event)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

socket_app = socketio.ASGIApp(sio, app)

@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "XLeRobot Web Control Server is running"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    controller_info = {
        'type': config.robot_type,
        'connected': remote_core.connected,
        'capabilities': remote_core.get_capabilities()
    }

    return {
        "status": "healthy",
        "service": "XLeRobot Web Control",
        "controller": controller_info
    }

@app.get("/robot/info")
async def robot_info():
    """Robot controller info endpoint"""
    return {
        'controller_type': config.robot_type,
        'connected': remote_core.connected,
        'capabilities': remote_core.get_capabilities(),
        'state': await remote_core.get_state() if remote_core.connected else None
    }

@app.get("/robot/controllers")
async def available_controllers():
    """Get available controllers"""
    return {
        'available': ['maniskill', 'mujoco', 'xlerobot'],
        'current': config.robot_type,
        'description': 'Unified remote control supports all robot types via host programs'
    }

@app.post("/robot/camera/reset")
async def reset_camera():
    """Reset camera to default position"""
    try:
        result = await remote_core.reset_camera()
        return result
    except Exception as e:
        return {"error": f"Camera reset failed: {str(e)}"}

@app.post("/robot/camera/position")
async def set_camera_position(request: dict):
    """Set camera position"""
    position = request.get('position')
    target = request.get('target')

    if not position:
        return {"error": "Position is required"}

    try:
        result = await remote_core.set_camera_position(position, target)
        return result
    except Exception as e:
        return {"error": f"Set camera position failed: {str(e)}"}

@app.get("/robot/camera/info")
async def get_camera_info():
    """Get camera info"""
    try:
        # For simplified architecture, return basic camera info
        return {
            'camera_id': 0,
            'position': [2.0, 2.0, 2.0],
            'target': [0.0, 0.0, 0.0],
            'frame_size': {'width': config.video_width, 'height': config.video_height},
            'fps': config.video_fps,
            'quality': config.video_quality
        }
    except Exception as e:
        return {"error": f"Get camera info failed: {str(e)}"}

# Rate limiting and throttling functions
def check_rate_limit(sid: str) -> bool:
    """Check if client is within rate limits"""
    current_time = time.time()
    client_state = client_states.get(sid)

    if not client_state:
        return True

    # Reset command count if window has passed
    if current_time - client_state['window_start'] >= RATE_LIMIT_CONFIG['rate_limit_window']:
        client_state['command_count'] = 0
        client_state['window_start'] = current_time

    return client_state['command_count'] < RATE_LIMIT_CONFIG['max_commands_per_second']

def check_throttle(sid: str) -> bool:
    """Check if client is throttling commands too fast"""
    current_time = time.time()
    client_state = client_states.get(sid)

    if not client_state:
        return True

    # Check if client is in penalty period
    if (client_state['throttle_violations'] >= RATE_LIMIT_CONFIG['max_throttle_violations'] and
        current_time - client_state['last_throttle_time'] < RATE_LIMIT_CONFIG['throttle_penalty_duration']):
        return False

    # Reset violations if penalty period has passed
    if current_time - client_state['last_throttle_time'] >= RATE_LIMIT_CONFIG['throttle_penalty_duration']:
        client_state['throttle_violations'] = 0

    # Check minimum interval between commands
    if current_time - client_state['last_command_time'] < RATE_LIMIT_CONFIG['min_command_interval']:
        client_state['throttle_violations'] += 1
        client_state['last_throttle_time'] = current_time
        return False

    return True

def update_client_state(sid: str, *, timestamp: float) -> None:
    """Update client state after successful command"""
    client_state = client_states.setdefault(sid, _init_client_state())
    client_state['last_command_time'] = timestamp
    client_state['command_count'] += 1

@sio.event
async def connect(sid, environ, auth):
    """Client connection event"""
    print(f"Client connected: {sid}")
    # Initialize client state
    client_states[sid] = _init_client_state()
    await sio.emit('connection_established', {'message': 'Connected to XLeRobot control server'}, to=sid)

@sio.event
async def disconnect(sid):
    """Client disconnect event"""
    print(f"Client disconnected: {sid}")

    if sid in video_manager.stream_tasks:
        task = video_manager.stream_tasks[sid]
        if not task.cancelled():
            task.cancel()
            print(f"Cancelled video stream task for disconnected client {sid}")
        del video_manager.stream_tasks[sid]

    if client_states.pop(sid, None) is not None:
        print(f"Cleaned up state for client {sid}")

@sio.event
async def ping(sid, data):
    """Ping-pong test event"""
    print(f"Received ping from {sid}: {data}")
    await sio.emit('pong', {'message': 'pong', 'timestamp': data.get('timestamp')}, to=sid)

@sio.event
async def move_command(sid, data):
    """Movement command handler with rate limiting and throttling"""
    direction = data.get('direction')
    speed = data.get('speed', 1.0)
    timestamp = data.get('timestamp', time.time() * 1000)

    current_time = time.time()

    # Check rate limiting
    if not check_rate_limit(sid):
        await sio.emit('command_received', {
            'type': 'move',
            'status': 'rate_limited',
            'message': f'Rate limit exceeded: maximum {RATE_LIMIT_CONFIG["max_commands_per_second"]} commands per second',
            'max_rate': RATE_LIMIT_CONFIG['max_commands_per_second'],
            'client_timestamp': timestamp,
            'server_timestamp': current_time * 1000
        }, to=sid)
        return

    # Check throttling
    if not check_throttle(sid):
        client_state = client_states.setdefault(sid, _init_client_state())
        await sio.emit('command_received', {
            'type': 'move',
            'status': 'throttled',
            'message': f'Command throttled: minimum {RATE_LIMIT_CONFIG["min_command_interval"]*1000:.0f}ms interval required',
            'min_interval': RATE_LIMIT_CONFIG['min_command_interval'] * 1000,
            'violations': client_state['throttle_violations'],
            'penalty_remaining': max(0, RATE_LIMIT_CONFIG['throttle_penalty_duration'] - (current_time - client_state['last_throttle_time'])) if client_state['throttle_violations'] >= RATE_LIMIT_CONFIG['max_throttle_violations'] else 0,
            'client_timestamp': timestamp,
            'server_timestamp': current_time * 1000
        }, to=sid)
        return

    if not remote_core.connected:
        await sio.emit('command_received', {
            'type': 'move',
            'status': 'error',
            'message': 'Remote core not connected to robot host',
            'client_timestamp': timestamp,
            'server_timestamp': current_time * 1000
        }, to=sid)
        return

    # Log command with rate limiting info
    client_state = client_states.setdefault(sid, _init_client_state())
    print(f"[{sid[:8]}] Move command: {direction} (speed={speed:.1f}) - count={client_state['command_count'] + 1}/{RATE_LIMIT_CONFIG['max_commands_per_second']}")

    # Execute robot command
    try:
        result = await remote_core.move(direction, speed)

        # Update client state after successful command
        update_client_state(sid, timestamp=current_time)

        # Get current robot state
        robot_state = await remote_core.get_state()

        # Calculate latency
        latency = (current_time * 1000) - timestamp if timestamp else 0

        # Send success response with detailed metrics
        await sio.emit('command_received', {
            'type': 'move',
            'direction': direction,
            'speed': speed,
            'status': result.get('status', 'executed'),
            'robot_state': robot_state,
            'metrics': {
                'latency': latency,
                'commands_in_window': client_state['command_count'],
                'max_commands': RATE_LIMIT_CONFIG['max_commands_per_second'],
                'throttle_violations': client_state['throttle_violations']
            },
            'client_timestamp': timestamp,
            'server_timestamp': current_time * 1000
        }, to=sid)

    except Exception as e:
        await sio.emit('command_received', {
            'type': 'move',
            'status': 'error',
            'message': f'Command execution failed: {str(e)}',
            'client_timestamp': timestamp,
            'server_timestamp': current_time * 1000
        }, to=sid)

@sio.event
async def start_video_stream(sid):
    """Start video streaming"""
    print(f"Client {sid} requested start video stream")
    
    if sid in video_manager.stream_tasks:
        task = video_manager.stream_tasks[sid]
        if not task.cancelled():
            task.cancel()
        del video_manager.stream_tasks[sid]
    
    result = await video_manager.start_stream()
    await sio.emit('stream_status', result, to=sid)
    
    task = asyncio.create_task(video_manager.stream_frames(sio, sid))
    video_manager.stream_tasks[sid] = task

@sio.event
async def stop_video_stream(sid):
    """Stop video streaming"""
    print(f"Client {sid} requested stop video stream")
    result = await video_manager.stop_stream(sid)
    await sio.emit('stream_status', result, to=sid)


@sio.event
async def reset_camera(sid):
    """Reset camera event handler"""
    print(f"Client {sid} requested camera reset")

    try:
        result = await remote_core.reset_camera()
        await sio.emit('camera_action_result', {
            'action': 'reset',
            **result
        }, to=sid)
        print(f"Camera reset result: {result['status']}")
    except Exception as e:
        await sio.emit('camera_action_result', {
            'action': 'reset',
            'status': 'error',
            'message': f'Camera reset failed: {str(e)}'
        }, to=sid)

@sio.event
async def set_camera_position(sid, data):
    """Set camera position event handler"""
    print(f"Client {sid} requested set camera position")

    position = data.get('position')
    target = data.get('target')

    if not position:
        await sio.emit('camera_action_result', {
            'action': 'set_position',
            'status': 'error',
            'message': 'Position is required'
        }, to=sid)
        return

    try:
        result = await remote_core.set_camera_position(position, target)
        await sio.emit('camera_action_result', {
            'action': 'set_position',
            **result
        }, to=sid)
        print(f"Camera position set result: {result['status']}")
    except Exception as e:
        await sio.emit('camera_action_result', {
            'action': 'set_position',
            'status': 'error',
            'message': f'Set camera position failed: {str(e)}'
        }, to=sid)

@sio.event
async def get_camera_info(sid):
    """Get camera info event handler"""
    print(f"Client {sid} requested camera info")

    try:
        # Return basic camera info for simplified architecture
        camera_info = {
            'camera_id': 0,
            'position': [2.0, 2.0, 2.0],
            'target': [0.0, 0.0, 0.0],
            'frame_size': {'width': config.video_width, 'height': config.video_height},
            'fps': config.video_fps,
            'quality': config.video_quality
        }
        await sio.emit('camera_info_result', {
            'status': 'success',
            'camera_info': camera_info
        }, to=sid)
    except Exception as e:
        await sio.emit('camera_info_result', {
            'status': 'error',
            'message': f'Get camera info failed: {str(e)}'
        }, to=sid)

if __name__ == "__main__":
    uvicorn.run(
        "main:socket_app",
        host=config.ui_host,
        port=config.ui_port,
        reload=False,  # Disable reload for simplified architecture
        log_level="info"
    )
