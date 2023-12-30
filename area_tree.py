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

## RULES ##
#These must have an interface that mathes the following and returns boolean

def check_time(event, area_state, **kwargs):
    # returns tags based on time
    tags=[]

    if now<5 :
        tags.append("late_night")

    if now>18:
        if now < 20:
            tags.append("evening")
        else :
            tags.append("night")
    else:
        tags.append("day")
    return tags


def check_sleep(event, area_state,) :
    is_theo_alseep=state.get('binary_sensor.xavier_is_sleeping')
    log.info(f"theo sleep {is_theo_alseep}")

def merge_states(state_list, name=None):
    if len(state_list) == 1:  # Case where merge does not need to happen
        return state_list[0]

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
                values.add(dict_[key])  # Gather values for present keys

        if len(values) == 1:  # Shared if all present values are identical
            merged_state[key] = values.pop()

    # Find individual values
    for dict_ in state_list:
        individual_state = {}

        for key, value in dict_.items():
            if key != "name" and key not in merged_state:  # Filter for non-shared keys
                individual_state[key] = value

        if len(individual_state.keys()) > 0:
            merged_state[dict_["name"]] = individual_state

    if name is not None:
        merged_state["name"] = name

    return merged_state


class Area:
    def __init__(self, name):
        self.name = name
        self.children = []
        self.direct_children = []
        self.devices = []
        self.parent = None

    def add_parent(self, parent):
        self.parent = parent

    def add_child(self, child, direct=False):
        if child is not None and child.name is not None:
            self.children.append(child)
            if direct:
                self.direct_children.append(child)

    def add_device(self, device):
        if device is not None and device.name is not None:
            self.devices.append(device)

    def get_devices(self):
        return self.devices

    def get_children(self, exclude_devices=False):
        if exclude_devices:
            return list(set(self.children + self.direct_children))

        return list(set(self.children + self.direct_children + self.devices))

    def get_direct_children(self):
        return list(set(self.direct_children ))


    def get_parent(self):
        return self.parent

    def has_children(self, exclude_devices=False):
        return len(self.get_children(exclude_devices)) > 0


    def set_state(self, state):
        for child in self.get_children():
            child.set_state(copy.deepcopy(state))

    def get_state(self):
        child_states = []

        for child in self.get_children():
            child_state = child.get_state()
            child_states.append(child_state)

        merged = merge_states(child_states, self.name)

        return merged

    def pretty_print(self, indent=1, is_direct_child=False, show_state=False):
        """Prints a tree representation with accurate direct child highlighting."""
        string_rep = (
            "\n"
            + " " * indent
            + f"{('(Direct) ' if is_direct_child else '') + self.name}:\n"
        )

        if show_state:
            string_rep += "  " * indent + f"  Last State: {self.last_state}\n"


        if self.has_children():

            string_rep += "  " * indent + "│\n"
            for child in self.get_children() :
                direct = False
                if child in self.direct_children:
                    direct = True
                string_rep += child.pretty_print(indent + 2, direct, show_state)
        else:
            string_rep += "  " * indent + "└── (No children)\n"

        return string_rep


@pyscript_compile
def load_yaml(path):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data


class EventManager:
    def __init__(self, rules_file, area_tree):
        self.rules = load_yaml(rules_file)
        self.area_tree=area_tree

    def create_event(self, event):
        log.info(f"New event: {event}")

        result=self.check_event(event)

    def check_event(self, event):
        log.info(f"checking event {event}")

        matching_rules = []
        for rule_name in self.rules.keys():
            log.info(f"rule name: {rule_name}")
            if event["device_name"].startswith(rule_name):
                matching_rules.append(rule_name)

        log.info(f"matching rules: {matching_rules}")

        


        for rule_name in matching_rules:
            rule = self.rules[rule_name]
            return self.execute_rule(event, rule)

        return False  # No matching rule

    def check_device(self, device, rule):
        log.info(f"checking device {device}")

        if not self._check_tags(event_tags, rule):
            return False


        functions = rule.get("functions", [])
        if len(functions) > 0:
            if not self._check_functions(functions, event_data, 1, rule):
                return False



    def execute_rule(self, event_data, rule):
        log.info(f"executing rule {rule} with event {event_data}")

        self.get_relevent_devices( event_data, rule)
        return True

    def get_relevent_devices(self, event_data, rule):
        # Get area input device is in
        device_name=event_data["device_name"]
        device_area=self.area_tree.get_device_area(device_name)

        log.info(f"device_area: {device_area}")

        # get areas in scope of device_area
        scope=rule.get("scope",[])[0]
        log.info(f"scope: {scope}")
        
        function_name = "get_"+str(list(scope.keys())[0])
        args = scope.get(function_name, [])
        log.info(f"checking function {function_name} with args {args}")

        # checks if function exists
        if hasattr(self.area_tree, function_name):
            func = getattr(self.area_tree, function_name)
        else:
            log.warning(f"Function '{function_name}' not implemented.")
            return None

        res=func(device_area.name, **args)
        log.info(f"res: {res}")


    def _check_tags(self, tags, rule):
        """This checks tags"""
        required_tags = rule.get("required_tags", [])
        prohibited_tags = rule.get("prohibited_tags", [])

        for tag in required_tags:
            if tag not in tags:
                return False

        for tag in prohibited_tags:
            if tag in tags:
                return False

        return True

    def _check_functions(self, functions, event_data, area_state, rule):
        for function_data in functions:
            # split dict key and value to get functoin name and args
            function_name = list(function_data.keys())[0]
            args = function_data.get(function_name, [])

            log.info(f"checking function {function_name} with args {args}")

            if function_name in globals().keys():
                func = globals()[function_name]
                if not func(event_data, area_state, **args):
                    return False
                else :
                    log.info(f"{function_name} passed!")
            else:
                log.info(f"Function '{function_name}' not implemented.")
                return True

        return True


