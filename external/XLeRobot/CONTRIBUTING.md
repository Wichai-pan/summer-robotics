# Contributing to XLeRobot 🤖

**👋 Want to contribute to XLeRobot?**

If you have a bug or an idea, read the guidelines below before opening an issue.

If you're ready to tackle some open issues, we've collected some [good first issues](https://github.com/Vector-Wangel/XLeRobot/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) for you.
You can also create an issue yourself to tackle the tasks below, following the template.

## 🚀 What We're Looking For

### Software Development (High Priority)
- **Computer Vision**: YOLO object detection and segmentation, depth estimation, gesture recognition
- **Navigation**: LIDAR/RGBD/Stereo/RGB-based navigation, path planning, obstacle avoidance  
- **Simulation**: Isaac Sim integration, MuJoCo improvements, etc
- **VLA Integration**: VLA models (Pi0, SmolVLA) migration from single SO101 arm
- **User Interfaces**: Web control, mobile apps, voice recognition
- **Hardware Support**: More cameras (realsense, oak camera, etc), tactile sensing, additional sensors
- **RL Training**: Stable and generalizable RL algorithms, sim2real transfer, benchmark environments
- **VLM/LLM/MCP**: Inference pipelines, task planning, multimodal reasoning, MCP tool integration
- **Your Own Research Ideas**: Novel robotics research, embodied AI algorithms, innovative applications

### Advocacy & Community Building
- **Share Your Experiences**: Document your XLeRobot journey, challenges, and successes
- **Educational Use Cases**: Robotics courses, workshops, student projects, and learning materials
- **Community Events**: Organize hackathons, meetups, and collaborative projects
- **Real-world Applications**: Industrial pilots, research projects, and practical deployments
- **Content Creation**: Blog posts, videos, tutorials, and social media showcasing XLeRobot capabilities

### Documentation & Examples
- Tutorials and guides update (especially video)
- Code examples
- API documentation
- Your own video demos 

### Minor Hardware Fix and Upgrades

**Note**: The hardware design is fairly settled. Most contributions should focus on software, examples, and documentation. For major hardware changes, please discuss in issues first!

## 🤝 How to Contribute

### 1. Before You Start
- **Check existing issues** - someone might already be working on it
- **Comment on the issue** - let others know your approach
- **Small PRs are better** - easier to review and merge


### 2. Proposing Your Approach
When you want to work on an issue:

**Comment with your proposal like this:**
```
I'd like to work on this! My approach:
- Use OpenCV + YOLO11 for object detection
- Create a ROS2 wrapper for easy integration  
- Add examples for common objects (bottles, cups, etc.)
- Timeline: ~2 weeks

Let me know if this sounds good or if you have suggestions!
```

This helps avoid duplicate work and gets feedback early.

### 3. Submitting Code
- Fork → Branch → Code → Test → PR
- Include examples when adding new features
- Update README if needed
- Reference the issue: `Fixes #123`

## 🏷️ Issue Labels We Use

- `good first issue` - Perfect for newcomers
- `help wanted` - Community help needed  
- `bug` - Something broken
- `enhancement` - New features
- `documentation` - Docs improvements

**Areas:**
- `area: vision` - Computer vision
- `area: navigation` - Navigation/planning
- `area: simulation` - Sim environments
- `area: ai` - AI/ML features
- `area: hardware` - Hardware integration

## 📝 Guidelines

### Code Style
- Follow existing patterns in the codebase
- Test your changes (at least run the examples)

### Hardware Contributions
- **No major hardware redesigns** without discussion first
- Keep cost increases minimal
- Don't make assembly significantly harder

### What NOT to Do
- Don't submit PRs without first commenting on an issue
- Don't duplicate existing functionality without good reason
- Don't add heavy dependencies without discussion
- Don't break existing examples

## 🆘 Getting Help

- **Discord**: [XLeRobot Community](https://discord.gg/bjZveEUh6F)
- **Documentation**: [https://xlerobot.readthedocs.io/](https://xlerobot.readthedocs.io/)
- **Issues**: For bugs and feature requests
- **Discussions**: For questions and brainstorming

## 🎯 Quick Start

1. Look for [`good first issue`](https://github.com/Vector-Wangel/XLeRobot/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22) labels
2. **Comment your approach** before starting
3. Fork, code, test, PR
4. Celebrate! 🎉

---

Thanks for contributing to making embodied AI accessible to everyone! 🤖✨
