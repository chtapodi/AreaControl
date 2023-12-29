
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

    def __init__(self, device_type, device_interface):
        self.interface = device_interface
        self.device_name = obj.__class__.__name__
        self.device_type = device_type

        self.method_names = self.parse_methods()


        
        

    def parse_methods(self):
        """
        Parses the devices's interfaces and returns a list of their names.
        """
        interfaces=[]
        for m in dir(self.obj) :
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
    

