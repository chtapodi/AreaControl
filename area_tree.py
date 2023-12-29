import yaml
from collections import defaultdict
import copy
import time


STATE_VALUES = {
    "input": {
        "status": 0,
        "baud_duration": 0,
        "elapsed_time": 0,
    },
    "output": {"status": 0, "rgb": [0, 0, 0], "brightness": 0, "temperature": 0},
}


def merge_states(state_list, name=None):

    if len(state_list)==1 : #Case where merge does not need to happen
        return state_list[0]

    log.info(f"\nMERGING {state_list}")

    all_keys = set()
    for d in state_list:
        state_keys = []
        for key, value in d.items():
            if not type(value) == dict:  # Don't use nested state keys
                state_keys.append(key)

        all_keys.update(state_keys)  # Gather all unique keys

    if len(all_keys) == 0:
        return {}

    merged_state = {}

    # Find shared values
    for key in all_keys:
        values = set()
        for dict_ in state_list:
            if key in dict_:
                log.info(f"key {key}")

                values.add(dict_[key])  # Gather values for present keys
        if len(values) == 1:  # Shared if all present values are identical
            merged_state[key] = values.pop()

    # Find individual values
    for dict_ in state_list:
        log.info(f"dict {dict_}")

        individual_state = {}
        for key, value in dict_.items():
            if key!="name" and key not in merged_state:  # Filter for non-shared keys
                individual_state[key] = value
        if len(individual_state.keys())>0 :
            merged_state[dict_["name"]] = individual_state

    if name is not None :
        merged_state["name"]=name
    return merged_state


class Area:
    def __init__(self, name):
        self.name = name
        self.children = []
        self.direct_children = []
        self.parent = None

    def add_parent(self, parent):
        self.parent = parent

    def add_child(self, child, direct=False):
        if child is not None and child.name is not None:
            self.children.append(child)
            if direct:
                self.direct_children.append(child)

    def get_children(self):
        return list(set(self.children + self.direct_children))

    def set_state(self, state):
        for child in self.get_children():
            child.set_state(copy.deepcopy(state))

    def get_state(self):
        child_states = []

        for child in self.get_children():
            child_state = child.get_state()
            child_states.append(child_state)

        merged = merge_states(child_states, self.name)
        if len(child_states) > 1:
            log.info(f"{self.name}: Merged {len(child_states)} states {merged}")
        log.info(f"\n")

        return merged


@pyscript_compile
def load_yaml(path):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data


class RuleManager:
    def __init__(self, rules_file):
        self.rules = self.load_rules(rules_file)

    def load_rules(self, rules_file):
        data = load_yaml(rules_file)
        rules = {}
        for rule_name, rule_data in data.items():
            rules[rule_name] = {
                "input_type": rule_data["input_type"],
                "function": rule_data["function"],
                "args": rule_data["args"],
            }
        return rules

    def create_event(self, event_string):
        for rule_name, rule in self.rules.items():
            if event_string in rule_name:
                print(f"Rule '{rule_name}' {self.rules[rule_name]}")
                return


def create_area_tree(yaml_file):
    """
    Loads areas from a YAML file and creates a hierarchical structure of Area objects.

    Args:
        yaml_file: Path to the YAML file containing area definitions.

    Returns:
        A dictionary mapping area names to their corresponding Area objects.
    """

    data = load_yaml(yaml_file)

    area_tree = {}
    area_names = set()  # Track unique area names

    def create_area(name):
        """Creates an Area object, ensuring unique names."""
        if name not in area_names:
            area = Area(name)
            area_tree[name] = area
            area_names.add(name)
            return area
        else:
            return area_tree[name]  # Reuse existing object

    # Create initial areas
    for area_name, area_data in data.items():
        if area_name is not None:
            area = create_area(area_name)

            # Create child and direct child relationships
            for child_type in ["sub_areas", "direct_sub_areas"]:
                if child_type in area_data:
                    for child_name in area_data[child_type]:
                        child_area = create_area(child_name)
                        child_area.add_parent(area)
                        direct = child_type == "sub_areas"
                        area.add_child(child_area, direct=direct)

            # Add outputs as children
            if "outputs" in area_data:
                for output in area_data["outputs"]:
                    if output is not None:
                        if "kauf" in output:
                            new_light = KaufLight(output)
                            new_device = Device(new_light)
                            area.add_child(new_device, direct=True)

    return area_tree


