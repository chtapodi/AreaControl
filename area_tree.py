import yaml
from collections import defaultdict
import copy
import time
from pyscript.k_to_rgb import convert_K_to_RGB
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.util import color as color_util
from tracker import TrackManager, Track, Event
import unittest




STATE_VALUES = {
    "input": {
        "status": 0,
        "baud_duration": 0,
        "elapsed_time": 0,
    },
    "output": {"status": 0, "rgb": [0, 0, 0], "brightness": 0, "temperature": 0},
}


area_tree = None
event_manager = None
global_triggers = None
tracker_manager=None

verbose_mode = False

last_set_state={}

# Default heights for smart blinds (in the same units used when setting height).
# These values allow converting between physical height and percentage closed.
BLIND_HEIGHTS = {
    "blind_bedroom_window": 100,
}


@service
def reset():
    log.warning("RESETTING. MAKE SURE YOU WANT THIS")
    global area_tree
    global event_manager
    global global_triggers
    global verbose_mode
    area_tree = None
    event_manager = None
    global_triggers = None
    verbose_mode = False
    tracker_manager=None
    init()


@service
def init():
    global area_tree
    global event_manager
    global global_triggers
    global tracker_manager
    global_triggers = []
    area_tree = AreaTree("./pyscript/layout.yml")
    event_manager = EventManager("./pyscript/rules.yml", area_tree)
    tracker_manager = TrackManager()


def get_global_triggers():
    global global_triggers
    if global_triggers is None:
        init()
    return global_triggers


@service
def get_total_average_state(key=None):
    area_tree = get_area_tree()
    root = area_tree.get_root()
    state = summarize_state(root.get_state())
    if key is not None:
        if key in state:
            return state[key]
        else:
            return None
    return state


def get_event_manager():
    global event_manager
    if event_manager is None:
        init()
    return event_manager

def get_tracker_manager():
    global tracker_manager
    if tracker_manager is None:
        init()
    return tracker_manager


def get_area_tree():
    event_manager = get_event_manager()
    return event_manager.get_area_tree()


def get_verbose_mode():
    global verbose_mode
    return verbose_mode


def get_cached_last_set_state():
    global last_set_state
    if last_set_state is None:
        return None
    return copy.deepcopy(last_set_state)

def set_cached_last_set_state(device,state):
    global last_set_state
    log.info(f"set global last set state to {state}")
    if state is None:
        last_set_state = None
    else:
        last_set_state = copy.deepcopy(state)
    return True

@service
def create_event(**kwargs):
    log.info(f"Service creating event:  with kwargs {kwargs}")
    event = {}
    if "name" in kwargs.keys():
        event["device_name"] = kwargs["name"]

    elif "device_name" in kwargs.keys():
        event["device_name"] = kwargs["device_name"]

    if "device_name" in event.keys():
        if "tags" in kwargs.keys():
            event["tags"] = kwargs["tags"]

        if "state" in kwargs.keys():
            event["state"] = kwargs["state"]

        if "scope_functions" in kwargs.keys():
            event["scope_functions"] = kwargs["scope_functions"]

        if "state_functions" in kwargs.keys():
            event["state_functions"] = kwargs["state_functions"]

        event_manager = get_event_manager()
        log.info(f"Service creating event: {event}")
        event_manager.create_event(event)

    else:
        log.warning(f"No devic_name in serice created event {kwargs}")


@service
def freeze_area(area_name, recursive=True):
    """Freeze an area so its lights ignore future state changes."""
    area = get_area_tree().get_area(area_name)
    if area is None:
        log.warning(f"freeze_area: area {area_name} not found")
        return False
    area.freeze(propagate=recursive)
    return True


@service
def unfreeze_area(area_name, recursive=True):
    """Unfreeze a previously frozen area."""
    area = get_area_tree().get_area(area_name)
    if area is None:
        log.warning(f"unfreeze_area: area {area_name} not found")
        return False
    area.unfreeze(propagate=recursive)
    return True


def get_function_by_name(function_name, func_object=None):
    func = None
    if func_object is None:
        if function_name in globals().keys():
            func = globals()[function_name]
        else:
            log.warning(f"Function {function_name} not found")
    else:
        if hasattr(func_object, function_name):
            func = getattr(func_object, function_name)

    if func is None:
        log.warning(f"Function {function_name} not found")
    # else:
    # log.info(f"Function {function_name} found")
    return func


def combine_states(state_list, strategy="last"):
    """
    A function that combines a list of states using a specified strategy and returns the final combined state. 

    Args:
        state_list (list): A list of states to be combined.
        strategy (str, optional): The strategy to be used for combining the states. Defaults to "last".

        Strategies are :

        - "first_state" : Uses the first valid state in the list
        - "last" : The last state in the list
        - "first" : The first state in the list
        - "average" : Averages all of the states

    Returns:
        dict: The final combined state.
    """
    final_state = {}
    log.info(f"Combining states with strategy {strategy}: {state_list}")
    state_list=copy.deepcopy(state_list)

    if strategy=="first_state" : # Uses the first valid state in the list 
        # state_list.reverse()
        for state in state_list:
            if state is not None and len(state) > 0:
                log.info(f"Found first state: {state}")
                return state



    if strategy == "last" or strategy == "first":
        if strategy == "first": # Combine, first is least likely to be overwritten
            state_list.reverse()

        log.info(f"COMBINING states with strategy {strategy}: {state_list}")
        for state in state_list:
            if state is not None:
                final_state.update(state)  # Update overwrites previous value

    elif strategy == "average":
        sum_dict={}
        count_dict={}

        # This is to deal with the iterables within the dict and making sure they are all properly averaged. Its a pain. 
        # The first section sums up all of the values in the dict and keeps count, and the second half divides total by the count
        for state in state_list:
            if state is not None:
                for key, value in state.items():
                    if (isinstance(value, (tuple, list))
                            or value.__class__.__name__ == "TupleWrapper"
                        ):
                        if key not in sum_dict.keys():
                            sum_dict[key]=[]
                            count_dict[key]=[]
                            for i in range(len(value)):
                                sum_dict[key].append(0)
                                count_dict[key].append(0)

                        for i in range(len(value)):
                            sum_dict[key][i] += value[i]
                            count_dict[key][i] += 1

                    else:
                        if key not in sum_dict.keys():
                            sum_dict[key] = 0
                            count_dict[key] = 0

                        sum_dict[key] += value
                        count_dict[key] += 1

        log.info(f"SUMDICT {sum_dict} COUNTDICT {count_dict}")
        for key, value in sum_dict.items():
            # if iterable 
            
            if (isinstance(value, (tuple, list))
                            or value.__class__.__name__ == "TupleWrapper"
                        ):
                if key not in final_state.keys():
                    final_state[key]=[]
                    for i in range(len(value)):
                        final_state[key].append(0)
                for i in range(len(value)):
                    final_state[key][i] = value[i] / count_dict[key][i]
            
            elif count_dict[key] > 0:
                final_state[key] = value / count_dict[key]
        if "status" in final_state.keys() and final_state["status"] > 0:
            final_state["status"] = 1
        
        log.info(f"FINAL STATE {final_state}")

    else :
        log.warning(f"Strategy {strategy} not found")
    if get_verbose_mode():
        log.info(f"combined states {state_list} into {final_state}")
    return final_state


def summarize_state(state):
    flat_state = {}
    for key, value in state.items():
        if type(value) == dict:
            new_state = summarize_state(value)
            flat_state = combine_states([flat_state, new_state], strategy="average")
        else:
            flat_state[key] = value
    if get_verbose_mode():
        log.info(f"summarized state {state} as {flat_state}")
    return flat_state


def combine_colors(color_one, color_two, strategy="add"):
    color = [0, 0, 0]
    if strategy == "average":
        color[0] = (color_one[0] + color_two[0]) / 2
        color[1] = (color_one[1] + color_two[1]) / 2
        color[2] = (color_one[2] + color_two[2]) / 2
    elif strategy == "add":
        color[1] = color_one[1] + color_two[1]
        color[2] = color_one[2] + color_two[2]
        color[0] = color_one[0] + color_two[0]
    else:
        log.warning(f"Strategy {strategy} not found")

    for i in range(len(color)):
        val = color[i]
        if val > 255:
            color[i] = 255
        if val < 0:
            color[i] = 0
    if get_verbose_mode():
        log.info(f"combined: {color_one} + {color_two} = {color}")

    return color


## RULES ##
# These must have an interface that mathes the following and returns boolean


def check_sleep(
    event,
    area_state,
):
    is_theo_alseep = state.get("binary_sensor.xavier_is_sleeping")
    log.info(f"theo sleep {is_theo_alseep}")


def motion_sensor_mode(*args, **kwargs):
    log.info(f"motion_sensor_mode {input_boolean.motion_sensor_mode}")
    return input_boolean.motion_sensor_mode == "on"

