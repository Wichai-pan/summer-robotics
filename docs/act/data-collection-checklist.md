# ACT Data Collection Checklist

Use this checklist only after the Phase 1 hardware gate has been approved.
It is a runbook, not authorization to move the robot.

## Before The Session

- [ ] Announce the hardware owner and verify no other locked hardware process
  is running on Jetson.
- [ ] Record Git commit, Jetson container image tag, LeRobot version, recorder
  config hash, and black-arm calibration file identity.
- [ ] Record the dataset ID/version and create a new dataset directory under
  `/home/jetsonl7/robot-data/act/`; never append incompatible data to an old
  schema.
- [ ] Photograph the whole scene and close-ups of Gemini mount, black-arm base,
  desk edge, jar, and starting pose. Assign a `scene_version`.
- [ ] Fix Gemini and white-wrist RGB resolution, FPS and camera poses. Log
  their stable physical identities; never use a volatile `/dev/videoN` name.
- [ ] Verify the six observation/action joint names, order, units and command
  convention before recording. Use LeRobot calibrated positions; do not mix
  legacy `SAVED_TARGET_JSON` with measured encoder values.
- [ ] Confirm the eye-to-hand diagnostic fit remains `motion_locked` and is
  not loaded by the recorder or controller.
- [ ] Check the 12V cut path, arm clearance, operator position, stop key, and
  a manual recovery plan.

## Pilot Episodes

Collect a small pilot only after a separate movement approval.

- [ ] Start from the same safe folded pose, jar start marker and place target
  for every v1 pilot.
- [ ] Record the full episode: folded pose, approach, close, lift, place,
  release and return to the folded pose. Do not begin halfway through a grasp.
- [ ] For each episode, log operator, scene version, jar start-cell, outcome,
  duration, and one failure reason if unsuccessful.
- [ ] Do not use collision, dropped-object, stale-camera, wrong-target or
  interrupted episodes as successful demonstrations.
- [ ] Finalize the pilot dataset before inspection. A dataset with unclosed
  writers is invalid even if files appear present.

## QA Gate

Accept an episode only when all checks pass:

- [ ] Required keys exist in every frame: `observation.state`, `action`,
  `observation.images.gemini_rgb`, and `observation.images.white_wrist_rgb`.
- [ ] The state/action vector length is six and the joint-name order matches
  the recorded metadata.
- [ ] RGB frames decode throughout the episode; FPS and image shape are
  constant within the dataset version.
- [ ] Timestamps are monotonic and no action/state/image stream has a
  suspicious gap or duplicated sequence.
- [ ] The video visually matches the logged action phases and jar location.
- [ ] Episode success is judged by the fixed rule: jar is secured, lifted
  clear of the desk, and held for the agreed duration without collision.
- [ ] The dataset can be reopened with `LeRobotDataset`; metadata, episode
  count and statistics load after finalization.

Create an immutable accepted-episode manifest. Split train/validation/test by
episode, never by individual frames. Keep a small untouched real-robot test
set out of both training and hyperparameter selection.

## Corpus Targets

Begin with 10-15 accepted pilot demonstrations only to validate recording and
QA. Do not train a policy from that pilot unless a smoke run is explicitly
approved. For the first meaningful fixed-scene ACT corpus, target at least 50
accepted demonstrations, then set the final target from observed operator
consistency and holdout performance. Include controlled, documented variation
in jar start-cell and approach timing, but keep scene hardware fixed.

## Stop And Recovery

- Unexpected arm motion: cut 12V, stop the process, retain logs, and mark the
  episode rejected.
- Camera/serial ownership error: stop; do not bypass the shared lock or change
  device permissions.
- Dataset write/metadata failure: stop collection, preserve the raw directory
  for diagnosis, and start a new dataset revision after the fix.
- Schema drift: stop collection and create a new version; never repair an
  existing dataset by silently substituting a camera or action convention.
