# VLA (3) pi0.5

<video width="100%" controls>
  <source src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/pi05_XLeRobot.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

This document provides information about the **pi0.5** VLA (Vision-Language-Action) implementation for XLeRobot with dual-arm support.

## Overview

The pi0.5 implementation includes optimizations for data collection scripts and dual-arm teleoperation, data collection, and inference workflows. Some changes are available in local branches for reference.

## Implementation Details

### XLeRobot Fork
- **Repository**: [xuweiwu/XLeRobot](https://github.com/xuweiwu/XLeRobot)
- **Branch**: `pi05 dual arm`
- **Features**: Teleoperation, data collection, and inference for dual-arm setup

### OpenPI Fine-tuning
- **Repository**: [xuweiwu/openpi](https://github.com/xuweiwu/openpi)
- **Branch**: `biso101 training_support`
- **Features**: Training support for bimanual SO-101 configuration

## Dataset

The collected dataset for pi0.5 training is available on Hugging Face:

- **Dataset**: [xuweiwu/bimanual-toy-box-cleanup](https://huggingface.co/datasets/xuweiwu/bimanual-toy-box-cleanup)

You can visualize the dataset using the LeRobot dataset visualization tool:

```bash
lerobot-visualize-dataset xuweiwu/bimanual-toy-box-cleanup
```

Alternatively, you can view it directly on Hugging Face using the [lerobot/visualize_dataset](https://huggingface.co/spaces/lerobot/visualize_dataset) space.

## Status

A minor PR has been created to optimize the existing data collection script workflow. Additional changes that may be more difficult to merge are currently available in local branches for reference.

## Related Links

- [XLeRobot Fork (pi0.5)](https://github.com/xuweiwu/XLeRobot)
- [OpenPI Fork (biso101 training)](https://github.com/xuweiwu/openpi)