def set_motion_sensor_mode(state):
    log.info(f"set_motion_sensor_mode {input_boolean.motion_sensor_mode}")
    input_boolean.motion_sensor_mode = state
    log.info(f"set_motion_sensor_mode is now {input_boolean.motion_sensor_mode}")



### Scope functions
def get_entire_scope(device, device_area, *args):
    return [get_area_tree().get_root()]


# get immediate scope
# make it so they filter by all checking
def get_immediate_scope(device, device_area, *args): ...


def get_local_scope(device, device_area, *args):
    greatest_parent = get_area_tree().get_greatest_area(device_area.name)
    return [greatest_parent]


# When area names are passed in as args, gets their local scopes
def get_area_local_scope(device, device_area, *args):
    log.info(f"get_area_local_scope {args}")
    areas = []
    for area_name in args[0]:
        area_tree = get_area_tree()
        if area_tree.is_area(area_name):
            areas.append(area_tree.get_area(area_name))
        else:
            log.info(f"Area {area_name} not found")
    log.info(f"get_area_local_scope {areas[0].name}")
    return areas


### State functions
# Functions that return a state based on some value
def get_time_based_state(device, scope, *args):
    """
    Determines and returns a time-based state for devices within a given scope.

    This function calculates the desired state for devices based on the current
    hour of the day. The state includes attributes like brightness, RGB color,
    and color temperature. The state is intended to reflect common lighting
    preferences for different times of the day, such as early morning, midday,
    evening, etc.

    Args:
        device: The device for which the state is being determined.
        scope: A list of areas containing devices whose states are to be
               considered.
        *args: Additional arguments that may be required by the function.

    Returns:
        dict: A dictionary representing the desired state, including keys for:
              - "status": Integer, represents the on/off state (1 for on).
              - "brightness": Integer (optional), represents the brightness level.
              - "rgb_color": List of integers (optional), represents the RGB color.
              - "color_temp": Integer (optional), represents the color temperature.
    """
    now = time.localtime().tm_hour
    states = {}
    for area in scope:
        states[area.name] = area.get_state()
    scope_state = summarize_state(states)

    step_increment = 20

    state = {}

    state["status"] = 1  # want to turn on for all of them

    # using now, have if statements for times of day: early morning, morning, midday, afternoon, evening, night, late night

    if now > 0 and now < 5:
        log.info("it is late_night")

        state["brightness"] = 50
        state["rgb_color"] = [255, 0, 0]

    elif now >= 5 and now < 7:
        log.info("it is dawn")
        state["rgb_color"] = [255, 0, 0]

    elif now >= 7 and now < 8:
        log.info("it is early morning")
        state["brightness"] = 255

        goal_color = [255, 200, 185]
        if "rgb_color" in scope_state:
            state["rgb_color"] = combine_colors(
                scope_state["rgb_color"], goal_color, strategy="average"
            )  # scope_state["rgb_color"]
        else:
            state["rgb_color"] = goal_color

    elif now >= 8 and now < 11:
        log.info("it is morning")
        state["brightness"] = 255
        state["color_temp"] = 350

    elif now >= 11 and now < 14:  # 11-2
        log.info("it is midday")
        state["brightness"] = 255
        state["color_temp"] = 350

    elif now >= 14 and now < 18:  # 2-6
        log.info("it is afternoon")
        state["brightness"] = 255
        state["color_temp"] = 350


    elif now >= 18 and now < 20:  # 6-8
        log.info("it is evening")
        goal_color = [255, 200, 185]
        if "rgb_color" in scope_state:
            log.info(f"combining {scope_state['rgb_color']} with {goal_color}")
            state["rgb_color"] = combine_colors(
                scope_state["rgb_color"], goal_color, strategy="average"
            )  # scope_state["rgb_color"]
        else:
            log.info("just setting the color")
            state["rgb_color"] = goal_color

    elif now >= 20 and now < 22:  # 8-10
        log.info("it is late evening")

        goal_color = [255, 172, 89]
        if "rgb_color" in scope_state:
            state["rgb_color"] = combine_colors(
                scope_state["rgb_color"], goal_color, strategy="average"
            )  # scope_state["rgb_color"]
        else:
            state["rgb_color"] = goal_color

    elif now >= 22:  # 10-11
        log.info("it is night")

        if "rgb_color" in scope_state:
            log.info("Light is off, darkening color")
            redder_state = combine_colors(
                scope_state["rgb_color"],
                [+step_increment, -step_increment, -step_increment],
                "add",
            )
            state["rgb_color"] = redder_state
        else:
            state["rgb_color"] = [255, 80, 0]

    elif now >= 23:  # 23-0
        if scope_state["status"] == 0:
            log.info("it is late-ish_night")
            state["rgb_color"] = [255, 0, 0]
        else:
            if "brightness" in scope_state:
                current_brightness = scope_state["brightness"]
                if current_brightness > 50:
                    state["brightness"] = current_brightness - 5
            else:
                state["brightness"] = 50

    if "status" in scope_state:
        if scope_state["status"]:
            # if the light is on, don't apply rgb_color or temp
            if "rgb_color" in state:
                del state["rgb_color"]

            if "color_temp" in state:
                del state["color_temp"]
    else:
        log.warning("Status is not in scope_state")

    log.info(f"Time based state is {state}")
    return state

# Gets the most recent state that was manually set
def get_last_set_state(device, scope, *args):
    return get_cached_last_set_state()

def get_last_track_state(device, scope, *args):
    tracker_manager=get_tracker_manager()
    area_tree=get_area_tree()
    device_area = device.get_area().name

    log.info(f"get_last_track_state(): looking for {device_area} in {tracker_manager.get_pretty_string()}")

    for track in tracker_manager.tracks:
        if track.get_area() == device_area:
            previous_event=track.get_previous_event(1) # Get the event before the current one
            if previous_event is not None:
                previous_area=previous_event.get_area()
                last_track_state=summarize_state(area_tree.get_state(previous_area))
                if "name" in last_track_state:
                    del last_track_state["name"] 
                log.info(f"get_last_track_state(): Last track state is {last_track_state} from {previous_area}")
                return last_track_state
    return None



def toggle_status(device, scope, *args):
    states = {}
    for area in scope:
        states[area.name] = area.get_state()
        log.info(f"Area {area.name} state is {states[area.name]}")
    scope_state = summarize_state(states)
    log.info(f"Toggling status is {scope_state}")
    if "status" in scope_state:
        if scope_state["status"]:  # if on
            return {"status": 0}  # turn off
        else:
            return {"status": 1}  # turn on


def toggle_state(device, scope, *args):
    goal_state = {"status": 1, "color_temp": 350}
    opposite_state = {"status": 1, "rgb_color": [255, 149, 51]}

    def does_state_match_goal(state):
        return get_state_similarity(state, goal_state) >= 0.5

    states = {}
    for area in scope:
        states[area.name] = area.get_state()
        log.info(f"toggle_state: Area {area.name} state is {states[area.name]}")
    scope_state = summarize_state(states)

    log.info("toggle_state: Does scope_state match goal?")
    if does_state_match_goal(scope_state):
        log.info(f"toggle_state: Already in goal state, toggling to last scope state")

        last_states = {}
        for area in scope:
            last_states[area.name] = area.get_last_state()
        last_scope_state = summarize_state(last_states)
        last_scope_state["status"]=1
        log.info(f"toggle_state: Last state is {last_scope_state}")

        log.info("toggle_state: Does last_scope_state match goal?")
        if does_state_match_goal(last_scope_state):
            log.info(f"toggle_state: last scope state matches goal state, applying opposite state")
            return opposite_state

        # TODO: Theres gotta be a better way
        if "temperature" in last_scope_state:
            del last_scope_state["temperature"]

        if "temp_color" in last_scope_state:
            del last_scope_state["temp_color"]

        if "name" in last_scope_state:
            del last_scope_state["name"]

        if "device_name" in last_scope_state:
            del last_scope_state["device_name"]

        return last_scope_state

    else:
        log.info(f"toggle_state: scope_state does not match goal, toggling to {goal_state}")
        return goal_state

    return scope_state


###


def generate_state_trigger(trigger, functions, kwarg_list):
    log.info(f"generating state trigger @{trigger} {functions}( {kwarg_list} )")

    @service
    @state_trigger(trigger)
    def func_trig(**kwargs):
        log.info(f"TRIGGER: state trigger @{trigger} {functions}( {kwarg_list} )")
        # This assumes that if the functions are lists the kwargs are as well.
        if isinstance(functions, list):
            for function, kwargs in zip(functions, kwarg_list):
                function(**kwargs)
        else:
            functions(**kwarg_list)

    func_trig.__name__ = "state_trigger_" + trigger

    get_global_triggers().append(["trigger", trigger, func_trig])
    return func_trig


