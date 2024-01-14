import yaml
import networkx as nx
import matplotlib.pyplot as plt


@pyscript_compile
def load_yaml(path):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data


class graphManager: 

    def __init__(self, connection_config):
        self.connections=load_yaml(connection_config)
        self.graph = self.create_graph(self.connections)
        self.tracks=None
        

    def create_graph(self, connections) :
        log.info(f"CONNECTIONS: {connections}")
        connection_pairs=[]
        for connection in connections["connections"] :
            for start, end in connection.items():
                connection_pairs.append((start,end))

        log.info(f"connection_pairs: {connection_pairs}")
        graph = nx.Graph()
        graph.add_edges_from(connection_pairs)
        return graph


    def visualize_graph(self, output_file="graph.png"):
        log.info(f"graph: {self.graph}")
        if self.graph is not None :
            self._visualize_graph(self.graph, self.tracks, filename=output_file)
        else :
            log.info("No graph to visualize")
# Function to visualize the graph
    def _visualize_graph(self, graph, tracks=None, filename="graph.png"):
        pos = nx.kamada_kawai_layout(graph)  # Adjust layout if needed
        # colors = [
        #     "cyan" if area_info[node]["state"] == "occupied" else "green"  # Cyan for occupied areas
        #     for node in graph.nodes
        # ]

                
        visit_numbers = {}  # Initialize dictionary for visit order
        for i, track in enumerate(tracks):
            for j, (start, end) in enumerate(track):
                visit_numbers[start] = i * 10 + j + 1  # Assign unique numbers

        labels = {node: f"{node}\n{visit_numbers.get(node, '')}" for node in graph.nodes}  # Add numbers to labels

        nx.draw(graph, pos, node_color=colors, with_labels=True, labels=labels, font_color="black", arrows=True, arrowsize=10, node_size=400)

        if tracks:
            for track in tracks:
                nx.draw_networkx_edges(graph, pos, edgelist=track, edge_color="cyan")

        plt.axis("off")

        # Print area information if needed
        for node, info in area_info.items():
            print(f"{node}: {info}")

        plt.savefig(filename)  # Save the image





example_track = [
    ("outside", "living_room"),
    ("living_room", "dining_room"),
    ("dining_room", "kitchen"),
    ("kitchen", "outside"),
]


@service 
def plot_graph():
    log.info(f"STARTING")
    graph_manager=graphManager("./pyscript/connections.yml")
    graph_manager.visualize_graph()


plot_graph()
# Example usage:
# visualize_graph(graph, area_info, filename="house_graph.png")


