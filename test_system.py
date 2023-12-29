
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
def TESTIT() :

    color=state.get(f"light.kauf_tube.rgb_color")
    log.warning(f"\nPYSCRIPT: colorzz {color}")

    light=KaufLight("kauf_tube")
    log.warning(f"\nPYSCRIPT: INIT")

    
    color=light.get_brightness()
    # color=light.get_brightness()
    log.warning(f"\nPYSCRIPT: CIKIR?? {color}")

