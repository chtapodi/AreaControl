import yaml
from collections import defaultdict


STATE_VALUES={
    "input": {
        "status" : 0,
        "baud_duration" : 0,
        "elapsed_time" : 0,
    },
    "output": {
        "status" : 0,
        "rgb" : [0,0,0],
        "brightness" : 0,
        "temperature" : 0
    }
}


class Area:
    def __init__(self, name):
        self.name=name
        self.children=[]
        self.direct_children=[]
        self.parent=None

    def add_parent(self,parent) :
        self.parent=parent

    def add_child(self, child, direct=False) :
        self.children.append(child)
        if direct :
            self.direct_children.append(child)


    def set_state(self,state) :
        for child in self.children :
            child.set_state(state)


@pyscript_compile
def load_yaml(path) :
    with open(path, 'r') as f:
        data = yaml.safe_load(f)
    return data


def create_area_tree(yaml_file):
    """
    Loads areas from a YAML file and creates a hierarchical structure of Area objects.

    Args:
        yaml_file: Path to the YAML file containing area definitions.

    Returns:
        A dictionary mapping area names to their corresponding Area objects.
    """

    data=load_yaml(yaml_file)

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
        area = create_area(area_name)

        # Create child and direct child relationships
        for child_type in ["sub_areas", "direct_sub_areas"]:
            if child_type in area_data:
                for child_name in area_data[child_type]:
                    child_area = create_area(child_name)
                    child_area.add_parent(area)
                    direct=child_type == "sub_areas"
                    area.add_child(child_area, direct=direct)
        
        # Add outputs as children
        if "outputs" in area_data:
            for output in area_data["outputs"]:
                if output is not None:
                    if "kauf" in output:
                        new_light=KaufLight(output)
                        new_device=Device(new_light)
                        area.add_child(new_device, direct=True)

                

    return area_tree


def visualize_areas(areas):
    """
    Prints a visual representation of the area hierarchy.

    Args:
        areas: A dictionary of Area objects.
    """

    def print_tree(area, indent=0):
        if area.name is not None :
            print("PYSCRIPT: " * indent + area.name)
            for child in area.children:
                print_tree(child, indent + 2)

    # Find the root area (no parent)
    root_area = None
    for area in areas.values():
        if area.parent is None:
            root_area = area
            break  # Exit the loop once the root area is found

    # Print the tree structure
    print("PYSCRIPT:Area Hierarchy:")
    print_tree(root_area)



class Device:
    """Acts as a wrapper/driver for a device type -- interfaces between states and devices."""

    def __init__(self, driver):
        self.driver = driver
        log.warning(f"\nPYSCRIPT: trying")

        self.name = driver.name
        log.warning(f"\nPYSCRIPT: {self.name=}")

        self.last_state=None

    def get_state(self):
        state=self.driver.get_state()
        self.last_state=state
        return state

    def set_state(self, state):
        self.driver.set_state(state)
        self.last_state=state

    def get(self,value) :
        return self.last_state[value]

class KaufLight:
    """Light driver for kauf bulbs"""

    def __init__(self, name):
        self.name = name
        self.last_state = None


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

    def is_on(self) :
        status=self.get_status()
        if status is None or "off" in status or "unknown" in status:
            return False
        return True


    # RGB (color)
    def set_rgb(self, color, apply=False):
        self.color = color
        if (apply or self.is_on()):
            self.apply_values(rgb_color=self.color)

    def get_rgb(self):
        color = state.get(f"light.{self.name}.rgb_color")

        return color

    # Brightness
    def set_brightness(self, brightness, apply=False):
        self.apply_values(brightness=str(brightness))

    def get_brightness(self):
        alpha = 0
        try:
            alpha = state.get(f"light.{self.name}.brightness")
        except:
            pass
        if alpha is None:
            alpha = 0
        self.brightness = alpha

        return alpha

    def set_state(self, state) :
        """Attempts to set all of the values at the same time instead of rgb, brightness, etc..."""
        self.apply_values(**state)

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
def test_classes() :
    log.warning("\nPYSCRIPT: Starting")
    area_tree = create_area_tree("./pyscript/layout.yml")
    log.warning("\nPYSCRIPT: Created")

    living_room=area_tree["living_room"]
    log.warning(f"\nPYSCRIPT: living_room {living_room}")
    living_room.set_state({"brightness":255})



