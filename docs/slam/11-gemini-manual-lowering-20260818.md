# Gemini manual lowering record (2026-08-18)

Status: completed; the intermediate manual pose was discarded and the gimbal
was returned to the existing ACT/IK grasp reference.

## Adjustment purpose

Lower the fixed Gemini RGB-D camera pitch slightly for improved near-field
coverage. Yaw must remain unchanged. This is a manual gimbal adjustment, not a
camera intrinsic calibration.

## Before adjustment

- Last verified reference: `/data/config/gemini_gimbal_mapping_down_20deg_v1.json`
- Yaw / ID 7: raw `4066`
- Pitch / ID 8: raw `1924`
- Relative to the level-forward pitch reference (`1694`): `+230` ticks,
  approximately `20.21484375 deg` downward
- Encoder conversion used by the existing tooling: `4096 ticks / 360 deg`
- Source: `configs/slam/base_to_gemini_mapping_down_20deg_candidate.yaml` and
  the successful read-only check recorded on 2026-08-17

The 2026-08-18 pre-adjustment live read subsequently passed after gimbal power
was restored:

- Black-board serial: `5B3D043224`
- ID 7: raw `4066`, one-turn `357.36 deg`, mode `0`, torque `0`
- ID 8: raw `1924`, one-turn `169.10 deg`, mode `0`, torque `0`
- Reference deviation: ID 7 `+0.00 deg`, ID 8 `+0.00 deg`
- Tool result: `PASS`; no motor register was written

Two earlier read-only attempts failed at `ping ID 7` while the gimbal was not
successfully powered. Those failures did not alter the saved reference or motor
state.

## After adjustment

- Yaw / ID 7: raw `4066`, unchanged from the previous reference
- Pitch / ID 8: raw `2141`
- Pitch change from the previous mapping pose: `+217` ticks, approximately
  `19.072265625 deg` farther downward
- Downward angle relative to level-forward pitch raw `1694`: `+447` ticks,
  approximately `39.287109375 deg`
- ID 7 and ID 8 mode: `0`
- ID 7 and ID 8 torque: `0`
- Read-only check result: current pose intentionally falls outside the old
  reference tolerance; no motor register was written
- New reference file: unresolved; do not overwrite the existing reference
- Visual framing check: unresolved

## Integration boundary

Changing the pitch invalidates the assumption that the existing fixed
`base_link -> camera_link` candidate exactly describes the camera pose. The old
reference, transform candidate, and RTAB-Map database remain preserved. A new
pose reference and transform candidate must be created and validated before the
new pose is used for formal mapping or Nav2 localization.

## Final disposition

The manually selected `ID7=4066`, `ID8=2141` pose was not retained. The
existing supervised return tool and
`/data/config/gemini_gimbal_grasp_pose_v1.json` were used to return toward the
saved ACT/IK grasp target `ID7=4062`, `ID8=2284` at a maximum speed of
`4 deg/s`.

Final feedback after the return and a separate torque-free read-only check:

- ID 7: raw `4066`, error `-0.35 deg` from the saved grasp reference
- ID 8: raw `2286`, error `-0.18 deg` from the saved grasp reference
- Both axes: mode `0`, torque `0`
- Return result: `PASS`
- Independent reference check: `PASS` within `1.0 deg`

The saved reference file was not overwritten. This grasp pose is for the
existing ACT/IK fixed view and must not be used with the SLAM mapping-down
transform or the RTAB-Map database built at `ID7=4066`, `ID8=1924`.
