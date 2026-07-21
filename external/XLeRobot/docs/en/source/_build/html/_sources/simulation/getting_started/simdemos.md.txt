# More Sim Demos

### More Scenes

You can use various environments with XLeRobot following [this](https://maniskill.readthedocs.io/en/latest/user_guide/datasets/scenes.html):

- `ReplicaCAD_SceneManipulation-v1` (default)
- AI2THOR scenes
- Robocasa Kitchen counter scenes
- `OpenCabinetDrawer-v1`
    
    ![image](https://github.com/user-attachments/assets/767683be-c090-4fd7-9cfe-05fd2b4559c6)
    

### VR Integration

To enable VR with Oculus:

1. Install Oculus reader according to the (official documentation)[https://github.com/rail-berkeley/oculus_reader]
2. Replace the [reader.py](http://reader.py/) file with the provided version in `codes/VR/reader.py`:
3. Update the path of the Oculus reader folder in your configuration:
    
    ![image](https://github.com/user-attachments/assets/f05fae0f-9641-4704-bac7-dea9aa4f0092)
    
4. After putting the control code to `examples/`, run the end effector control demo with:

```bash
python -m mani_skill.examples.XLeRobot_demo_VR_ee_ctrl -e "ReplicaCAD_SceneManipulation-v1"   --render-mode="human" --shader="rt-fast" -c "pd_joint_delta_pos_dual_arm"

```

### Custom Hardware

To use different hardware versions:

1. Modify the URDF path in `agents/robots/fetch.py` to follow the files in `assets/`
2. You may need to adjust the size of `qpos` depending on your hardware configuration
    
    ![image](https://github.com/user-attachments/assets/01c5568a-46ac-4d74-95e1-c66994a72d19)
    

### Troubleshooting

#### Common Errors

- Navigate to the script and change the link name
- Navigate to the script and comment out the avoid collision list