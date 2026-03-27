from modules.color_mapper import ColorMapper


def test_calibration_only_mapping():
    mapper = ColorMapper(
        defaults={"hue": [1.0, 1.0, 1.0]},
        config_data={
            "reference_profile": "hue",
            "profiles": {"kauf": {"calibration": [0.5, 1.0, 1.0]}},
        },
    )
    assert mapper.to_profile([100, 100, 100], target_profile="kauf") == [50, 100, 100]


def test_weighted_sample_mapping():
    mapper = ColorMapper(
        defaults={"hue": [1.0, 1.0, 1.0], "kauf": [1.0, 1.0, 1.0]},
        config_data={
            "reference_profile": "hue",
            "mappings": {
                "hue": {
                    "kauf": {
                        "samples": [
                            {"source": [0, 0, 255], "target": [0, 0, 200]},
                            {"source": [255, 0, 0], "target": [240, 0, 0]},
                        ],
                    }
                }
            },
        },
    )
    assert mapper.to_profile([128, 0, 128], target_profile="kauf") == [120, 0, 100]


def test_rgb_to_color_temp_mapping():
    mapper = ColorMapper(
        defaults={"hue": [1.0, 1.0, 1.0]},
        config_data={
            "reference_profile": "hue",
            "profiles": {
                "kauf": {
                    "calibration": [1.0, 1.0, 1.0],
                    "rgb_to_color_temp": {
                        "samples": [
                            {"source": [255, 160, 120], "target": 2200},
                            {"source": [255, 255, 255], "target": 4000},
                        ],
                        "distance_bias": 1.0,
                    },
                }
            },
        },
    )
    temp = mapper.to_color_temp([255, 200, 160], target_profile="kauf")
    assert 2200 <= temp <= 4000
