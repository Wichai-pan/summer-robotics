### 安装LeRobot 🤗

要安装LeRobot，请按照[官方安装指南](https://huggingface.co/docs/lerobot/installation)

```{note}
建议使用`pip install -e .`以便更方便的文件传输。
```

如果您还没有配置[SO101手臂](https://huggingface.co/docs/lerobot/so101#configure-the-motors)和[其他电机](https://xlerobot.readthedocs.io/en/latest/hardware/getting_started/assemble.html#configure-motors)的电机，请进行配置。


## 移动XLeRobot文件 

打开已安装的lerobot文件夹并：

将我的SO101机器人解析逆运动学求解器移动到/model文件夹
![image](https://github.com/user-attachments/assets/87248f48-b118-470d-8e57-2b7111f054ed)

将xlerobot机器人文件夹移动到/robots文件夹。
![image](https://github.com/user-attachments/assets/335d571a-a14d-4466-b439-8384517f607b)

```{note}
如果您想基于树莓派构建，请在__init__.py中取消注释xlerobot_host和xlerobot_client。
```
将所有示例代码移动到/example文件夹。
![image](https://github.com/user-attachments/assets/f6e89ff4-7361-408a-83c6-d320bb23da98)
