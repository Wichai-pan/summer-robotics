# VLA (3) pi0.5

<video width="100%" controls>
  <source src="https://vector-wangel.github.io/XLeRobot-assets/videos/Community/pi05_XLeRobot.mp4" type="video/mp4">
  Your browser does not support the video tag.
</video>

本文档提供了关于XLeRobot的**pi0.5** VLA（视觉-语言-动作）实现的信息，支持双臂。

## 概述

pi0.5实现包括对数据收集脚本和双臂遥操作、数据收集和推理工作流的优化。一些更改在本地分支中可用以供参考。

## 实现细节

### XLeRobot Fork
- **仓库**: [xuweiwu/XLeRobot](https://github.com/xuweiwu/XLeRobot)
- **分支**: `pi05 dual arm`
- **功能**: 双臂设置的遥操作、数据收集和推理

### OpenPI Fine-tuning
- **仓库**: [xuweiwu/openpi](https://github.com/xuweiwu/openpi)
- **分支**: `biso101 training_support`
- **功能**: 双手SO-101配置的训练支持

## 状态

已创建一个小型PR以优化现有的数据收集脚本工作流。可能更难合并的其他更改目前在本地分支中可用以供参考。

## 相关链接

- [XLeRobot Fork (pi0.5)](https://github.com/xuweiwu/XLeRobot)
- [OpenPI Fork (biso101 training)](https://github.com/xuweiwu/openpi)