def merge_data(data):
    """
    Merge the given data into a single value.

    Args:
        data (list): A list of elements to be merged.

    Returns:
        The merged value of the given data.

    Raises:
        ValueError: If the provided data is empty or not all elements are of the same type.
        ValueError: If the data type is not supported.

    Notes:
        - The function supports merging integers and floats by taking the average.
        - The function supports merging lists by recursively merging items at corresponding indices.
        - The function supports merging dictionaries by recursively merging values for corresponding keys.

    """
    if not data:
        raise ValueError("merge_data(): Empty data provided")


    def is_similar(item1, item2):
        if issubclass(data_type, (list,tuple)) and issubclass(type(item), (list,tuple)) :
            return True
        if issubclass(data_type, (int,float)) and issubclass(type(item), (int,float)) :
            return True
        return False

    data_type = type(data[0])
    for item in data[1:]:
        if not issubclass(type(item), data_type) and not is_similar(item, data[0]):
            log.error(f"merge_data(): Not all elements are of the same type {data}")
            return None

    # Handle integers and floats by averaging
    if issubclass(data_type, (int, float)):
        return sum(data) / len(data)

    # Handle lists
    elif issubclass(data_type, (list, tuple)) :
        max_length=len(data[0])
        for item in data:
            max_length=max(len(item),max_length)

        result = []
        for i in range(max_length):
            items_at_index = []
            for item in data:
                if len(item) > i:
                    items_at_index.append(item[i])
            # Recursively merge items at current index
            merged_item = merge_data(items_at_index)
            result.append(merged_item)
        return result

    # Handle dictionaries
    elif issubclass(data_type, dict):
        result = {}
        all_keys = set()
        for d in data:
            for key in d.keys():
                all_keys.add(key)
        for key in all_keys:
            values = []
            for d in data:
                if key in d:
                    values.append(d[key])
            # Recursively merge values for the current key
            merged_value = merge_data(values)
            result[key] = merged_value
        return result

    else:
        raise ValueError(f"merge_data(): Unsupported data type {data_type}: {data}")



def merge_states(state_list, name=None):
    for state in state_list :
        if "name" in state.keys(): del state["name"]
    merged_state=merge_data(state_list)
    if "status" in merged_state and merged_state["status"]>0:
        merged_state["status"]=1 
    else:
        merged_state["status"]=0
    log.info(f"merged_state: {merged_state}")
    return merged_state

def get_state_similarity(state1, state2):

    state1=copy.deepcopy(state1)
    if "name" in state1.keys(): del state1["name"]
    state2=copy.deepcopy(state2)
    if "name" in state2.keys(): del state2["name"]

    unique_to_state1 = set(state1.keys()) - set(state2.keys())

    # Find keys unique to state2
    unique_to_state2 = set(state2.keys()) - set(state1.keys())

    unique_keys = unique_to_state1.union(unique_to_state2)
    if "status" in unique_keys: unique_keys.remove("status") # If only one state has status, it probably doesn't matter in the comparison

    # Get number of shared keys
    shared_keys = set(state1.keys()).intersection(set(state2.keys()))
    num_shared=len(shared_keys)

    matching_vals=0
    for key in shared_keys:
        if  type(state2[key]) != type(state2[key]):
            log.info(f"State keys '{key}' have mismatched types: {state1[key]} vs {state2[key]}")
            num_shared-=1

        if type(state1[key]) == dict:
            matching_vals+=get_state_similarity(state1[key], state2[key])

        elif type(state1[key]) == list:
            for i in range(len(state1[key])):
                if state1[key][i] == state2[key][i]:
                    matching_vals+=1
                    num_shared+=1  # Add one to num shared because each item in list is unique
        elif state1[key] == state2[key]:
            matching_vals+=1

    similarity = matching_vals / (num_shared+len(unique_keys))
    return similarity

# Color helpers


def rgb_to_hsl(r, g, b):
    """Convert RGB to HSL using Home Assistant helpers."""
    h, s = color_util.color_RGB_to_hs(r, g, b)
    # Home Assistant does not provide luminance; assume 50 for consistency.
    l = 50
    return h, s, l


def hs_to_rgb(h, s):
    """Convert HS color to RGB using Home Assistant helpers."""
    r, g, b = color_util.color_hs_to_RGB(h, s)
    return [r, g, b]


def k_to_rgb(k):
    """Convert a kelvin temperature into an RGB color tuple."""
    r, g, b = color_util.color_temperature_to_rgb(k)
    return [r, g, b]


class Area:
    def __init__(self, name):
        self.name = name
        self.children = []
        self.direct_children = []
        self.devices = []
        self.parent = None
        self.frozen = False

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
        return list(set(self.direct_children))

    def get_parent(self):
        return self.parent

    def has_children(self, exclude_devices=False):
        return len(self.get_children(exclude_devices)) > 0

    def freeze(self, propagate=True):
        """Freeze this area so state changes are ignored."""
        self.frozen = True
        for child in self.get_children(exclude_devices=False):
            if isinstance(child, Area) and propagate:
                child.freeze(propagate=True)
            elif isinstance(child, Device):
                child.lock(True)

    def unfreeze(self, propagate=True):
        """Unfreeze this area allowing state changes again."""
        self.frozen = False
        for child in self.get_children(exclude_devices=False):
            if isinstance(child, Area) and propagate:
                child.unfreeze(propagate=True)
            elif isinstance(child, Device):
                child.lock(False)

    def is_frozen(self):
        return self.frozen

    def set_state(self, state):
        if self.frozen:
            log.info(f"Area {self.name} is frozen; skipping state change {state}")
            return
        for child in self.get_children():
            child.set_state(copy.deepcopy(state))

    def get_state(self):
        log.info(f"Area:get_state(): Getting state for {self.get_pretty_string()}")
        child_states = []

        for child in self.get_children():
            child_state = child.get_state()
            log.info(f"Area:get_state(): Child state: {child_state}")
            child_states.append(child_state)
        log.info(f"merging states: {child_states}")
        merged = merge_states(child_states, self.name)

        return merged

    def get_last_state(self):
        child_states = []

        for child in self.get_children():
            child_state = child.get_last_state()
            child_states.append(child_state)

        merged = merge_states(child_states, self.name)

        return merged

    def get_pretty_string(self, indent=1, is_direct_child=False, show_state=False):
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
            for child in self.get_children():
                direct = False
                if child in self.direct_children:
                    direct = True
                string_rep += child.get_pretty_string(indent + 2, direct, show_state)
        else:
            string_rep += "  " * indent + "└── (No children)\n"

        return string_rep


@pyscript_compile
def load_yaml(path):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data


### Tracker interface
def update_tracker(device, *args):
    tracker_manager=get_tracker_manager()

    tracker_manager.add_event(device.get_area().name)

    log.info(f"update_tracker: Current tracks")
    for track in tracker_manager.tracks:
        log.info(f"update_tracker: {track.get_pretty_string()}")

    return True