class AreaTree:
    """Acts as an interface to the area tree"""

    def __init__(self, config_path):
        self.config_path = config_path
        self.area_tree = self._create_area_tree(self.config_path)

        self.root_name = self._find_root()

    def get_state(self, area=None):
        if area is None:
            area = self.root_name
        return self.area_tree[area].get_state()

    def get_area(self, area_name=None):
        if area_name is None:
            area_name = self.root_name
        return self.area_tree[area_name]

    def get_area_tree(self):
        return self.area_tree

    def _find_root(self):
        root_area = None
        for name, area in self.area_tree.items():
            if area.parent is None:
                root_area = name
                break
        return root_area

    def get_greatest_area(self, area_name):
        # Gets the highest area which still has the input area as a direct child
        if area_name not in self.area_tree:
            log.warning(f"Area {area_name} not found in area tree")
            return None

        starting_area = self.area_tree[area_name]

        highest_area = starting_area
        parent = starting_area.get_parent()

        while parent is not None:
            if highest_area in parent.direct_children:

                highest_area = parent
                parent = parent.get_parent()
            else:
                return highest_area

        return self.get_area() #return root if runs out of parents


    def get_lowest_children(self, area_name, include_devices=False) :
        area=self.get_area(area_name)

        lowest_areas=[]

        def traverse(area):
            if len(area.get_children(exclude_devices=(not include_devices)))==0:
                lowest_areas.append(area)
            else:
                for child in area.get_children(exclude_devices=True):
                    traverse(child)

        traverse(area)
        return lowest_areas

    def get_greater_siblings(self, area_name, **args):
        area=self.get_area(area_name)
        greatest_parent=self.get_greatest_area(area_name)
        siblings=greatest_parent.get_direct_children()
        if area in siblings:
            siblings.remove(area)
        return siblings


    def get_lesser_siblings(self, area_name):
        area=self.get_area(area_name)
        greatest_parent=self.get_greatest_area(area_name)
        siblings=self.get_lowest_children(greatest_parent.name)
        if area in siblings:
            siblings.remove(area)
        return siblings

    def get_device_area(self, device):
        for area_name, area in self.area_tree.items():
            log.info(f"Checking device {device} in area {area_name}")
            if device in area.get_devices():
                return area_name
        return None

    def _create_area_tree(self, yaml_file):
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

                # Create direct child relationships
                if "direct_sub_areas" in area_data and area_data["direct_sub_areas"] is not None:
                    for direct_child in area_data["direct_sub_areas"]:
                        child = create_area(direct_child)
                        child.add_parent(area)
                        area.add_child(child, direct=True)

                # Create child relationships
                if "sub_areas" in area_data and area_data["sub_areas"] is not None:
                    for child in area_data["sub_areas"]:
                        if child is not None:
                            new_area = create_area(child)
                            new_area.add_parent(area)
                            area.add_child(new_area, direct=False)

                # Add outputs as children
                if "outputs" in area_data:
                    for output in area_data["outputs"]:
                        if output is not None:
                            if "kauf" in output:
                                new_light = KaufLight(output)
                                new_device = Device(new_light)

                                area.add_device(new_device)
                                area_tree[output] = area
                #TODO: inputs

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
        return state

    def set_state(self, state):
        if "status" not in state.keys():
            log.info(f"{self.name}: State does not contain status {state}. Caching")

            self.cached_state = state

        else:
            for key, val in self.cached_state.items():
                if key not in state.keys():

                    state[key] = val

            self.driver.set_state(state)
            self.last_state = state

    def get(self, value):
        return self.last_state[value]

    def pretty_print(self, indent=1, is_direct_child=False, show_state=False):

        string_rep = (
            " " * indent + f"{('(Direct) ' if is_direct_child else '') + self.name}:\n"
        )

        if show_state:
            string_rep += " " * (indent + 2) + f"State: {self.get_state}\n"

        return string_rep


class KaufLight:
    """Light driver for kauf bulbs"""

    def __init__(self, name):
        self.name = name
        self.last_state = None
        self.color = None
        self.brightness = None
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
        try:
            color = state.get(f"light.{self.name}.rgb_color")
        except:
            log.warning(f"Unable to get rgb_color from {self.name}")
            return None

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

        if self.is_on():  # brightness reports as 0 when off
            self.brightness = brightness

        return brightness

    def set_temperature(self, temperature, apply=False):
        self.temperature = temperature
        self.apply_values(color_temp=self.temperature)

    def get_temperature(self):
        try:
            temperature = state.get(f"light.{self.name}.color_temp")
        except:
            log.warning(f"Unable to get color_temp from {self.name}")
            return None
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

        if state["status"]:  # if status is on, get current brightness
            brightness = self.get_brightness()
            if brightness is not None:
                state["brightness"] = brightness
        else:
            if self.brightness is not None:
                state["brightness"] = self.brightness

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

    log.info("\nPYSCRIPT: Starting")
    area_tree = AreaTree("./pyscript/layout.yml")

    event_manager = EventManager("./pyscript/rules.yml", area_tree)


    log.info("\nPYSCRIPT: ####Created#####\n\n")
    log.info(f"\narea tree {area_tree}\n\n")

    living_room = area_tree.get_area("living_room")
    log.info(f"\nlivingroom {living_room.pretty_print()}\n\n")

    event={"device_name": "motion_sensor_dining_room", "trigger": "on", "tags": []}
    event_manager.create_event(event)