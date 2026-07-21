### Install LeRobot 🤗

To install LeRobot, follow the [official Installation Guide](https://huggingface.co/docs/lerobot/installation)

```{note}
It's recommended to use `pip install -e .` for a more convenient file transfer.
```

Configure the motors for [SO101 arms](https://huggingface.co/docs/lerobot/so101#configure-the-motors) and [other motors](https://xlerobot.readthedocs.io/en/latest/hardware/getting_started/assemble.html#configure-motors) if you haven't done so.


## Move XLeRobot files 

Open the installed lerobot folder and:

Move my analytical IK solver for SO101 robot to the /model folder
![image](https://github.com/user-attachments/assets/87248f48-b118-470d-8e57-2b7111f054ed)

Move xlerobot robot folder the /robots folder.
![image](https://github.com/user-attachments/assets/335d571a-a14d-4466-b439-8384517f607b)

```{note}
If you want to build based on RaspberryPi, uncomment xlerobot_host and xlerobot_client in __init__.py.
```
Move all the example codes to /example folder.
![image](https://github.com/user-attachments/assets/f6e89ff4-7361-408a-83c6-d320bb23da98)

