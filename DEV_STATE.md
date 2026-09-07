# Development State

September 7 superseding update: SmolVLA synthetic CUDA forward/backward/inference
passed on Roihu (`1094450`); a 100-step training run on old ACT episodes 0–23
completed and saved checkpoint `outputs/1094687/train/checkpoints/000100/pretrained_model`
under the independent `summer-robotics-smolvla` root. Saved-model/held-out-input
validation also passed (`1094988`): the checkpoint reloaded and decoded finite
six-dimensional actions from held-out episode 24. Two of eighteen decoded
components exceeded the recorded corpus range, including a physically meaningless
negative gripper position, so executors must clamp to trusted bounds. The
training pipeline is therefore available end to end, but no Jetson inference or
physical VLA execution was tested. See `docs/experiments/smolvla-validation-20260907.md`. User reports basket
transport was infeasible: arm-held transport is now intended, not yet validated.
Teammates published map and navigation commits `046834c` and `8fefd78`; these were
merged without overwriting their work. The paragraph below records September 6
context, not the current GPU or publication status.

Updated 2026-09-06 (confirmed facts and explicitly labelled plans): ForestBridge has an operator-verified fixed-scene baseline combining manual-push RGB-D mapping, localization, Nav2 table docking, ACT face-cream pick/local-place and arm recovery; grasp success is inconsistent and thermal/communication safeguards remain mandatory. The robot is now with teammates, while the original developer works remotely. A September 6 review found continuous table/sofa routes retaining camera/RTAB-Map/Nav2 across stages; sofa-to-table run `20260906T083342Z` had six PASS reports, but teammate code changes were still unpublished and were not overwritten by this work. The map and launch instructions in `docs/19-machine-handoff-20260830.md` are historical baseline references, not the latest teammate configuration. The proposed next task is medicine-bottle/water delivery; VR dual-arm versus single-arm recording and basket versus held transport remain undecided, and no new task dataset exists. Preserve ACT while preparing SmolVLA in the separate Roihu root `/scratch/project_2016517/panh/summer-robotics-smolvla`, with LeRobot pinned to `22bd7a2f489b367d8df42de803b1e8c4ca63a3f9`, CSC CUDA PyTorch 2.10 and PyAV; environment installation and model/training imports passed, but GPU forward/backward, new-data training and Jetson inference are not yet verified. Core files are `scripts/roihu_smolvla_bootstrap.sh`, `jobs/roihu_smolvla.sh`, `tools/smolvla_train.py` and `tools/smolvla_smoke.py`; two local unit tests and shell syntax checks passed. See `docs/experiments/progress-20260906.md` for handoff evidence and `docs/experiments/smolvla-roihu-setup-20260906.md` for paths, verification limits and commands. Next: run the isolated GPU smoke, settle the recording/action schema, upload versioned demonstrations with an episode-level holdout, validate a short training run and benchmark inference offline before supervised robot deployment. Do not equate program PASS with physical grasp success or assume the public web worker is connected to real motion; current end-to-end web motion remains unverified in this review.