class EventManager:
    def __init__(self, rules_file, area_tree):
        self.rules = load_yaml(rules_file)
        self.area_tree = area_tree

    def create_event(self, event):
        log.info(f"EventManager: New event: {event}")

        result = self.check_event(event)

    def check_event(self, event):
        matching_rules = []
        rule_lookup = self.get_rules()
        for rule_name in rule_lookup.keys():
            # Get devices that names match trigger_prefix
            trigger_prefix = rule_lookup[rule_name]["trigger_prefix"]
            if event["device_name"].startswith(trigger_prefix):
                if "service" in event["device_name"]:
                    log.info(f"EventManager:check_event(): SERVICESEARCH")
                if get_verbose_mode():
                    log.info(
                        f"EventManager:check_event(): Rule {rule_name} prefix [{trigger_prefix}] matches {event['device_name']}"
                    )
                function_override = False
                tag_override = False
                if "tags" in event:
                    if "tag_override" in event["tags"]:
                        tag_override = True
                    if "function_override" in event["tags"]:
                        function_override = True

                approved = True
                if not (
                    tag_override or self._check_tags(event, rule_lookup[rule_name])
                ):
                    approved = False

                if get_verbose_mode() and approved:
                    log.info(f"EventManager:check_event(): {rule_name} Passed tag check")

                if "tags" in event:
                    if "tag_override" in event["tags"]:
                        tag_override = True

                if not approved or (
                    function_override
                    and self._check_functions(event, rule_lookup[rule_name])
                ):
                    approved = False
                    # log.info(f"EventManager:check_event(): {rule_name} FAILED function check")

                if get_verbose_mode() and approved:
                    log.info(f"EventManager:check_event(): {rule_name} Passed function check")

                if approved:
                    matching_rules.append(rule_name)

        event_tags = event.get("tags", [])
        log.info(f"EventManager:check_event():  Event: {event} Matches:{matching_rules} Rules")

        results = []
        for rule_name in matching_rules:
            rule = copy.deepcopy(self.rules[rule_name])
            log.info(f"EventManager:check_event():  Rule: {rule}")
            results.append(self.execute_rule(event, rule))

        if results is not None:
            return results

        return False  # No matching rule

    # Looks for keywords in args and replaces them with values
    def expand_args(self, args, event_data, state):
        for arg in args :
            if type(arg) is str:
                if arg.startswith("$") :
                    if arg == "$state" :
                        log.info(f"Expanding $state to {state}")
                        del args[args.index("$state")]
                        args.append(state)
        return args

    def execute_rule(self, event_data, rule):
        device_name = event_data["device_name"]

        log.info(f"EventManager:execute_rule(): {event_data}")
        device = self.get_area_tree().get_device(device_name)



        if device is not None:
            # get values
            device_area = device.get_area()
            rule_state = rule.get("state", {})

            log.info(f"EventManager:execute_rule(): updating {rule} with {event_data}")
            rule.update(event_data)

            scope = None  # Should these be anded?
            # Get scope to apply to
            if "scope_functions" in rule:
                for function_pair in rule["scope_functions"]:  # function_name:args
                    for function_name, args in function_pair.items():
                        function = get_function_by_name(function_name)
                        # If function exists, run it
                        if function is not None:
                            new_scope = function(device, device_area, args)
                            if new_scope is not None:
                                if scope is None:  # if no scope to compare with, set
                                    scope = new_scope
                                else:
                                    edited_scope = []
                                    for area in scope:
                                        if get_verbose_mode():
                                            log.info(
                                                f"EventManager:execute_rule(): Checking if {area.name} in {new_scope}"
                                            )
                                        if area in new_scope:
                                            edited_scope.append(area)
                                    log.info(f"EventManager:execute_rule(): Edited scope: {scope}->{edited_scope}")
                                    scope = edited_scope

            if scope is None:
                scope = get_local_scope(device, device_area)

            scope_names=[]
            for area in scope:
                scope_names.append(area.name)
            
            log.info(f"EventManager:execute_rule(): Event scope is {scope_names}")

            function_states = []
            # if there are state functions, run them
            if "state_functions" in rule:
                log.info(f"EventManager:execute_rule(): State functions: {rule['state_functions']}")
                for function_pair in rule["state_functions"]:  # function_name:args
                    for function_name, args in function_pair.items():
                        function = get_function_by_name(function_name)
                        # If function exists, run it
                        if function is not None:
                            function_state = function(device, scope, args)
                            # Adds the states to a list to be combined
                            log.info(f"EventManager:execute_rule(): Function {function_name} provided: {function_state}")
                            function_states.append(function_state)

                log.info(f"EventManager:execute_rule(): Function states: {rule['state_functions']} provided  {function_states}")
            # Add state_list to event_state
            state_list = []
            if "state" in event_data:
                #Add manual state list to state options. TODO: Should this get priority?
                state_list.append(event_data["state"])

            state_list.extend(function_states)
            state_list.append(rule_state) #TODO: Also rethink the priority of this.

            strategy="average"
            if "combination_strategy" in rule:
                strategy = rule["combination_strategy"]
            final_state = combine_states(
                state_list, strategy=strategy
            )

            log.info(f"EventManager:execute_rule(): Event state is {final_state}")



            #For now, assuming functions are boolean, if fail, ignore rule.
            # This is down here so we have full states for expanding args
            if "functions" in rule:
                for function_pair in rule["functions"]:  # function_name:args
                    for function_name, args in function_pair.items():
                        function = get_function_by_name(function_name)
                        
                        # If function exists, run it
                        if function is not None:
                            args=self.expand_args(args, event_data, final_state)
                            if not function(device, *args) :
                                log.info(f"Fuction '{function_name}' failed, not running rule.")
                                return False
            log.info("EventManager:execute_rule(): Event passed all functions")
            log.info(f"EventManager:execute_rule(): Applying {final_state} to {scope_names}")
            for areas in scope:
                areas.set_state(final_state)

            return True
        else:
            log.warning(f"EventManager:execute_rule(): Device {device_name} not found")
            return False

    def _check_tags(self, event, rule):
        """Checks if the tags passed the rules tags"""
        tags = event.get("tags", [])
        if "required_tags" in rule:
            if get_verbose_mode():
                log.info(
                    f"Checking Required tags {rule['required_tags']} against {tags}"
                )
            for tag in rule["required_tags"]:
                if tag not in tags:
                    if get_verbose_mode():
                        log.info(f"Required tag {tag} not found in event {event}")
                    return False
        if "prohibited_tags" in rule:
            if get_verbose_mode():
                log.info(
                    f"Checking Prohibited tags {rule['prohibited_tags']} against {tags}"
                )
            for tag in rule["prohibited_tags"]:
                if tag in tags:
                    if get_verbose_mode():
                        log.info(f"Prohibited tag {tag} found in event {event}")
                    return False
        if get_verbose_mode():
            log.info(f"Passed tag check")
        return True

    def _check_functions(self, event, rule, **kwargs):
        functions = rule.get("functions", [])
        if len(functions) > 0:
            for function_data in functions:
                # split dict key and value to get functoin name and args
                function_name = list(function_data.keys())[0]

                function = get_function_by_name(function_name)
                if function is not None:
                    result = function(event, **kwargs)
                    if not result:
                        if get_verbose_mode():
                            log.info(f"Function {function_name} failed")
                        return False

        return True  # If passed all checks or theres no functions to pass

    def get_area_tree(self):
        return self.area_tree

    def get_rules(self):
        return copy.deepcopy(self.rules)


class AreaTree:
    """Acts as an interface to the area tree"""

    def __init__(self, config_path):
        self.config_path = config_path
        self.area_tree_lookup = self._create_area_tree(self.config_path)

        self.root_name = self._find_root_area_name()

    def get_state(self, area=None):
        if area is None:
            area = self.root_name

        state=self.area_tree_lookup[area].get_state()
        log.info(f"AreaTree:get_state(): State for {area} is {state}")
        return state

    def get_root(self):
        return self.get_area(self.root_name)

    def get_area(self, area_name=None):
        if area_name is None:
            area_name = self.root_name
        if area_name not in self.area_tree_lookup:
            log.warning(f"Area {area_name} not found in area tree")
            return None
        return self.area_tree_lookup[area_name]

    def get_device(self, device_name):
        if device_name not in self.area_tree_lookup:
            if "service_" in device_name:
                return self.area_tree_lookup["service_input"]
            log.warning(f"Device {device_name} not found in area tree")
            return None
        return self.area_tree_lookup[device_name]

    def get_area_tree_lookup(self):
        return self.area_tree_lookup

    def is_area(self, area_name):
        log.info(f"Checking if {area_name} is an area")
        if area_name in self.get_area_tree_lookup():
            return True
        return False

    def _find_root_area_name(self):
        root_area = None
        for name, area in self.area_tree_lookup.items():
            if area.parent is None:
                root_area = name
                break
        return root_area

    def get_greatest_area(self, area_name):
        # Gets the highest area which still has the input area as a direct child
        if area_name not in self.area_tree_lookup:
            log.warning(f"Area {area_name} not found in area tree")
            return None

        starting_area = self.area_tree_lookup[area_name]

        highest_area = starting_area
        parent = starting_area.get_parent()

        while parent is not None:
            if highest_area in parent.direct_children:
                highest_area = parent
                parent = parent.get_parent()
            else:
                return highest_area

        return self.get_area()  # return root if runs out of parents

    def get_lowest_children(self, area_name, include_devices=False):
        area = self.get_area(area_name)

        lowest_areas = []

        def traverse(area):
            if len(area.get_children(exclude_devices=(not include_devices))) == 0:
                lowest_areas.append(area)
            else:
                for child in area.get_children(exclude_devices=True):
                    traverse(child)

        traverse(area)
        return lowest_areas

    def get_greater_siblings(self, area_name, **args):
        area = self.get_area(area_name)
        greatest_parent = self.get_greatest_area(area_name)
        siblings = greatest_parent.get_direct_children()
        if area in siblings:
            siblings.remove(area)
        return siblings

    def get_lesser_siblings(self, area_name):
        area = self.get_area(area_name)
        greatest_parent = self.get_greatest_area(area_name)
        siblings = self.get_lowest_children(greatest_parent.name)
        if area in siblings:
            siblings.remove(area)
        return siblings

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
                if (
                    "direct_sub_areas" in area_data
                    and area_data["direct_sub_areas"] is not None
                ):
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
                if "outputs" in area_data and area_data["outputs"] is not None:
                    for output in area_data.get("outputs", []):
                        if output is not None:
                            if "kauf" in output:
                                new_light = KaufLight(output)
                                new_device = Device(new_light)

                                area.add_device(new_device)
                                new_device.set_area(area)

                                area_tree[output] = new_device
                            elif "blind" in output:
                                height = BLIND_HEIGHTS.get(output, 100)
                                new_blind = BlindDriver(output, height)
                                new_device = Device(new_blind)

                                area.add_device(new_device)
                                new_device.set_area(area)

                                area_tree[output] = new_device
                            elif "speaker" in output or "google_home" in output:
                                new_speaker = SpeakerDriver(output)
                                new_device = Device(new_speaker)

                                area.add_device(new_device)
                                new_device.set_area(area)

                                area_tree[output] = new_device

                # Add outputs as children
                if "inputs" in area_data:
                    inputs = area_data["inputs"]
                    log.info(f"Inputs: {inputs}")

                    if type(inputs) == list:
                        if inputs[0] is not None:
                            log.warning(f"Inputs are a list: {inputs}. Not processing")

                    elif type(inputs) == dict:
                        for input_type, device_id_list in area_data["inputs"].items():
                            if input_type is not None and device_id_list is not None:
                                for device_id in device_id_list:
                                    if device_id is not None:
                                        new_input = None
                                        if "motion" in device_id:
                                            log.info(f"lumi: {device_id}")
                                            new_input = MotionSensorDriver(
                                                input_type, device_id
                                            )
                                        elif "presence" in device_id:
                                            log.info(
                                                f"Creating presence device: {device_id}"
                                            )
                                            new_input = PresenceSensorDriver(
                                                input_type, device_id
                                            )
                                        elif "service" in device_id:
                                            log.info(
                                                f"Creating service device: {device_id}"
                                            )
                                            new_input = ServiceDriver(
                                                input_type, device_id
                                            )
                                        else:
                                            log.warning(
                                                f"Input has no driver: {device_id}"
                                            )

                                        if new_input is not None:
                                            new_device = Device(new_input)
                                            new_input.add_callback(
                                                new_device.input_trigger
                                            )

                                            area.add_device(new_device)
                                            new_device.set_area(area)

                                            area_tree[new_device.name] = new_device

        return area_tree

    def get_pretty_string(self):
        return self.get_area(self.root_name).get_pretty_string()


