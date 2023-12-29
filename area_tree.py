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

class Device:
    """Acts as a wrapper/driver for a device type -- interfaces between states and devices."""

    def __init__(self, driver):
        self.driver = driver
        log.warning(f"\nPYSCRIPT: trying")

        self.device_name = driver.name
        log.warning(f"\nPYSCRIPT: {self.device_name=}")


        self.method_names = self.parse_methods()


        
        

    def parse_methods(self):
        """
        Parses the devices's interfaces and returns a list of their names.
        """
        interfaces=[]
        log.warning(f"\nPYSCRIPT: Parsing")
        
        for m in dir(self.driver) :
            log.warning(f"\nPYSCRIPT: {m}")

            if (not m.startswith("_") and callable(getattr(self.obj, m))) :
                if m.startswith("get_") or m.startswith("set_") :
                    m=m[4:]
                if m not in methods :
                    interfaces.append(m)
        return interfaces

    def get_state(self):
        "Gets the state of the device"
        state = {}
        
        for name in self.method_names:
            method_name = "get_" + name
            method = getattr(self.device, method_name)
            result = method()
            state[name]=result


        for direction, states in STATE_VALUES :
            for key, value in states :
                if key in self.method_names : # if this part of the state is something this device has
                    method_name = "get_" + key
                    method = getattr(self.device, method_name)
                    result = method()
                    state[direction][key]=result


        return state

    def set_state(self, state):
        """Sets the state of the device (if applicable)"""

        #Filters the states for which methods exist
        applicable_state={}
        for key in state :
            if key in self.method_names :
                applicable_state[key]=state[key]

        self.device.set_state(applicable_state)
    




class KaufLight:
    """Light driver for kauf bulbs"""

    def __init__(self, name):
        self.name = name
        self.last_state = None

        # self.color_converter = ColorConverter()


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
        self.apply_values(state)

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

    driver=KaufLight("kauf_tube")
    log.warning(f"\nPYSCRIPT: Init driver")

    device=Device(driver)
    log.warning(f"\nPYSCRIPT: Init device")

    state=device.get_state()
    log.warning(f"\nPYSCRIPT: {state=}")




    

# test_classes()