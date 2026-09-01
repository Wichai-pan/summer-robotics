# Frankfurt relay deployment

This deployment publishes only the ForestBridge static dashboard and structured
task relay. It contains no robot, camera, ROS, serial or shell adapter.

Required server-local `.env` values:

```text
FORESTBRIDGE_UI_TOKEN=<browser-only token>
FORESTBRIDGE_ROBOT_TOKEN=<Jetson-only token>
```

The relay and HTTPS proxy join the existing external Docker network
`jl_default`. Only the HTTPS proxy publishes port 443. Relay state and Caddy
certificates remain in server-local directories and are not committed.
