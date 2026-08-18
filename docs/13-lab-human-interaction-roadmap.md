# 2026-08-18: Lightweight Lab Human-Interaction Roadmap

## Goal

Develop XLeRobot toward a supervised laboratory assistant that can:

1. understand a high-level request and select a verified place and skill;
2. recognize a small vocabulary of deliberate human gestures;
3. mirror coarse upper-body motion for a face-to-face demonstration; and
4. keep the operator physically separated from the experimental workspace.

This is a technical selection and implementation roadmap. No human-pose model,
motor control, camera session, dependency, or Jetson image was changed during
this investigation.

## Decision

Build a thin human-interaction layer on the existing project instead of
adopting a separate robot stack or implementing pose estimation from scratch.

The first implementation candidate is:

```text
Gemini aligned RGB-D
  -> existing Orbbec sidecar
  -> YOLO11n-pose human keypoints
  -> temporal person lock and deterministic gesture rules
  -> typed GestureEvent

language/image request
  -> existing Gemini + RoboCrew constrained tool interface
  -> allow-listed TaskPlan

GestureEvent + TaskPlan
  -> deterministic safety supervisor
  -> already validated Nav2, leader/follower, and manipulation skills
```

The LLM may select only an allow-listed high-level skill. It must never emit
motor register values, unrestricted joint targets, wheel speeds, or safety
decisions. Loss of a person track, stale frames, low confidence, ambiguous
multi-person input, communication failure, or an unknown action must result in
`STOP`/`NO_ACTION`.

## Why this fits the repository

The repository already has the expensive integration pieces:

- Gemini RGB-D acquisition and color/depth alignment;
- `tools/yolo_orbbec_depth_detect.py` and an installed Ultralytics runtime;
- a safety-constrained Gemini/RoboCrew tool-calling prototype under
  `agents/llm_navigation/`;
- black-leads-white leader/follower control and LeRobot recording;
- RTAB-Map/Nav2 localization and planning experiments; and
- a single hardware-lock entry point for Jetson device ownership.

The new code should therefore consume the existing RGB-D stream and publish a
small, hardware-independent event contract. It must not open a second camera
handle, create a second arm controller, bypass the hardware lock, or duplicate
the existing LeRobot dataset/control conventions.

## Evaluated upstream projects

Snapshot checked on 2026-08-18:

