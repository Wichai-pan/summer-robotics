import asyncio
import base64
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:
    from core.remote_core import RemoteCore


class VideoStreamManager:

    def __init__(self) -> None:
        self.streaming = False
        self.frame_rate = 30
        self.frame_interval = 1.0 / self.frame_rate
        self.stream_tasks: dict[str, asyncio.Task] = {}
        self.remote_core: Optional['RemoteCore'] = None

    def attach_remote_core(self, remote_core: 'RemoteCore') -> None:
        self.remote_core = remote_core

    async def start_stream(self) -> dict:
        if not self.streaming:
            self.streaming = True
            print("Video stream started")
        return {'status': 'streaming_started'}

    async def stop_stream(self, sid: Optional[str] = None) -> dict:
        self.streaming = False

        if sid and sid in self.stream_tasks:
            task = self.stream_tasks.pop(sid)
            if not task.cancelled():
                task.cancel()
                print(f"Cancelled video stream task for client {sid}")
        elif sid is None:
            for client_sid, task in list(self.stream_tasks.items()):
                if not task.cancelled():
                    task.cancel()
                    print(f"Cancelled video stream task for client {client_sid}")
            self.stream_tasks.clear()

        print("Video stream stopped")
        return {'status': 'streaming_stopped'}

    def _generate_fallback_frame(self) -> Optional[str]:
        try:
            import cv2
        except ImportError:
            return None

        test_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        success, buffer = cv2.imencode('.jpg', test_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not success:
            return None

        return base64.b64encode(buffer).decode('utf-8')

    async def get_frame(self) -> Optional[dict]:
        frame_base64 = None
        source = 'test'

        if self.remote_core and self.remote_core.connected:
            try:
                frame_base64 = await self.remote_core.get_camera_frame_base64()
                if frame_base64:
                    source = self.remote_core.config.robot_type.lower()
            except Exception as exc:
                print(f"Error getting frame from remote core: {exc}")

        if not frame_base64:
            frame_base64 = self._generate_fallback_frame()
            if frame_base64:
                source = 'test_jpeg'

        if not frame_base64:
            return None

        loop = asyncio.get_running_loop()
        return {
            'frame': frame_base64,
            'width': 640,
            'height': 480,
            'channels': 3,
            'timestamp': loop.time(),
            'source': source
        }

    async def stream_frames(self, socket_io, sid: str) -> None:
        print(f"Starting video stream for client {sid}")
        try:
            while self.streaming:
                if asyncio.current_task().cancelled():
                    break

                frame_data = await self.get_frame()
                if frame_data:
                    await socket_io.emit('video_frame', frame_data, to=sid)

                await asyncio.sleep(self.frame_interval)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"Stream error for client {sid}: {exc}")
        finally:
            self.stream_tasks.pop(sid, None)
            print(f"Video stream ended for client {sid}")


video_manager = VideoStreamManager()