class Device:
    """Acts as a wrapper/driver for a device type -- interfaces between states and devices."""

    def __init__(self, driver):
        self.driver = driver
        self.name = driver.name
        self.last_state = None # The previous state before the current one (and current cache) was applied
        self.cached_state = None # The most recent applied state, used to fillout states.
        self.area = None
        self.tags = []
        self.locked=False

    # "Lock" The device so it can't be changed
    def lock(self, value=True):
        if value:
            log.info(f"Locking {self.name}")
        else:
            log.info(f"Unlocking {self.name}")
        self.locked = value

    def get_state(self):
        
        state = self.driver.get_state()
        log.info(f"Device:get_state(): Getting state for {self.name} state:{state}")
        state["name"] = self.name
        # self.cached_state = state #Update cached state to that of driver
        state=self.fillout_state_from_cache(state)
        log.info(f"Device:get_state(): filled out state: {state}")
        return state

    def get_last_state(self):
        if self.last_state is None:
            state = {} if self.cached_state is None else copy.deepcopy(self.cached_state)
        else:
            state = copy.deepcopy(self.last_state)
        state["name"] = self.name
        self.last_state = state
        log.info(f"Device:get_last_state(): Last state: {state}")
        return state

    def fillout_state_from_cache(self, state):
        if self.cached_state is not None and type(self.cached_state)==dict:
            log.info(f"Device:fillout_state_from_cache(): Filling out state {state} from cache: {self.cached_state}")
            for key, val in self.cached_state.items():

                if key not in state.keys():
                    state[key] = val
        return state

    def filter_state(self, state) :
        return self.driver.filter_state(state)


    def add_to_cache(self, state):
        # Remove keys that don't apply to driver (buttons don't have rgb color etc...)
        if state is not None :
            state=self.filter_state(state)

            self.last_state = self.cached_state
            new_state=copy.deepcopy(self.cached_state) # Set cached state as old state
            if new_state is None :
                new_state = {}
            for key, val in state.items():
                new_state[key] = copy.deepcopy(val) #update with new values
            self.cached_state = new_state
            log.info(f"add_to_cache: Added {state} to {self.last_state} to create Cached state: {self.cached_state}")

    def input_trigger(self, tags):
        global event_manager

        event = {"device_name": self.name, "tags": tags}
        log.info(f"Device {self.area.name} Triggered. Event: {event}")

        event_manager.create_event(event)

    def set_state(self, state):
        log.info(f"Setting state: {state} on {self.name}")
        if not self.locked:
            #TODO: FIXME this is a hack, should be done on driver side
            color_type=None
            if "rgb_color" in state:
                color_type="rgb"
            elif "color_temp" in state:
                color_type="temp"

            
            state = copy.deepcopy(state)
            if hasattr(self.driver, "set_state"):
                # I want this here so color/temp can be filled out when it is off
                # state = self.fillout_state_from_cache(state) #TODO: rethink how this is done in relation to add_to_cache
                if get_verbose_mode():
                    log.info(f"Setting state: {state} on {self.name}")
                #THIS IS A HACK, FIXME
                if color_type is not None:
                    if color_type == "rgb" and "color_temp" in state:
                        del state["color_temp"]
                    elif color_type == "temp" and "rgb_color" in state:
                        del state["rgb_color"]
                log.info(f"filled out state from cache: {state}")

                applied_state=self.driver.set_state(state)
                log.info(f"Applied state: {applied_state}")
                self.add_to_cache(applied_state)
                log.info(f"Updated cache: {self.cached_state}")
        else :
            if get_verbose_mode():
                log.info(f"Device {self.name} is locked, not setting state {state}")

    def get(self, value):
        if self.cached_state is None:
            return None
        return self.cached_state.get(value)

    def set_area(self, area):
        self.area = area

    def get_area(self):
        return self.area

    def add_tag(self, tag):
        self.tags.append(tag)

    def get_tags(self):
        return self.tags

    def get_name(self):
        return self.name

    def get_pretty_string(self, indent=1, is_direct_child=False, show_state=False):
        string_rep = (
            " " * indent + f"{('(Direct) ' if is_direct_child else '') + self.name}:\n"
        )

        if show_state:
            string_rep += " " * (indent + 2) + f"State: {self.get_state}\n"

        return string_rep


class MotionSensorDriver:
    def __init__(self, input_type, device_id):
        self.name = self.create_name(input_type, device_id)

        self.last_state = {}
        self.trigger = self.setup_service_triggers(device_id)

        self.callback = None

    def create_name(self, input_type, device_id):
        if "." in device_id:
            # get value after .
            device_id = device_id.split(".", 1)[1]
        name = f"{device_id}"
        return name

    def add_callback(self, callback):
        self.callback = callback

    def get_state(self):
        state = self.last_state
        state["name"] = self.name
        return state
    def get_valid_state_keys(self):
        return ["status"]

        

    def trigger_state(self, **kwargs):
        log.info(f"Triggering Motion Sensor: {self.name} with value: {kwargs}")
        if self.callback is not None:
            if "tags" in kwargs:
                tags = kwargs["tags"]
                log.info(f"tags are {tags}")
                self.callback(tags)
            else:
                log.info(f"No tags in kwargs {kwargs}")

    def setup_service_triggers(self, device_id):
        log.info(f"Generating trigger for: {device_id}")
        trigger_types = ["_ias_zone", "_occupancy"]
        values = ["on", "off"]

        triggers = []
        for trigger_type in trigger_types:
            if trigger_type == "_ias_zone":
                tag = "motion_detected"
            else:
                tag = "motion_occupancy"

            if f"binary_sensor.{device_id}{trigger_type}" in locals():
                log.info(f"IN LOCALS: {device_id}")
            if f"binary_sensor.{device_id}{trigger_type}" in globals():
                log.info(f"IN GLOBALS: {device_id}")

            for value in values:
                triggers.append(
                    generate_state_trigger(
                        f"binary_sensor.{device_id}{trigger_type} == '{value}'",
                        self.trigger_state,
                        {"tags": [value, tag]},
                    )
                )


class ServiceDriver:
    def __init__(self, input_type, device_id):
        self.name = device_id
        log.info(f"Creating Service Input: {self.name}")

        self.last_state = None
        self.trigger = self.create_trigger()

    def add_callback(self, callback):
        pass

    @service
    def create_trigger(self, **kwargs):
        @service
        def service_driver_trigger(**kwargs):
            log.info(f"Triggering Service: with value: {kwargs}")
            new_event = {}
            if "state" in kwargs:
                state = kwargs["state"]
                if "hs_color" in state:
                    hs_color = state["hs_color"]
                    rgb = hs_to_rgb(hs_color[0], hs_color[1])
                    rgb = [rgb[0], rgb[1], rgb[2]]
                    state["rgb_color"] = rgb

                    del state["hs_color"]

                if "temp" in state:
                    state["color_temp"] = state["temp"]
                    del state["temp"]
                if "name" in kwargs:
                    new_event["device_name"] = kwargs["name"]
                else:
                    new_event["device_name"] = self.name

                log.info(f"state: {state}")
                new_event["state"] = state

            get_event_manager().create_event(new_event)

        get_global_triggers().append(["Service", service_driver_trigger])

        return service_driver_trigger  # return the function created?

    def get_state(self):
        return {"name": self.name}
    
    def get_valid_state_keys(self):
        return []