| Project | Maintenance and license | Fit | Decision |
| --- | --- | --- | --- |
| [Ultralytics YOLO11](https://github.com/ultralytics/yolo11) | Active; AGPL-3.0 implementation ecosystem | Nano pose checkpoint, familiar API, exportable to TensorRT, and the project already imports Ultralytics | Use for the first body-keypoint MVP; review licensing before any closed-source commercialization |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) | Active; Apache-2.0 | Strong pose, hand landmarks, and gesture tasks, but official Linux ARM64/Jetson packaging remains a deployment risk | Do not add to the Jetson MVP; reconsider on an x86 companion computer if finger gestures become necessary |
| [ROS4HRI](https://github.com/ros4hri) | ROS 2 message packages maintained; generally Apache-2.0 | Useful HRI vocabulary and ROS conventions, but a full additional perception stack is unnecessary | Reference its message semantics; do not install the full stack initially |
| [NVIDIA trt_pose](https://github.com/NVIDIA-AI-IOT/trt_pose) | MIT; main repository last materially updated in 2022 | Jetson-specific and historically fast, but its ROS 2 wrapper targets an old ROS generation | Reject as the new baseline |
| [LeRobot](https://github.com/huggingface/lerobot) | Active; Apache-2.0 | Existing leader/follower, recording, policy, and hardware abstractions | Continue using it for precise manipulation and demonstrations |
| [BehaviorTree.CPP](https://github.com/BehaviorTree/BehaviorTree.CPP) and [BehaviorTree.ROS2](https://github.com/BehaviorTree/BehaviorTree.ROS2) | Active; MIT/Apache-2.0 | Mature asynchronous task composition and close alignment with Nav2 | Adopt only when multiple verified skills must be composed; keep the first gesture MVP as a small deterministic state machine |
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Active; MIT | ARM/CUDA, quantization, constrained JSON, and an OpenAI-compatible server | Optional later offline backend; do not compete with vision and ROS on Jetson during the MVP |

Visual-XR retargeting projects were not selected as the base architecture.
They target different arms, VR devices, kinematics, and safety assumptions. The
existing physical leader/follower path is substantially closer to this robot
and remains the preferred source of precise laboratory demonstrations.

## Minimal MVP

The first milestone is entirely perception-only and must work on recorded
video before any live robot connection:

1. Load `yolo11n-pose.pt` through the existing Ultralytics environment.
2. Emit timestamped 2D keypoints, confidence, track identity, and frame age.
3. Maintain one explicit person lock; reject ambiguous multi-person scenes.
4. Recognize only gestures that do not require finger landmarks:
   `EMERGENCY_STOP`, `REQUEST_ATTENTION`, `POINT_LEFT`, `POINT_RIGHT`, and
   `IDLE_OR_CANCEL`.
5. Require a gesture to remain stable for a configured time and apply a
   cooldown so one pose cannot trigger repeatedly.
6. Reopen recorded results and run deterministic QA for stale frames, missing
   joints, low confidence, false transitions, and person-track loss.
7. Display the skeleton and recognized state in a GUI, with no hardware import
   and no motor output.

Do not train or fine-tune a pose model for this milestone. Start with the
existing PyTorch runtime. TensorRT export is a later optimization and must be
built and validated against the exact Jetson CUDA/TensorRT environment; a
serialized TensorRT engine is not portable across arbitrary environments.

## Mirroring boundary

Visual mirroring is not direct joint-angle copying. The later retargeting layer
must explicitly define camera, human, and robot frames; face-to-face left/right
semantics; reachable workspace; rate and joint limits; collision checks; and a
neutral-pose handover. Its first output must be a dry-run target stream.

For contact-rich or precise laboratory manipulation, use the existing physical
leader/follower path and LeRobot data recording. Visual mirroring is initially
a communication/demo feature, not a replacement for calibrated teleoperation.

## Camera-pose boundary

The Gemini currently ends at the saved ACT/IK grasp reference near raw
ID7=`4062`, ID8=`2284`. That downward view is not suitable for face-to-face
human observation. A future interaction pose must be stored as a separate,
versioned gimbal reference. It must not overwrite or be mixed with either the
ACT/IK grasp reference or the SLAM mapping reference ID7=`4066`, ID8=`1924`.

## Acceptance gates

Before connecting gesture output to any robot skill:

- recorded-video precision and false-trigger tests pass;
- live camera processing meets a measured rate and maximum-frame-age limit;
- `EMERGENCY_STOP` is implemented locally and does not depend on the LLM;
- unknown, stale, lost, or ambiguous perception always fails closed;
- the LLM output is schema-validated and restricted to an allow list;
- each selected robot skill has its own independent safety gate and timeout;
- a human remains able to cut 12 V immediately during supervised trials; and
- chemical/biological procedures receive a separate task-specific risk review.

## Planned phases

This is now an official parallel project track. It does not replace the active
ACT reliability work or the base-wheel repair gate.

| Phase | Scope | Output and acceptance | Hardware boundary |
| --- | --- | --- | --- |
| H0: contract and fixtures | Define `PersonTrack`, `PoseFrame`, `GestureEvent`, timestamps, confidence, stale/lost states, and a small labelled recorded-video fixture | Schemas reject missing/non-finite/stale data; fake source and replay are deterministic | No Jetson, camera, ROS, serial, or motors |
| H1: offline perception MVP | Run `yolo11n-pose.pt`, lock one person, recognize the initial gesture vocabulary, draw a GUI overlay, and produce JSONL | Recorded videos reopen; gesture stability/cooldown and false-trigger tests pass; ambiguous scenes fail closed | No live camera or hardware imports |
| H2: live camera-only observation | Create a separate versioned interaction gimbal reference, consume the existing Gemini stream, and measure rate, latency, frame age, and track loss | Stable face-to-face skeleton and gesture events for a supervised session; no duplicate camera owner | Requires separate approval for camera, gimbal pose, container, and any dependency/image change; still no motor output |
| H3: mirror retarget dry-run | Convert a tracked upper body into bounded robot target poses with explicit face-to-face mirroring, neutral-pose alignment, workspace limits, and collision/rate checks | Replayed and live targets remain finite, bounded, smooth, and observable in a GUI; target loss produces hold then stop | No torque or motor connection |
| H4: supervised mirror pilot | Connect the dry-run target stream to one arm through the existing controller and hardware lock, initially at very low rate and range | Neutral handover, dead-man timeout, joint/rate limits, stop gesture, disconnect stop, and immediate 12 V cutoff all pass | Separate approval for every powered test; one arm before dual-arm work |
| H5: lab task orchestration | Let the existing constrained LLM select only verified navigation/manipulation skills; compose them with deterministic preconditions and recovery | Schema-valid plans, allow-listed skills, operator confirmation for hazardous steps, complete audit log, and safe rollback | No unsupervised chemical/biological operation; task-specific risk review required |

Dependencies between phases are strict: H1 requires H0, H2 requires H1, H3
requires H2, H4 requires H3, and H5 may call only skills that have already
passed their independent hardware acceptance. TensorRT, hand/finger models,
ROS4HRI, BehaviorTree.CPP, and a local LLM remain optional optimizations rather
than prerequisites for H0/H1.

## Next implementation step

Create a separate branch/worktree and implement only the recorded-video
YOLO11n-pose pipeline, event schema, fake source, GUI overlay, and automated QA.
Do not install dependencies, rebuild the Jetson image, move the gimbal, access
motors, or connect the output to Nav2/arms until that offline milestone has
been reviewed.
