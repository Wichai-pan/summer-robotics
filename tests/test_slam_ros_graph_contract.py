from pathlib import Path

from tools.slam_ros_graph_contract import analyze_graph, parse_publishers, parse_tf_chain


VALID_TF = """At time 1786537258.0
- Translation: [0.001, -0.002, 0.003]
- Rotation: in Quaternion (xyzw) [0.0, 0.0, 0.0, 1.0]
"""


def topic_info(*publishers: str) -> str:
    blocks = ["Type: example/msg/Type", f"Publisher count: {len(publishers)}"]
    for publisher in publishers:
        namespace, name = publisher.rsplit("/", 1)
        blocks.append(
            "\n".join(
                (
                    f"Node name: {name}",
                    f"Node namespace: {namespace or '/'}",
                    "Topic type: example/msg/Type",
                    "Endpoint type: PUBLISHER",
                )
            )
        )
    blocks.append(
        "\n".join(
            (
                "Subscription count: 1",
                "Node name: listener",
                "Node namespace: /rtabmap",
                "Endpoint type: SUBSCRIPTION",
            )
        )
    )
    return "\n\n".join(blocks) + "\n"


def valid_topic_info() -> dict[str, str]:
    return {
        "odom": topic_info("/rtabmap/rgbd_odometry"),
        "odom_info": topic_info("/rtabmap/rgbd_odometry"),
        "tf": topic_info("/camera/camera", "/rtabmap/rgbd_odometry"),
        "tf_static": topic_info("/camera/camera"),
    }


def test_parser_ignores_subscribers() -> None:
    count, publishers = parse_publishers(
        topic_info("/camera/camera", "/rtabmap/rgbd_odometry")
    )
    assert count == 2
    assert publishers == ["/camera/camera", "/rtabmap/rgbd_odometry"]


def test_real_camera_and_odometry_tf_publishers_pass() -> None:
    report = analyze_graph(valid_topic_info(), VALID_TF)
    assert report["status"] == "PASS"


def test_missing_camera_tf_publisher_fails() -> None:
    info = valid_topic_info()
    info["tf"] = topic_info("/rtabmap/rgbd_odometry")
    report = analyze_graph(info, VALID_TF)
    assert report["status"] == "FAIL"
    assert any("tf: expected publishers" in failure for failure in report["failures"])


def test_unexpected_tf_publisher_fails() -> None:
    info = valid_topic_info()
    info["tf"] = topic_info(
        "/camera/camera", "/rtabmap/rgbd_odometry", "/other/broadcaster"
    )
    report = analyze_graph(info, VALID_TF)
    assert report["status"] == "FAIL"
    assert any("/other/broadcaster" in failure for failure in report["failures"])


def test_motion_graph_allows_only_the_named_static_tf_publisher() -> None:
    info = valid_topic_info()
    info["tf_static"] = topic_info("/camera/camera", "/base_to_gemini_static_tf")

    report = analyze_graph(
        info,
        VALID_TF,
        expected_child_frame="base_link",
        allow_static_transform_publisher=True,
    )

    assert report["status"] == "PASS"
    assert report["expected_tf_chain"] == ["odom", "base_link"]
    info["tf_static"] = topic_info(
        "/camera/camera", "/base_to_gemini_static_tf", "/other/broadcaster"
    )
    assert analyze_graph(info, VALID_TF, allow_static_transform_publisher=True)["status"] == "FAIL"


def test_mapping_graph_allows_only_the_named_rtabmap_tf_publisher() -> None:
    info = valid_topic_info()
    info["tf"] = topic_info(
        "/camera/camera", "/rtabmap/rgbd_odometry", "/rtabmap/rtabmap"
    )
    assert analyze_graph(
        info, VALID_TF, allow_rtabmap_mapping_tf_publisher=True
    )["status"] == "PASS"
    assert analyze_graph(info, VALID_TF)["status"] == "FAIL"


def test_missing_transform_sample_fails() -> None:
    report = analyze_graph(valid_topic_info(), "Waiting for transform...\n")
    assert report["status"] == "FAIL"
    assert any("no transform block" in failure for failure in report["failures"])


def test_incomplete_or_non_finite_transform_fails() -> None:
    for tf_text in (
        "At time 123.0\n",
        VALID_TF.replace("0.001", "nan"),
        VALID_TF.replace("0.0, 0.0, 0.0, 1.0", "0.0, 0.0, 0.0, 0.0"),
    ):
        report = analyze_graph(valid_topic_info(), tf_text)
        assert report["status"] == "FAIL"


def test_duplicate_publisher_endpoint_fails() -> None:
    info = valid_topic_info()
    duplicated = topic_info("/rtabmap/rgbd_odometry", "/rtabmap/rgbd_odometry")
    info["odom"] = duplicated.replace("Publisher count: 2", "Publisher count: 1")
    report = analyze_graph(info, VALID_TF)
    assert report["status"] == "FAIL"
    assert any("parsed 2 endpoints" in failure for failure in report["failures"])
    assert any("duplicate publisher" in failure for failure in report["failures"])


def test_redacted_real_tf_topic_info_fixture_parses() -> None:
    fixture = Path(__file__).parent / "fixtures" / "ros2_topic_info_tf.txt"
    count, publishers = parse_publishers(fixture.read_text(encoding="utf-8"))
    assert count == 2
    assert publishers == ["/camera/camera", "/rtabmap/rgbd_odometry"]


def test_complete_transform_is_parsed() -> None:
    transform = parse_tf_chain(VALID_TF)
    assert transform["stamp_s"] == 1786537258.0
    assert transform["translation"] == [0.001, -0.002, 0.003]
    assert transform["quaternion"] == [0.0, 0.0, 0.0, 1.0]


def test_real_humble_tf2_echo_fixture_parses() -> None:
    fixture = Path(__file__).parent / "fixtures" / "tf2_echo_odom_camera_link.txt"
    transform = parse_tf_chain(fixture.read_text(encoding="utf-8"))
    assert transform["stamp_s"] == 1786537258.26054
    assert transform["quaternion"] == [0.0, 0.0, 0.0, 1.0]
