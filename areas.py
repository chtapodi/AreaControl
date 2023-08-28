import yaml
import os


class Area:
    def __init__(self, name):
        self.name = name
        self.children = []
        self.parent = None

        self.devices = []

    def add_child(self, child):
        self.children.append(child)
        ...

    def get_children(self, filter=None):
        ...

    def get_value(self, value_id, filter=None):
        # state.get(f'light.{self.name}.brightness')
        ...

    def set_value(self, value_id, filter=None):
        ...

    def _accumulate_values(self, value_id, filter=None):
        """Gets values from children of area and accumulates them

        Args:
            value_id (id): ID for value to get
            filter (filter, optional): Filter for children. Defaults to None.
        """

    def pretty_print(self, prefix=""):
        ret=""
        ret += f"{prefix}{self.name}\n"

        if len(self.devices) > 0:
            ret += f"Devices:\n"

            for devices in self.devices:
                ret += f"\t{device.name}\n"
            # ret += f"\n"

        elif len(self.children) > 0:
            ret += f"{prefix}>children of {self.name}:\n"
            for child in self.children:
                child_str=child.pretty_print(prefix+'-')
                ret += f"{child_str}"
            # ret += f"\n"

        # ret += f"\n"
        return ret

    def __repr__(self):
        return self.name

    def __eq__(self, other):
        if isinstance(other, str):
            return self.name == str
        if isinstance(other, Area):
            return self.name == other.name
        else:
            return self == other


class AreaTree:
    def __init__(self):
        self.root = None
        self.areas = []

    def create_tree(self, yml_file):
        with open(yml_file, "r") as file:
            area_descriptions = yaml.safe_load(file)
        print(area_descriptions)

        created_areas = []


        def create_child(parent, child):
            if child not in created_areas:
                if child in area_descriptions:
                    new_area = create_area(child, area_descriptions[child])
                    parent.add_child(new_area)
                    created_areas.append(new_area)
                else:
                    print(f"\nERROR: child {child} does not have a description\n")
                    return None

        def create_area(area_name, area_data):
            area = Area(area_name)

            if "children" in area_data:
                children = area_data["children"]
                if isinstance(children, list):
                    if len(children) > 0:
                        for child in children:
                            create_child(area, child)
                elif isinstance(children, str):
                    create_child(area, children)

            return area

        self.root=create_area("everything", area_descriptions["everything"])
        created_areas.append(self.root)

        for area in area_descriptions :
            if area not in created_areas:
                new_area = create_area(area, area_descriptions[area])
                created_areas.append(new_area)

        print(self.root.pretty_print("|"))


print("start")
tree = AreaTree()
tree.create_tree("./areas.yml")
