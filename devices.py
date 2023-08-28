

class Device :
    def __init__(self, name, filters) :
        self.name=name
        self.filters=filters
        self.got_history=[]
        self.set_history=[]
        self.current_value=None
        

    def get_value(self, value_id, recurse=True, filter=None):
        # state.get(f'light.{self.name}.brightness')
        ...

    def set_value(self, value_id, recurse=True, filter=None):
        ...

    def __repr__(self) :
        return self.name

    def pretty_print(self, prefix="") :
        ret=""
        ret += f"{prefix}-{self.name}\n"
        ret += f"{prefix}--Current value: {self.current_value}\n"
        return ret