# Pick/Hold and Place/Release Segment Recording

The original `tools/black_leads_white_wrap_safe.py` remains unchanged. The
segment recorders create separate datasets:

```text
black_leads_white_pick_hold.py     empty folded -> pick -> v -> short retract -> h/HOLD
black_leads_white_place_release.py carry folded -> place -> release -> empty folded -> q
black_leads_white_pick_hold_place.py both segments, one torque-on process, two datasets
```

Neither waiting in HOLD nor base navigation is written into either episode.

For collecting both segments without ever releasing arm ownership, use
`black_leads_white_pick_hold_place.py`. It runs both stages in one process but
still creates two independent dataset episodes. The cameras are closed after
`h` and fresh camera streams are opened only after `b`, so the HOLD/navigation
gap is absent from both training datasets.

`x` is the global abort/discard key in both segment recorders. During any
active collection, verification, confirmation or HOLD state, `x` invalidates
the current episode and stops the experiment. It is separate from the
state-specific `q`, `h`, `r`, `p` and `o` keys. Because ending the process also
removes motor torque, catch or support a still-held object before pressing `x`
whenever the situation permits. Hardware emergency stop/power isolation still
takes priority when continued torque is unsafe.

## State and recording boundaries

| State | Recorded | Decision |
|---|---:|---|
| `PREPARE_PICK` | no | fixed empty start pose |
| `RECORD_PICK` | yes | approach, close and lift |
| `RETRACT_TO_HOLD` | yes | operator-confirmed grasp, gripper latched, short retract |
| `FINALIZE_PICK` | no | `h` freezes the operator-selected endpoint |
| `HOLD` / `WAIT_FOR_PLACE` | no | arm hold, base wait/navigation |
| `RECORD_PLACE` | yes | move the held object onto its support |
| `VERIFY_PLACE` / `VERIFY_RELEASE` | yes | supervised support and release sequence |
| `RETURN_EMPTY` | yes | withdraw and return empty |
| `VERIFY_EMPTY` / `FINALIZE_PLACE` | no | final pose gate and encoding |

The `v` key itself is the supervised grasp-success label. There is no automatic
position/load/current classifier and no additional `y/n` confirmation. Press
`x` to discard a failed grasp instead of recording recovery motion inside a
successful episode.

## Pose references

Save the empty folded start pose with no object. The pick recorder no longer
requires or checks a fixed carry pose: the operator-selected pose at `h` is the
endpoint. The separate place recorder still requires a carry start reference;
save that pose only while the object is supported by a table/fixture. The pose
saver disables torque, so never use it with an unsupported object.

```bash
./scripts/jetson_robot_exec.sh --white --interactive -- \
  python3 tools/save_white_folded_pose.py \
  --output /data/act/config/white_empty_folded_pose_v1.json

./scripts/jetson_robot_exec.sh --white --interactive -- \
  python3 tools/save_white_folded_pose.py \
  --output /data/act/config/white_carry_folded_pose_v1.json
```

## Record pick and enter HOLD

```bash
./scripts/jetson_robot_exec.sh --gemini --wrist-a --black --white --interactive -- \
  python3 tools/black_leads_white_pick_hold.py \
  --record-root /data/act/pick_level_cup_retract_hold_v2 \
  --record-repo-id forestbridge/pick-level-cup-retract-hold-v2 \
  --scene-version pick_level_cup_retract_hold_v2_20260907 \
  --task "Pick up the measuring cup while keeping it level, retract slightly, and hold all joints and the grasp." \
  --white-wrist-device /dev/wrist-2-4-1 \
  --folded-pose-json /data/act/config/white_empty_folded_pose_v1.json \
  --full-range --duration-s 120 --fps 20 \
  --max-speed-deg-s 30 --max-gripper-speed-s 60
```

Enter `FOLLOW`, keep the cup level, demonstrate the grasp and small lift, and
press `v` only after visually confirming that the cup is stably suspended.
`v` immediately accepts the grasp; it performs no load/current/position test
and requires no subsequent `y`. At that instant the follower's actual gripper
position is latched, preventing a later leader squeeze from tightening it
further during retraction. Keep the cup level, retract only enough for base
clearance, then press `h`. The `h` pose is accepted without a fixed carry-pose,
grasp telemetry or wrist endpoint check. All arm joints and the gripper are
then held at their actual positions.

At `h`, the recorder closes both cameras and freezes the episode buffer, but
does not save it yet. The episode is saved only after the object has remained
secure through HOLD, has been reliably supported, and the operator presses
`r` and enters `RELEASE`. If the object drops or the experiment becomes
invalid after `h`, press `x`; the still-pending episode is discarded instead
of being left in the dataset as a normal success.
Pressing `h` completes and freezes collection, but the buffered episode remains
pending so that the global `x` key can still invalidate it after a later drop.
Do not press `h` after a drop, collision, manual correction or uncertain grasp;
use `x` to discard instead.

