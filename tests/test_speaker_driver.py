import types
from tests.conftest import load_area_tree

def test_speaker_driver_volume():
    area_tree = load_area_tree()
    calls = []
    area_tree.media_player = types.SimpleNamespace(volume_set=lambda **kw: calls.append(kw))
    SpeakerDriver = area_tree.SpeakerDriver
    driver = SpeakerDriver('living_room')
    # ensure filter_state removes invalid keys
    filtered = driver.filter_state({'volume': 0.5, 'invalid': 1})
    assert filtered == {'volume': 0.5}
    driver.set_state({'volume': 0.7})
    assert calls and calls[0]['volume_level'] == 0.7
