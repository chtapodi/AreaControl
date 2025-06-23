import types
from .conftest import load_area_tree


def test_create_event_builds_dict():
    area_tree = load_area_tree()
    events = []

    class DummyEventManager:
        def create_event(self, event):
            events.append(event)

    area_tree.event_manager = DummyEventManager()

    area_tree.create_event(
        name="device1",
        tags=["on"],
        state={"status": 1},
        scope_functions=["scope"],
        state_functions=["state"],
    )

    assert events == [
        {
            "device_name": "device1",
            "tags": ["on"],
            "state": {"status": 1},
            "scope_functions": ["scope"],
            "state_functions": ["state"],
        }
    ]


def test_create_event_forwards_to_event_manager():
    area_tree = load_area_tree()

    class DummyEventManager:
        def __init__(self):
            self.called = 0
            self.events = []

        def create_event(self, event):
            self.called += 1
            self.events.append(event)

    manager = DummyEventManager()
    area_tree.event_manager = manager

    area_tree.create_event(device_name="my_device")

    assert manager.called == 1
    assert manager.events == [{"device_name": "my_device"}]