While HOLD is active, `q` and Escape are rejected; `x` remains the global
discard command. After a person or stable
surface has fully taken the object's weight, press `r` and type `RELEASE` to
save the successful episode, disable torque and exit. This confirmation does not command the gripper open;
the object must already be supported. `Ctrl-C` is also rejected during normal
HOLD. Power loss, cable removal, motor protection and process kill still cannot
be made safe in software, so a person must remain ready to catch the object.

## Record place and release

This is a separate supervised recording session. Before starting, support the
object on a fixture/table while placing the torque-free arm at the saved carry
pose. Do not terminate the pick recorder while it holds a suspended object in
order to launch this recorder; that is not a safe process handoff.

```bash
./scripts/jetson_robot_exec.sh --gemini --wrist-a --black --white --interactive -- \
  python3 tools/black_leads_white_place_release.py \
  --record-root /data/act/stowed_object_to_place_v1 \
  --record-repo-id forestbridge/stowed-object-to-place-v1 \
  --scene-version stowed_object_to_place_v1 \
  --task "Move the held object from the fixed carry pose to the target, release it, and return to the empty folded pose." \
  --white-wrist-device /dev/wrist-2-4-1 \
  --carry-pose-json /data/act/config/white_carry_folded_pose_v1.json \
  --empty-folded-pose-json /data/act/config/white_empty_folded_pose_v1.json \
  --full-range --duration-s 120 --fps 20 \
  --max-speed-deg-s 30 --max-gripper-speed-s 60
```

Enter `FOLLOW`, put the object onto a stable support and press `p` as the
supervised support confirmation. Open the gripper and press `o`; position and
current must pass release verification. Return to the empty folded pose,
remain still for 1-2 seconds, then press `q`. `q` is rejected until `p` and `o`
have passed, and the arm remains torque-enabled while the empty pose is checked. Enter
`SUCCESS` only after visually confirming a safe release without collision,
drop, or manual correction.

## Collect both independent segments in one run

This is the recommended workflow when the white arm must keep holding the cup
while the base moves. The two roots must be different because pick and place
remain separate policies and must never become one continuous episode.

```bash
./scripts/jetson_robot_exec.sh --gemini --wrist-a --black --white --interactive -- \
  python3 tools/black_leads_white_pick_hold_place.py \
  --pick-record-root /data/act/pick_level_cup_retract_hold_v2 \
  --pick-record-repo-id forestbridge/pick-level-cup-retract-hold-v2 \
  --pick-scene-version pick_level_cup_retract_hold_v2_20260907 \
  --pick-task "Pick up the measuring cup while keeping it level, retract slightly, and hold the grasp." \
  --place-record-root /data/act/place_level_cup_release_v2 \
  --place-record-repo-id forestbridge/place-level-cup-release-v2 \
  --place-scene-version place_level_cup_release_v2_20260907 \
  --place-task "Move the held measuring cup to the target, release it, and return the empty arm." \
  --white-wrist-device /dev/wrist-2-4-1 \
  --folded-pose-json /data/act/config/white_empty_folded_pose_v2.json \
  --record-width 640 --record-height 480 --camera-fps 30 \
  --max-camera-age-s 0.25 --full-range --duration-s 120 --fps 20 \
  --max-speed-deg-s 30 --max-gripper-speed-s 60 \
  --tracking-error-deg 15 --wrist-max-speed-deg-s 8 \
  --wrist-max-travel-deg 60 --max-hold-temperature-c 60 \
  --max-hold-gripper-error 8
```

Key sequence:

1. `FOLLOW`: start the pick recorder and leader/follower control.
2. `v`: directly confirm the grasp and latch the gripper position.
3. `h`: freeze all joints and close both cameras; pick frames end here.
4. Move the base while the arm remains in HOLD. No frames are recorded.
5. `b`: after confirming the cup is still secure at the destination, start a
   new place recorder and rebase relative following at the held pose. The pick
   episode is then saved independently.
6. `p`: directly confirm the cup is supported; open the gripper and press `o`
   to directly confirm release.
7. Return the empty arm to the saved folded pose and press `q`. After the empty
   endpoint passes, only the place episode is saved and torque is released.

Before `b`, `x` discards the pending pick episode. After `b`, the pick episode
has already been saved, so `x` discards only the in-progress place episode.
This preserves a valid pick demonstration when a later place attempt fails.

At both `h` and `b`, wrist-roll torque is disabled only for the operating-mode
change. The controller then waits for the new mode's raw position coordinate,
seeds the goal from that post-switch feedback, verifies the register write and
only then restores wrist torque. A pre-switch velocity-mode coordinate is
never reused as a position-mode goal, preventing a homing-offset-sized jump.

## Operational boundary

Separate recorders and datasets are appropriate for training two policies.
The combined recorder is the long-lived arm-owning supervisor for data
collection. Two processes must not attempt to own the same controller, and
process termination is not a safe method of transferring a suspended load.
On this robot the white arm and base share the white controller/host lock, so
an existing base-control process cannot be launched beside this recorder.
Actual powered base motion in the same session requires an integrated
arm-and-base supervisor; merely stopping the cameras at `h` does not release
the outer process's hardware locks.
