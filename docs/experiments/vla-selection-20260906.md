# VLA 选型：Roihu 微调、Jetson 本机推理

日期：2026-09-06。范围：官方仓库/文档调研及只读内存检查；未下载权重、未提交训练、未启动推理或硬件。结论是候选优先级，不是部署成功证明。

## 目标与结论

在已有白臂双 RGB 相机拿放数据上，比较预训练 VLA 与已验证 ACT 的迁移效果，同时满足 Jetson 本机内存及闭环延迟要求。保留 ACT；首选 SmolVLA，X-VLA 为备用；LingBot-VLA 适合后续算力较充裕的探索，不作为当前 8GB 本机部署首选。

## 已确认资源与未知项

- 项目记录：Jetson Orin Nano Super；2026-09-06 SSH `free -h`：总内存 7.4 GiB、可用 5.9 GiB、swap 3.7 GiB。可用内存只是检查时快照，不能当作运行导航/相机后仍可用的预算；GPU 与 CPU 共用物理内存。
- CSC 官方：Roihu GPU 为 GH200，每芯片 96 GiB GPU 内存，GPU 节点为 ARM CPU。项目曾在 GH200 完成 ACT 训练；本次未核查当前配额、排队、环境和可用分配。
- 现有文档记录 28 episodes、19,309 frames、20 Hz，两路 RGB，以及六维混合动作（关节/夹爪位置与 wrist_roll 速度）。本次没有审计原始数据完整性。
- 参数量不能直接等同峰值内存。仅作理论权重估算：450M×2 bytes≈0.9GB；0.9B≈1.8GB；4B≈8GB；6B≈12GB。未包括激活、图像处理、缓存、CUDA 工作区和系统内存，亦未验证任何量化部署。

## 候选池与优先级

| 候选 | 角色/等级 | 已核对信息 | 当前结论 |
|---|---|---|---|
| 当前 ACT | 已有基线；必须保留 | 已在本机执行；见 docs/12-act-v2-28episode-grasp-log.md | 比较参照，不覆盖 |
| SmolVLA 450M | 资源匹配候选；优先 | LeRobot 原生，官方有自定义数据微调与部署说明 | 最先做双图像离线推理基准；本机性能未验证 |
| X-VLA 0.9B | 备用候选 | LeRobot 集成、跨机器人 soft prompt 适配、自定义动作映射 | 更大、适配更复杂；无本机实测结论 |
| LingBot-VLA 4B / VLA 2.0 6B | 后续探索；当前非首选 | 公开权重与训练代码 | 标准16位权重即逼近/超过本机总内存，不能承诺8GB实时部署 |
| GR00T N1.7 | 文献/后续平台候选 | 官方推理最低16GB+，训练最低40GB+；Orin测试为64GB平台 | 不符合当前硬件的标准部署门槛 |
| pi0 / pi0.5（openpi） | 后续服务器候选 | 官方推理>8GB，LoRA>22.5GB，全量微调>70GB | Roihu值得探索，当前8GB标准本机部署不匹配 |
| OpenVLA | 次要参考 | 官方仓库公开训练/部署实现，7B路线 | 优先级低于轻量原生LeRobot方案，不做当前第一轮 |

以上为工程适配排序，不是跨模型成功率排行榜。官方不同平台、不同数据上的指标不能直接拿来证明在本项目中更强。

## 最小公平对照与风险

- 使用相同示范筛选和 episode 级留出划分；沿用24训练/4留出前先确认原数据版本。不得把相邻帧随机分到两组。
- 显式记录 VLA 使用外部预训练数据，不能宣称同等总数据/算力条件下优于 ACT。
- 相机身份、图像预处理、状态顺序、位置/速度单位及20Hz时间语义逐项核对。不能把 wrist_roll.vel_deg_s 当作位置角度。
- 记录模型与代码revision、精度、batch、相机数、输入尺寸、chunk长度、去噪步数、训练步数和调参次数。
- 离线指标：动作误差、逐维误差/跳变、NaN/Inf、输出范围、加载峰值与稳态内存、冷启动、预处理加推理的p50/p95延迟。
- 开环动作误差低不等于实机成功率高；手部闭环偏移、接触和抓取需现场验收。
- 原数据是单物体固定场景拿放，不能据此宣称任意物体抓取、任务语言泛化或带物导航已经实现。

## 建议执行顺序与停止条件

1. 原始数据只读审计，制作小型双相机样例和明确的动作映射；不改原数据。
2. 在独立环境加载 SmolVLA，用录制数据做不连接相机/电机的推理。先检查部署可行性，再投入完整微调。
3. 若获得空闲设备时段，在 Jetson 跑隔离的离线性能测试；即使不驱动电机，GPU/内存压测也可能影响队友任务，不能直接抢资源。
4. Roihu 单GPU微调冒烟测试，然后正式对照。环境须核对ARM依赖，不照搬x86安装命令；未实测前不承诺训练时长。
5. 推理执行率与模型更新率分开记录：20Hz执行可消费动作chunk，但异步并不能消除旧观测和长推理延迟。
6. 若加载/推理挤占系统、持续swap、延迟无法满足选定执行窗口，则暂停完整训练；先调整部署或选择备用模型。
7. 队友现场监督A/B测试后，才决定是否替换默认策略。保留当前导航和资源互斥逻辑。

## 官方来源

- SmolVLA：https://huggingface.co/docs/lerobot/main/smolvla
- LeRobot代码：https://github.com/huggingface/lerobot
- SmolVLA权重：https://huggingface.co/lerobot/smolvla_base
- X-VLA：https://github.com/2toinf/X-VLA
- X-VLA适配文档：https://huggingface.co/docs/lerobot/main/xvla
- LingBot-VLA：https://github.com/Robbyant/lingbot-vla
- LingBot-VLA 2.0：https://github.com/Robbyant/lingbot-vla-v2
- GR00T硬件要求：https://github.com/NVIDIA/Isaac-GR00T/blob/main/getting_started/hardware_recommendation.md
- openpi：https://github.com/Physical-Intelligence/openpi
- OpenVLA：https://github.com/openvla/openvla
- Roihu规格：https://docs.csc.fi/computing/systems-roihu/

后续可研究 https://github.com/VinRobotics/vla.cpp 的推理加速，但它不是上述模型的官方训练仓库。不同checkpoint导出、动作归一化、数值一致性和双相机支持均需单独验证，不把支持CUDA视为已经支持本机器人。
