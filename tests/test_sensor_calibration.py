import yaml
from .test_caching import load_area_tree

area_tree = load_area_tree()
ThermometerDriver = area_tree.ThermometerDriver
HumiditySensorDriver = area_tree.HumiditySensorDriver


def test_thermometer_calibration(tmp_path):
    cfg = tmp_path / "cal.yml"
    driver = ThermometerDriver("temp1", config_path=str(cfg))
    driver.calibrate(2.5)
    with open(cfg) as f:
        data = yaml.safe_load(f)
    assert data["thermometers"]["temp1"] == 2.5


def test_humidity_calibration(tmp_path):
    cfg = tmp_path / "cal.yml"
    driver = HumiditySensorDriver("hum1", config_path=str(cfg))
    driver.calibrate(-1.0)
    with open(cfg) as f:
        data = yaml.safe_load(f)
    assert data["humidity_sensors"]["hum1"] == -1.0

