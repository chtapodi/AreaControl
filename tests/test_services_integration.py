def test_service_lifecycle_flow(load_service_area_tree):
    module = load_service_area_tree()

    module.init()
    area_tree = module.get_area_tree()
    living_light = area_tree.get_device("light_living_room_main")

    assert module.light.calls == []
    assert living_light.cached_state is None

    module.create_event(
        device_name="sensor_living_room_motion",
        tags=["auto", "motion_detected"],
    )

    assert module.light.calls == [
        ("on", {"entity_id": "light.light_living_room_main"})
    ]
    assert living_light.locked is False

    assert module.freeze_area("living_room") is True
    assert living_light.locked is True
    frozen_calls = list(module.light.calls)

    module.create_event(
        device_name="sensor_living_room_motion",
        tags=["auto", "motion_detected"],
    )

    assert module.light.calls == frozen_calls

    assert module.unfreeze_area("living_room") is True
    assert living_light.locked is False

    module.create_event(
        device_name="sensor_living_room_motion",
        tags=["auto", "motion_detected"],
    )

    assert module.light.calls[-1] == (
        "off", {"entity_id": "light.light_living_room_main"}
    )

    module.reset()
    refreshed_tree = module.get_area_tree()
    refreshed_light = refreshed_tree.get_device("light_living_room_main")
    assert refreshed_light.cached_state is None


def test_multiple_devices_share_cache(load_service_area_tree):
    module = load_service_area_tree()
    module.init()

    tree = module.get_area_tree()
    living_light = tree.get_device("light_living_room_main")
    hallway_light = tree.get_device("light_hallway")

    module.create_event(
        device_name="sensor_living_room_motion",
        tags=["auto", "motion_detected"],
    )
    module.create_event(
        device_name="sensor_hallway_motion",
        tags=["auto", "motion_detected"],
    )

    assert module.light.calls[0] == (
        "on", {"entity_id": "light.light_living_room_main"}
    )
    assert module.light.calls[1] == (
        "on", {"entity_id": "light.light_hallway"}
    )

    module.create_event(
        device_name="sensor_living_room_motion",
        tags=["auto", "motion_detected"],
    )

    assert module.light.calls[-1] == (
        "off", {"entity_id": "light.light_living_room_main"}
    )
    assert len(module.light.calls) == 3

    module.reset()
    assert module.get_area_tree().get_device("light_hallway").cached_state is None
