class ColorConverter:
    def __init__(self):
        pass

    def rgb_to_hsl(r, g, b):
        h, s, l = Color(rgb=[r, g, b]).hsl
        l_range = 50 - 100
        s_range = 100
        s = ((l - 100) * s_range) / l_range
        return h, s, l

    def hs_to_rgb(h, s):
        return Color(hsl=[h, s, 50]).rgb

    def k_to_rgb(self, k):
        r, g, b = convert_K_to_RGB(k)
        return r, g, b



class HueLight:  # (Light) :
    def __init__(self, name, config, token, config_path="./pyscript/room_config.yml"):
        self.name = name
        self.keys = ["rgb"]

        if config["type"] == "hue":
            print(f"Init {self.name} hue light")
        else:
            print("Wrong light type")
            exit()

        self.config = config
        self.color = self.config["saved_colors"]
        self.brightnesses = self.config["saved_brightnesses"]
        self.brightness = 255  # TODO
        self.color_converter = ColorConverter()

        self.token = token

    def set_status(self, status, edit=0):
        if status == 1 or status == "on" or status == "1":
            self.apply_values()

        else:
            light.turn_off(entity_id=f"light.{self.name}")

    def get_status(self):
        try:
            status = state.get(f"light.{self.name}")

            return status
        except:
            pass
        return 0


    def set_rgb(self, color, apply=False):
        """Sets the color of the bulb"""
        self.apply_values(rgb_color=str(color))

    def set_brightness(self, brightness, apply=False):
        self.apply_values(brightness=str(brightness))

    def get_rgb(self):
        color = state.get(f"light.{self.name}.rgb_color")
        return color

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

    def apply_values(self, **kwargs):
        log.warning(f"\nPYSCRIPT: [????] TRYING to set {self.name} {kwargs}")

        # todo:
        del kwargs["strength"]
        # for key, value in kwargs.items() :
        # self.db.set_value(key, value)
        try:
            light.turn_on(entity_id=f"light.{self.name}")
            # for key, value in kwargs.items() :
            # self.db.set_value(key, value)
        except Exception as e:
            log.warning(
                f"\nPYSCRIPT: [ERROR] Failed to set {self.name} {kwargs}: {str(e)}"
            )
            return False


class KaufLight:
    """Light driver for kauf bulbs"""

    def __init__(self, name, config, token, config_path="./pyscript/room_config.yml"):
        self.name = name
        self.last_state = None

        if config["type"] == "kauf":
            print(f"Init {self.name} kauf light")
        else:
            print("Wrong light type")
            exit()

        self.config = config
        self.color = self.config["saved_colors"]
        self.brightnesses = self.config["saved_brightnesses"]
        self.brightness = 255  # TODO
        self.color_converter = ColorConverter()

        self.token = token

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