class Device:
    """Acts as a wrapper/driver for a device type -- interfaces between states and devices."""

    def __init__(self, driver):
        self.driver = driver

        self.name = driver.name

        self.last_state = None

        self.cached_state = None

    def get_state(self):
        state = self.driver.get_state()
        state["name"] = self.name
        self.last_state = state
        log.info(f"{self.name}: gotten state {state}")

        return state

    def set_state(self, state):
        if "status" not in state.keys():
            log.info(f"{self.name}: State does not contain status {state}. Caching")

            self.cached_state = state

        else:
            log.info(f"{self.name}: State contains status {state}")

            for key, val in self.cached_state.items():
                if key not in state.keys():
                    # print(f"filling out state with {key}:{val}")
                    log.info(f"filling out state with {key}:{val}")

                    state[key] = val
            log.info(f"Setting state {state}")

            self.driver.set_state(state)
            self.last_state = state

    def get(self, value):
        return self.last_state[value]


class KaufLight:
    """Light driver for kauf bulbs"""

    def __init__(self, name):
        self.name = name
        self.last_state = None
        self.color = None
        self.temperature = None

    # Status (on || off)
    def set_status(self, status, edit=0):
        """Sets the status of the light (on or off)"""

        if status == 1 or status == "on" or status == "1":
            self.apply_values(rgb_color=str(self.color))

        else:
            light.turn_off(entity_id=f"light.{self.name}")

    def get_status(self):
        """Gets status"""

        try:
            status = state.get(f"light.{self.name}")

            return status
        except:
            pass
        return "unknown"

    def is_on(self):
        status = self.get_status()
        if status is None or "off" in status or "unknown" in status:
            return False
        return True

    # RGB (color)
    def set_rgb(self, color, apply=False):
        self.color = color
        if apply or self.is_on():
            self.apply_values(rgb_color=self.color)

    def get_rgb(self):
        color = state.get(f"light.{self.name}.rgb_color")

        return color if color != "null" else None

    # Brightness
    def set_brightness(self, brightness, apply=False):
        self.apply_values(brightness=str(brightness))

    def get_brightness(self):
        brightness = 0
        try:
            brightness = state.get(f"light.{self.name}.brightness")
        except:
            pass
        if brightness is None:
            brightness = 0
        self.brightness = brightness

        return brightness

    def set_temperature(self, temperature, apply=False):
        self.temperature = temperature
        self.apply_values(color_temp=self.temperature)

    def get_temperature(self):
        temperature = state.get(f"light.{self.name}.color_temp")

        return temperature if temperature != "null" else None

    def set_state(self, state):
        """
        Converts state to kauf specific values.
        Only does anything if state value is present, including changing brightness.
        """
        if "status" in state.keys():
            if not state["status"]:  # if being set to off
                state["off"] = 1

            del state["status"]

            self.apply_values(**state)

    def get_state(self):
        state = {}
        state["status"] = self.is_on()
        state["brightness"] = self.get_brightness()
        rgb = self.get_rgb()
        if rgb is not None:
            state["rgb"] = rgb

        temperature = self.get_temperature()
        if temperature is not None:
            state["temperature"] = temperature

        return state

    # Apply values
    def apply_values(self, **kwargs):
        """This parses the state that is passed in and sends those values to the light."""
        if "off" in kwargs and kwargs["off"]:  # If "off" : True is present, turn off
            self.last_state = {"off": True}
            light.turn_off(entity_id=f"light.{self.name}")

        else:
            new_args = {}
            for k, v in kwargs.items():
                if v is not None:
                    new_args[k] = v

            # If being turned on and no rgb present, rgb color is set to value.
            if "rgb_color" not in new_args.keys() or new_args["rgb_color"] is None:
                if not self.is_on():  # if it is off set it to the saved color
                    new_args["rgb_color"] = self.default_color

            try:
                light.turn_on(entity_id=f"light.{self.name}", **new_args)
                self.last_state = new_args

            except Exception as e:
                log.warning(
                    f"\nPYSCRIPT: [ERROR 0/1] Failed to set {self.name} {new_args}: {e}"
                )
                light.turn_on(entity_id=f"light.{self.name}")
                self.last_state = {"on": True}


@service
def test_classes():
    rules_manager = RuleManager("./pyscript/rules.yml")

    log.info("\nPYSCRIPT: Starting")
    area_tree = create_area_tree("./pyscript/layout.yml")
    log.info("\nPYSCRIPT: ####Created#####\n\n")

    # visualize_areas(area_tree)

    living_room = area_tree["living_room"]
    # log.info(f"APPLYING RED\n")
    # living_room.set_state({"rgb_color": [255, 0, 0]})
    # # time.sleep(10)
    # log.info(f"APPLYING ON\n")

    # living_room.set_state({"status": 1})
    lv_state = living_room.get_state()
    log.info(f"lv_state {lv_state}\n")
