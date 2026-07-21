Here's the urdf files, assets, and EE control codes in Maniskill.

## Update

XLeRobot files are exclusively listed instead of borrowing fetch's name. So there are a few more modifications need to be done to run XLeRobot in the ReplicaCAD scene, in addtion to the [previous tutorial](https://xlerobot.readthedocs.io/en/latest/simulation/getting_started/index.html) 

For new robot ids, you need to add them to ReplicaCAD scene first.
<img width="798" height="583" alt="image" src="https://github.com/user-attachments/assets/b5a6832b-73bf-489e-9a71-fd0fb13146a3" />

As well as the agent/robots/init.py
<img width="798" height="583" alt="image" src="https://github.com/user-attachments/assets/89c8fd71-2306-4963-8717-257795d8f8f1" />


## Run the examples

You also need to add the robot id in the command. For example, if you want to run a single-arm version of XLeRobot:

```
python -m mani_skill.examples.demo_ctrl_action_ee_keyboard_single -e "ReplicaCAD_SceneManipulation-v1" -r "xlerobot_single"  --render-mode="human" --shader="rt-fast" -c "pd_joint_delta_pos"
```