class PresenceSensorDriver:
    def __init__(self, input_type, device_id):
        self.name = self.create_name(input_type, device_id)
        log.info(f"Creating Presence Sensor: {self.name}")

        self.last_state = None
        self.trigger = self.setup_service_triggers(device_id)

        self.callback = None

        self.value = None

    def create_name(self, input_type, device_id):
        if input_type in device_id:
            name = device_id
        else:
            name = f"{input_type}_{device_id}"

        log.info(f"Creating Presence Sensor: {name}")
        return name

    def add_callback(self, callback):
        self.callback = callback

    def get_state(self):
        state = self.last_state
        if state is None:
            state = {}
        state["name"] = self.name
        return state

    def get_valid_state_keys(self):
        return ["presence"]

    def trigger_state(self, **kwargs):
        log.info(f"Triggering Presence Sensor: {self.name} with value: {kwargs}")
        if self.callback is not None:
            if "tags" in kwargs:
                tags = kwargs["tags"]
                log.info(f"tags are {tags}")
                self.callback(tags)
            else:
                log.info(f"No tags in kwargs {kwargs}")

    def setup_service_triggers(self, device_id):
        log.info(f"Generating trigger for: {device_id}")
        values = ["on", "off"]

        triggers = []

        if f"binary_sensor.{device_id}" in locals():
            log.info(f"IN LOCALS: {device_id}")
        if f"binary_sensor.{device_id}" in globals():
            log.info(f"IN GLOBALS: {device_id}")

        for value in values:
            triggers.append(
                generate_state_trigger(
                    f"binary_sensor.{device_id} == '{value}'",
                    self.trigger_state,
                    {"tags": [value, "presence"]},
                )
            )

        return triggers

class KaufLight:
    """Light driver for kauf bulbs"""

    def __init__(self, name):
        self.name = name
        self.last_state = {}
        # These values are cached on the driver, whereas the whole state is cached on the device
        self.rgb_color = None
        self.brightness = None
        self.temperature = None
        self.default_color = None
        self.color_type = "rgb"

    # Status (on || off)
    def set_status(self, status, edit=0):
        """Sets the status of the light (on or off)"""

        self.apply_values(rgb_color=self.get_rgb())

    def get_status(self):
        """Gets status"""
        status="unavailable"
        try:
            status = state.get(f"light.{self.name}")

            log.info(f"KaufLight<{self.name}>:get_status(): Getting status {status}")
        except:
            pass

        if status is None or status == "unavailable":
            log.warning(f"KaufLight<{self.name}>:get_status(): Unable to get status- Returning unknown")
        return status

    def get_valid_state_keys(self):
        return ["status", "off", "rgb_color", "brightness", "color_temp", "hs_color"]

    def filter_state(self, state):
        valid_keys=self.get_valid_state_keys()
        filtered_state={}
        
        for key, val in state.items():
            if key in valid_keys:
                filtered_state[key]=val
        if "off" in filtered_state:
            del filtered_state["off"]
        if "status" in filtered_state:
            del filtered_state["status"]
        return filtered_state

    def is_on(self):
        status = self.get_status()
        if status is None or "off" in status or "unknown" in status or "unavailable" in status:
            return False
        log.info(f"KaufLight<{self.name}>:is_on(): Returning True: {status}")
        return True

    # RGB (color)
    def set_rgb(self, color, apply=False):
        self.color = color
        log.info(f"KaufLight<{self.name}>:set_rgb(): Caching color: {self.color}")
        if apply or self.is_on():
            self.apply_values(rgb_color=self.color)

    def get_rgb(self):
        """ If this is unable to get color, should return None"""
        color = None
        try:
            color = state.get(f"light.{self.name}.rgb_color")
        except:
            log.warning(f"Unable to get rgb_color from {self.name}")

        self.rgb_color = color


        return color if color != "null" else None

    # Brightness
    def set_brightness(self, brightness, apply=False):
        self.apply_values(brightness=str(brightness))

    def get_brightness(self):
        brightness = 255
        try:
            brightness = state.get(f"light.{self.name}.brightness")
        except:
            log.warning(f"get_brightness(): Unable to get brightness from {self.name}")

        if self.is_on():  # brightness reports as 0 when off
            self.brightness = brightness

        return brightness

    def set_temperature(self, temperature, apply=False):
        self.temperature = temperature
        self.apply_values(color_temp=self.temperature)

    def get_temperature(self):
        temperature = None
        try:
            temperature = state.get(f"light.{self.name}.color_temp")
        except:
            log.warning(f"Unable to get color_temp from {self.name}")

        if temperature is None or temperature == "null":
            if self.temperature is not None:
                log.info(f"KaufLight<{self.name}>:get_temperature(): temperature is {temperature}. Getting cached temperature")
                temperature = self.temperature
        else:
            self.temperature = temperature

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
        else:
            if not self.is_on():  # if already on, apply values
                state["off"] = 1

        return self.apply_values(**state)

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

        if self.color_type == "rgb":
            rgb = self.get_rgb()
            if rgb is not None:
                state["rgb_color"] = rgb
        else:
            color_temp = self.get_temperature()
            if color_temp is not None:
                state["color_temp"] = color_temp
        log.info(f"KaufLight<{self.name}>:get_state(): Returning state: {state}")
        return state

    # Apply values
    def apply_values(self, **kwargs):
        """This parses the state that is passed in and sends those values to the light."""

        new_args = {}
        for k, v in kwargs.items():
            if v is not None:
                new_args[k] = v


        # If rgb_color is present: save 
        if "rgb_color" in new_args.keys():
            self.rgb_color = new_args["rgb_color"] #TODO: Make setting states and caching their values more consistent and a seperate process
            # log.info(f"KaufLight<{self.name}>:apply_values(): Caching {self.name} rgb_color to {self.rgb_color }")
            self.color_type = "rgb"
            # log.info(f"KaufLight<{self.name}>:apply_values(): color_type is {self.color_type} -> {new_args}")

        elif "color_temp" in new_args.keys():
            self.color_temp = new_args["color_temp"]
            # log.info(f"KaufLight<{self.name}>:apply_values(): Caching {self.name} color_temp to {self.color_temp }")
            self.color_type = "temp"
            # log.info(f"KaufLight<{self.name}>:apply_values(): color_type is {self.color_type} -> {new_args}")

        else:
            # log.info(f"KaufLight<{self.name}>:apply_values(): Neither rgb_color nor color_temp in {new_args}")

            log.info(f"KaufLight<{self.name}>:apply_values(): color_type is {self.color_type} -> {new_args}")
            if self.color_type == "rgb":
                rgb = self.get_rgb()

                log.info(f"KaufLight<{self.name}>:apply_values(): rgb_color not in new_args. self rgb is {rgb}")
                if rgb is not None:
                    new_args["rgb_color"] = rgb
                    log.info(f"KaufLight<{self.name}>:apply_values(): Supplimenting rgb_color to {rgb}")
            else:
                temp = self.get_temperature()
                log.info(f"KaufLight<{self.name}>:apply_values(): color_temp not in new_args. self color_temp is {temp}")
                if temp is not None:
                    new_args["color_temp"] = temp
                    log.info(f"KaufLight<{self.name}>:apply_values(): Supplimenting color_temp to {temp}")

        if (
            "off" in new_args and new_args["off"]
        ):  # If "off" : True is present, turn off
            self.last_state = {"off": True}
            light.turn_off(entity_id=f"light.{self.name}")
            new_args["status"] = 0
            del new_args["off"]
            return new_args

        

        else:  # Turn on

                
            try:
                log.info(f"KaufLight<{self.name}>:apply_values(): {self.name} {new_args}")
                light.turn_on(entity_id=f"light.{self.name}", **new_args)
                self.last_state = new_args

            except Exception as e:
                log.warning(
                    f"\nPYSCRIPT: [ERROR 0/1] Failed to set {self.name} {new_args}: {e}"
                )
                light.turn_on(entity_id=f"light.{self.name}")
                self.last_state = {"on": True}

        return self.last_state


