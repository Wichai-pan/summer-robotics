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
operator gates from the underlying tools in default supervised mode:

1. `PIPELINE` before any motor command;
2. mapping-gimbal `RETURN`;
3. Nav2 `PLAN`, then a separate `MOVE` before wheel torque is enabled;
4. ACT-gimbal `RETURN`;
5. ACT scene `READY`, result label and final arm-return `RETURN`.

With `--auto-demo`, one onsite `AUTO_PIPELINE` authorization replaces the
nested confirmations. The wrapper first folds the white arm for safe travel,
then runs mapping-gimbal return, Nav2 docking, grasp-gimbal return, ACT and a
final folded return. Existing motion, thermal, braking and torque-off limits
remain active, and any failed child blocks the following stages.

The default route uses the manual-push map
`/data/slam/mapping/20260830T095346Z/rtabmap.db` and the confirmed table pose
`(0.060, -0.372, -90 degrees)`. Its docking settings match the successful
fixed-table tests: 5 cm integrated-Demo XY arrival tolerance, 18 cm docking entry, wheel
feedback control, and existing supervised speed/travel/runtime caps.

## Run

On Jetson, after checking the immediate 12 V cutoff and clearing the base,
gimbal cables and arm workspace:

```bash
cd /home/jetsonl7/summer-robotics-deploy
bash scripts/jetson_nav_then_act_pick_place.sh --auto-demo --label table_pick_place_01
```

The ACT phase uses the established `jetson_act_trial.sh` defaults, including
the newer 28-epoch checkpoint and 600 steps (30 seconds). Override only a
specific value that has already been independently validated, for example
`--steps 600` or a different `--database` / goal pose.

The 2026-08-30 physical evidence, exact artifact paths, thermal failures and
new-maintainer startup checklist are in `docs/19-machine-handoff-20260830.md`.

## Boundary

This is not yet object transport to a second navigation goal. The ACT model
still performs its current local pick, short motion and release rollout after
the base docks. Treat the wrapper as a supervised integration baseline; retain
the standalone commands when isolating localization, wheel behavior, gimbal
pose or grasp failures.
