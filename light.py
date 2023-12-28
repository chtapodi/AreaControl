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


class PhotonLight:  # (Light) :
    def __init__(self, name, config, token):
        self.name = name
        if config["type"] == "photon":
            print(f"Init {self.name} photon light")
        else:
            print("Wrong light type")
            exit()

        self.config = config
        self.color = self.config["saved_colors"]
        self.brightnesses = self.config["saved_brightnesses"]
        self.brightness = 255  # TODO
        self.color_converter = ColorConverter()

        self.id = self.config["id"]
        self.token = token

        self.db = DatabaseInterface(name)

    def binary_to_status(self, input):
        if input == 0:
            input = "off"
        elif input == 1:
            input = "on"
        return input

    def status_to_select(self, input):
        if input == "on":
            input = 0
        elif input == "off":
            input = 11
        return input

    def status_to_binary(self, input):
        if input == "off":
            return 0
        else:
            return 1

    def select_to_binary(self, input):
        if input == 0:
            input = 0
        elif input == 11:
            input = 1
        return input

    def set_status(self, status, edit=0):
        status = self.binary_to_status(status)

        self._post_command(status)
        self.db.set_value("select_val", self.status_to_select(status))
        self.db.set_value("edited", edit)

    def set_hs(self, hs):
        r, g, b = self.color_converter.hs_to_rgb(
            float(hs[0]) - get_offset(float(hs[0])), float(hs[1])
        )
        self.set_rgb((r, g, b))
        self.db.set_value("r", r)
        self.db.set_value("g", g)
        self.db.set_value("b", b)

    def set_rgb(self, rgb):
        log.warning(f"\nPYSCRIPT: RGB {rgb}")
        r, g, b = rgb
        self._post_command(f"rgb:{r},{g},{b}")
        self.db.set_value("r", r)
        self.db.set_value("g", g)
        self.db.set_value("b", b)

    def set_rgb(self, color, apply=False):
        self.set_rgb(color)

    def set_k(self, k):
        # I don't really remember what the deal with this code is. I think translating between HA kelvin and normal kelvin?
        k = 1000000 / int(args.set_k)
        k = int(args.set_k)
        k = map_vals(k, 170, 500, 6000, 1200)

        # self.db.set_value('k',k)
        r, g, b = self.color_converter.k_to_rgb(k)

        # I do not recall why I did this and have yet to test it
        g = g - 5
        b = b + 5
        self._post_command(name, "rgb:{},{},{}".format(r, g, b), token)
        self.db.set_value("r", r)
        self.db.set_value("g", g)
        self.db.set_value("b", b)

    def set_brightness(self, alpha, apply=False):
        self._post_command(f"alpha:{alpha}")
        self.db.set_value("a", alpha)

    # Getters
    def get_status(self):
        # status=self.db.get_value('select_val')
        status = self.select_to_binary(status)
        return status

    def get_rgb(self):
        r = self.get_r()
        g = self.get_g()
        b = self.get_b()
        return r, g, b

    def get_r(self):
        c = self.db.get_value("r")
        return c

    def get_g(self):
        c = self.db.get_value("g")
        return c

    def get_b(self):
        c = self.db.get_value("b")
        return c

    def get_brightness(self):
        brightness = self.db.get_value("a")
        return brightness

    @pyscript_compile
    async def _post_command(self, command):
        def post(command):
            url = "https://api.particle.io/v1/devices/events"
            r = requests.post(
                url,
                {
                    "name": "chtapodi{0}".format(self.name),
                    "data": command,
                    "private": "false",
                    "access_token": self.token,
                },
            )

        await hass.async_add_executor_job(post, command)


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