class BlindDriver:
    """Driver for smart blinds controllable by percent closed or height."""

    def __init__(self, name, height=100):
        self.name = name
        self.height = height
        self.last_state = {"closed_percent": 0}

    def get_valid_state_keys(self):
        return ["closed_percent", "height"]

    def filter_state(self, state):
        valid = self.get_valid_state_keys()
        return {k: v for k, v in state.items() if k in valid}

    def get_state(self):
        position = None
        try:
            position = state.get(f"cover.{self.name}.current_position")
        except Exception:
            pass
        if position is None:
            position = 100 - self.last_state.get("closed_percent", 0)
        closed = 100 - int(position)
        result = {"closed_percent": closed}
        if self.height:
            result["height"] = self.height * (100 - closed) / 100
        self.last_state = result
        return result

    def set_state(self, state):
        state = self.filter_state(state)
        percent = None
        if "height" in state and self.height:
            percent = 100 - int((state["height"] / self.height) * 100)
        elif "closed_percent" in state:
            percent = state["closed_percent"]

        if percent is not None:
            position = max(0, min(100, 100 - percent))
            try:
                cover.set_cover_position(entity_id=f"cover.{self.name}", position=position)
            except Exception as e:
                log.warning(f"Failed to set blind {self.name} to {position}% open: {e}")
            self.last_state = {"closed_percent": percent}
            if self.height:
                self.last_state["height"] = self.height * (100 - percent) / 100
        return self.last_state


class SpeakerDriver:
    """Driver for smart speakers such as Google Home."""

    def __init__(self, name):
        self.name = name
        self.last_state = {"volume": None, "playing": None}

    def get_valid_state_keys(self):
        return ["volume"]

    def filter_state(self, state):
        valid = self.get_valid_state_keys()
        return {k: v for k, v in state.items() if k in valid}

    def get_state(self):
        volume = None
        playing = None
        try:
            volume = state.get(f"media_player.{self.name}.volume_level")
        except Exception:
            pass
        try:
            status = state.get(f"media_player.{self.name}.state")
            if status == "playing":
                playing = state.get(f"media_player.{self.name}.media_title")
        except Exception:
            pass
        self.last_state = {"volume": volume, "playing": playing}
        return self.last_state

    def set_state(self, state):
        state = self.filter_state(state)
        if "volume" in state and state["volume"] is not None:
            try:
                media_player.volume_set(entity_id=f"media_player.{self.name}", volume_level=state["volume"])
            except Exception as e:
                log.warning(f"Failed to set volume for {self.name}: {e}")
        self.last_state.update(state)
        return self.last_state


# def test_toggle(area_name="kitchen") :
#     event_manager=get_event_manager()

#     scope={"get_area_local_scope": [area_name]}

#     area=event_manager.area_tree.get_area(area_name)

#     # Set initial color for area
#     event = {
#         "device_name": "service_input_all_",
#         "state:": {"status": 1, "rgb_color": [255, 0, 0]}
#     }.update(scope)

#     area_state=area.get_state()
#     if area_state["status"] :
#         log.fatal("Failed turning on test")

#     #toggle status
#     event = {
#         "device_name": "service_input_button_single",
#     }.update(scope)


@service
def test_event():
    log.info("TEST")
    unittest.main()
    # reset()
    # log.info(get_event_manager().area_tree.get_pretty_string())
    log.info("STARTING TEST EVENT")
    name = "TEST_TRACKER"
    event = {
        "device_name": name,
        "scope": [{"get_area_local_scope": ["office"]}],
        "functions": {
            "update_tracker" : []
        }
    }
    log.info(f"\nCreating Event: {event}")

    event_manager.create_event(event)





class TestManager():

    def __init__(self) :
        self.default_test_room="laundry_room"
        self.event_manager = get_event_manager()
        self.area_tree = get_area_tree()
        self.default_test_area=self.area_tree.get_area(self.default_test_room)
        log.info(f"AREA DEVICES: {self.default_test_area.get_devices()}")
        self.default_test_light = self._find_light()
        self.default_motion_sensor = self._find_motion_sensor()

    def _find_motion_sensor(self) :
        for device in self.default_test_area.get_devices() :
            if device.get_name().startswith("motion_sensor") :
                return device

    def _find_light(self) :
        # for device in self.default_test_area.get_devices() :
        #     log.info(f"LIGHT: {device.get_name()}")
        #     if device.get_name().startswith("kauf") :
        #         return device
        return self.area_tree.get_device("kauf_laundry_room_2")

    def run_tests(self) :
        tests_run=0
        tests_passed=0
        failed_tests=[]
        # get all methods in this class and check if their name starts with "test"
        log.info(dir(self))
        for method_name in dir(self):
            if method_name.startswith("test"):
                if getattr(self, method_name)() :
                    log.info(f"Test {tests_run+1}: {method_name} PASSED")

                    tests_passed+=1
                else :
                    log.info(f"Test {tests_run+1}: {method_name} FAILED")

                    failed_tests.append(method_name)
                tests_run+=1

        log.info(f"Tests passed: {tests_passed}/{tests_run}")

        if len(failed_tests) > 0 :
            log.info(f"Failed tests: {failed_tests}")
            return False
        
    # Test methods for merge_data
    def test_merge_data_empty_list(self):
        try:
            merge_data([])
            return False
        except ValueError:
            return True

    def test_merge_data_integers(self):
        return merge_data([1, 2, 3, 4, 5]) == 3.0

    def test_merge_data_floats(self):
        return merge_data([1.5, 2.5, 3.5]) == 2.5

    def test_merge_data_mixed_numbers(self):
        return merge_data([1, 2.5, 3]) == 2.1666666666666665

    def test_merge_data_lists(self):
        return merge_data([[1, 2], [3, 4], [5, 6]]) == [3.0, 4.0]

    def test_merge_data_lists_with_different_lengths(self):
        result = merge_data([[1, 2], [3, 4, 5], [6]])
        return result == [3.3333333333333335, 3.0, 5.0]

    def test_merge_data_dicts(self):
        data = [{"a": 1, "b": 2}, {"a": 3, "b": 4}, {"a": 5}]
        expected = {"a": 3.0, "b": 3.0}
        return merge_data(data) == expected

    # Test methods for merge_states
    def test_merge_states(self):
        states = [{"status": 0}, {"status": 1}, {"status": 1}]
        result = merge_states(states)
        return result["status"] == 1

    def test_merge_states_no_status(self):
        states = [{"other": 5}, {"other": 10}]
        result = merge_states(states)
        return "status" in result and result["status"] == 0


    def test_set_setting_status(self):
        """
        A test function to check setting status functionality by turning on and off from different initial states.
        """
        log.info("STARTING TEST SETTING STATUS")
        initial_state=self.default_test_area.get_state()
        # turn on from unknown default state
        self.default_test_area.set_state({"status": 1})
        time.sleep(.1)
        current_state=self.default_test_area.get_state()
        if not current_state["status"] :
            log.info(f"Failed to turn on from initial state {initial_state}")
            return False
        # Turn off from on
        self.default_test_area.set_state({"status": 0})
        time.sleep(.1)
        log.info(f"Test testting test: current state: {self.default_test_area.get_state()}")
        
        current_state=self.default_test_area.get_state()
        log.info(f"current state: { current_state['status']}")
        if current_state["status"] :
            log.info(f"Failed to turn off from on")
            return False

        # Turn on from off
        self.default_test_area.set_state({"status": 1})
        time.sleep(.1)
        current_state=self.default_test_area.get_state()
        if not current_state["status"] :
            log.info(f"Failed to turn on from off")
            return False

        return True

    def test_setting_cache(self) :
        log.info("STARTING TEST SETTING CACHE")
        self.default_test_light.set_state({"status": 1, "rgb_color": [255, 255, 255]})
        time.sleep(.1)
        self.default_test_light.set_state({"status": 0})
        time.sleep(.1)
        state=self.default_test_light.get_state()
        if state["status"] != 0 :
            log.info(f"test_setting_cache: Failed to set to off {state}")
            return False
        
        if state["rgb_color"] != [255, 255, 255] and state["rgb_color"] != (255, 255, 255) :
            log.info(f"test_setting_cache: Failed to keep rgb_color {state}")
            return False

        log.info("test_setting_cache: Setting cache to {'rgb_color': [255, 0, 255]}")
        self.default_test_light.add_to_cache({"rgb_color": [255, 0, 255]})
        time.sleep(.1)
        state=self.default_test_light.get_state()
        if state["status"] != 0 or state["rgb_color"] != [255, 0, 255] :
            log.info(f"test_setting_cache: Failed to update cache {state}")
            return False

        return True

    def test_set_and_get_color(self):
        log.info("TEST SETTING AND GETTING COLOR")
        # Set to off as default
        log.info("TEST: setting status 0 and rgb 000")
        self.default_test_area.set_state({"rgb_color": [0, 0, 0], "status":0})
        time.sleep(.1)
        state=self.default_test_area.get_state()

        if state["status"] != 0:
            log.warning(f"test_set_and_get_color: Failed to set to off {state}")
            return False

        if "rgb_color" in state and state["rgb_color"] != [0, 0, 0] :
            log.warning(f"Failed to set color while setting off {state}")
            return False


        log.info("TEST: setting rgb while off")
        # Set color while off
        self.default_test_area.set_state({"rgb_color": [255, 255, 255]})
        time.sleep(.1)
        state=self.default_test_area.get_state()
        if "rgb_color" in state and state["rgb_color"] != [255, 255, 255] :
            log.warning(f"TEST: Failed to set color while off {state}")
            return False
        if state["status"] != 0:
            log.warning(f"TEST: Failed to stay off when setting color {state}")

        log.info("TEST: turning on")
        # turn on 
        self.default_test_area.set_state({"status":1})
        time.sleep(.1)
        state=self.default_test_area.get_state()
        if state["status"] != 1:
            log.warning(f"TEST: Failed to turn on {state}")
            return False

        if state["rgb_color"] != [255, 255, 255]:
            log.warning(f"TEST: Failed to keep color that was set while off {state}")
            return False

        log.info("TEST: setting rgb while on")

        # Change color while on 
        self.default_test_area.set_state({"rgb_color": [0, 255, 0]})
        time.sleep(.1)
        state=self.default_test_area.get_state()
        if state["rgb_color"] != [0, 255, 0] or state["status"] != 1:
            log.warning(f"TEST: Failed to change color while on {state}")
            return False
            
        
        log.info(f"TEST: current state: {self.default_test_area.get_state()}")

        self.default_test_area.set_state({"rgb_color": [255, 195, 50]})
        time.sleep(.1)
        self.default_test_area.set_state({"status": 0})
        time.sleep(.1)
        self.default_test_area.set_state({"status": 1})
        time.sleep(.1)
        state=self.default_test_area.get_state()
        if state["rgb_color"] != [255, 195, 50] or state["status"] != 1:
            log.warning(f"test_set_and_get_color: Failed to persist through toggle {state}")
        return True

    # TODO:
    # Test setting brightness
    # test buttons
    # Test tracks
    # Add tests for setting via service driver
    # FIgure out how to handle reading from cache with both rgb color and temp
    # Test helper functions

    # Test combine states
    def test_combine_states(self):
        log.info("STARTING TEST COMBINE STATES")
        states = [
            {"status": 1, "brightness": 255, "rgb_color": [255, 255, 0]},
            {"status": 1, "rgb_color": [255, 0, 0]},
            {"status": 0, "brightness": 100, "rgb_color": [0, 255, 255]},
        ]
        fist_expected_state = {"status": 1, "brightness": 255, "rgb_color": [255, 255, 0]}
        first_state_result = combine_states(states, strategy="first")

        if first_state_result != fist_expected_state:
            log.warning(f"Expected first state to be {fist_expected_state} but was {first_state_result}")
            return False
        
        last_expected_state = {"status": 0, "brightness": 100, "rgb_color": [0, 255, 255]}
        last_state_result = combine_states(states, strategy="last")

        if last_state_result != last_expected_state:
            log.warning(f"Expected last state to be {last_expected_state} but was {last_state_result}")
            return False
        
        average_expected_state = {"status": 1, "brightness": 177.5, "rgb_color": [170, 170, 85]}
        average_state_result = combine_states(states, strategy="average")

        if average_state_result != average_expected_state:
            log.warning(f"Expected average state to be {average_expected_state} but was {average_state_result}")
            return False

        return True
        

    def test_motion_sensor(self) :
        # When motion sensor is triggered, the area should be turned off.
        log.info(f"test_motion_sensor: starting: Area {self.default_test_area}")
        initial_state=self.default_test_area.get_state()
        log.info(f"test_motion_sensor: initial state: {initial_state}")
        # Set to known initial state
        #TODO: Enable a way of testing this with various state rules. currently most of state us not checkable
        self.default_test_area.set_state({"status": 1, "brightness": 255, "rgb_color": [255, 72, 35]})
        time.sleep(.1)
        # Set to off
        self.default_test_area.set_state({"status": 0})
        time.sleep(.1)
        log.info(f"test_motion_sensor: state after off: {self.default_test_area.get_state()}")

        event_manager.create_event({'device_name': self.default_motion_sensor.name, 'tags': ['on', 'motion_occupancy']})
        time.sleep(.2)
        # Check if area is on
        state=self.default_test_area.get_state()
        log.info(f"test_motion_sensor: state after motion: {state}")
        if state['status'] != 1 :
            log.warning(f"test_motion_sensor: Failed - Expected area to be on after motion sensor trigger but was {state}")
            return False
        if state["brightness"] != 255 :
            log.warning(f"test_motion_sensor: Failed - Expected brightness to be 255 but was {state['brightness']}")
            return False

        #TODO: Figure out how to have deterministic states with motion on
        # if state["rgb_color"] != [255, 72, 35]:
        #     log.warning(f"test_motion_sensor: Failed - Expected rgb_color to be [255, 72, 35] but was {state['rgb_color']}")
        #     return False


        # Test motion sensor deactivation
        self.default_test_area.set_state({"status": 0})
        set_motion_sensor_mode("off")
        time.sleep(.2)
        event_manager.create_event({'device_name': self.default_motion_sensor.name, 'tags': ['on', 'motion_occupancy']})

        time.sleep(.2)
        state=self.default_test_area.get_state()
        if state['status'] != 0:
            log.warning(f"Expected area to be off after motion sensor deactivation but was {self.default_test_area.get_state()}")
            return False

        # cleanup
        set_motion_sensor_mode("on")
        return True

