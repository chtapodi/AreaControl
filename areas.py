
class Area :
    def __init__(self, name) :

        self.ochildren=[]
        self.tchildren=[]
        self.parent=None
        
        self.devices=[]

    def add_child(self, child) :
        ...
    def get_children(self, filter=None) :
        ...

    def get_value(self, value_id, filter=None) :
        # state.get(f'light.{self.name}.brightness')
        ...

    def set_value(self, value_id, filter=None) :
        ...

    
    def _accumulate_values(self, value_id, filter=None) :
        """Gets values from children of area and accumulates them

        Args:
            value_id (id): ID for value to get
            filter (filter, optional): Filter for children. Defaults to None.
        """        