# Supervised Nav2-to-ACT pick/place pipeline (2026-08-25)

## Purpose

`scripts/jetson_nav_then_act_pick_place.sh` is a new, optional host-side
orchestrator for the current MVP: navigate to the confirmed table docking pose,
then restore the Gemini grasp pose and run the existing supervised ACT
pick/place trial. It calls existing scripts rather than replacing them, so all
individual mapping, localization, navigation, gimbal and ACT tests remain
available for diagnosis and unit tests.

## Sequence and gates

The wrapper stops immediately when a child command fails. It retains the
operator gates from the underlying tools:

1. `PIPELINE` before any motor command;
2. mapping-gimbal `RETURN`;
3. Nav2 `PLAN`, then a separate `MOVE` before wheel torque is enabled;
4. ACT-gimbal `RETURN`;
5. ACT scene `READY`, result label and final arm-return `RETURN`.

The default route uses the manual-push map
`/data/slam/mapping/20260825T131710Z/rtabmap.db` and the confirmed table pose
`(0.052, -0.357, -90 degrees)`. Its docking settings match the successful
short-table tests: 2.5 cm XY arrival tolerance, 18 cm docking entry, wheel
feedback control, and existing supervised speed/travel/runtime caps.

## Run

On Jetson, after checking the immediate 12 V cutoff and clearing the base,
gimbal cables and arm workspace:

```bash
cd /home/jetsonl7/robot-data/tmp/nav2-rotation-guard-20260822
bash scripts/jetson_nav_then_act_pick_place.sh --label table_pick_place_01
```

The ACT phase uses the established `jetson_act_trial.sh` defaults, including
the newer 28-epoch checkpoint and 600 steps (30 seconds). Override only a
specific value that has already been independently validated, for example
`--steps 600` or a different `--database` / goal pose.

## Boundary

This is not yet object transport to a second navigation goal. The ACT model
still performs its current local pick, short motion and release rollout after
the base docks. Treat the wrapper as a supervised integration baseline; retain
the standalone commands when isolating localization, wheel behavior, gimbal
pose or grasp failures.