@service 
def run_tests() :
    log.info("TEST")
    test_manager=TestManager()
    test_manager.run_tests()
    




init()
run_tests()

@event_trigger(EVENT_CALL_SERVICE)
def monitor_service_calls(**kwargs):
    log.info(f"got EVENT_CALL_SERVICE with kwargs={kwargs}")

# This monitors other methods of settings lights colors and informs the area tree
@event_trigger(EVENT_CALL_SERVICE)
def monitor_external_state_setting(**kwargs):
    if "domain" in kwargs:
        if kwargs["domain"] == "light":
            data=kwargs["service_data"]
            device_names=[]
            if "entity_id" in data:

                def fix_entity_name(entity_id) :
                    entity_id=entity_id.strip("light.")
                    if entity_id.endswith("_"): entity_id+="light"
                    return entity_id

                if type(data["entity_id"]) == str:
                    device_names.append(fix_entity_name(data["entity_id"]))
                elif type(data["entity_id"]) == list:
                    for device_name in data["entity_id"] :
                        device_names.append(fix_entity_name(device_name))
            
            state={}
            if "brightness" in data:
                state["brightness"]=data["brightness"]
            if "color_temp" in data:
                state["color_temp"]=data["color_temp"]
            if "rgb_color" in data:
                state["rgb_color"]=data["rgb_color"]
            if "hs_color" in data:
                state["rgb_color"]=hs_to_rgb(data["hs_color"][0], data["hs_color"][1])

            if state == {}:
                state["status"]=False

            event_manager=get_event_manager()

            devices=[]
            for device_name in device_names:
                log.info(f"ATTEMPTING TO SET DEVICE {device_name} TO {state}")
                device=event_manager.area_tree.get_device(device_name) #FIXME: The names do not match up, need a lookup
                if device is not None:
                    devices.append(device)
                    device_state=device.get_state()
                    if device_state is not None:
                        if get_state_similarity(device_state, state)<=0.5: 
                            log.info(f"SETTING DEVICE {device_name} TO {state}")
                            # device.set_state(state)
                else :
                    log.info(f"DEVICE {device_name} NOT FOUND")


### Tests ###


# Test if motion sensor sets state correctly




@service
def test_tracks() :
    log.info("STARTING TEST TRACKS")
    event_manager = get_event_manager()
    tracker_manager=get_tracker_manager()
    event_manager.create_event({'device_name': 'motion_sensor_laundry_room', 'tags': ['on', 'motion_occupancy']})
    time.sleep(0.2)
    event_manager.create_event({'device_name': 'motion_sensor_office', 'tags': ['on', 'motion_occupancy']})
    time.sleep(0.2)

    event_manager.create_event({'device_name': 'motion_sensor_hallway', 'tags': ['on', 'motion_occupancy']})
    time.sleep(0.2)

    event_manager.create_event({'device_name': 'motion_sensor_kitchen', 'tags': ['on', 'motion_occupancy']})
    time.sleep(0.2)

    # event_manager.create_event({'device_name': 'motion_sensor_outside', 'tags': ['on', 'motion_occupancy']})

    # event_manager.create_event({'device_name': 'motion_sensor_chair_0', 'tags': ['on', 'motion_occupancy']})

    # event_manager.create_event({'device_name': 'motion_sensor_chair_1', 'tags': ['on', 'motion_occupancy']})

    # event_manager.create_event({'device_name': 'motion_sensor_living_room_back', 'tags': ['on', 'motion_occupancy']})

    log.info(tracker_manager.get_pretty_string())

#test_tracks()