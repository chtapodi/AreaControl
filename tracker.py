import yaml
import networkx as nx
import matplotlib.pyplot as plt
import time


@pyscript_compile
def load_yaml(path):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data


class Track:
    """
    A track can only exist if there is at least one event.
    if there is only one event, duration is time since trigger

    """

    def __init__(self, area, max_length=5):
        self.track = [(area, 0)]  # First event
        self.max_length = max_length
        self.last_event_time = time.time()

    def add_event(self, area, person=None):
        track = self.get_track()
        new_event = (area, 0)
        self.last_event_time = time.time()
        # add new event to track start
        track.insert(0, new_event)
        log.info(f"new track: {track}")
        self.track = track

    def get_head(self):
        return self.get_track()[0]

    def get_track(self):
        track = self.track
        head = track[0]
        duration = time.time() - self.last_event_time
        track[0] = (head[0], duration)
        return track

    def _trim(self):
        if len(self.track) > self.max_length:
            log.info(f"trimming track: {self.track}")
            self.track = self.track[-self.max_length :]
            log.info(f"trimmed track: {self.track}")

    def get_duration(self):
        total = 0
        for event in self.get_track():
            total += event[1]
        return total

    def get_area(self):
        return self.get_head()[0]


class TrackManager:
    def __init__(self, max_track_length=5, oldest_track=30 * 60, max_tracks=10):
        self.tracks = []
        self.max_track_length = max_track_length
        self.oldest_track = oldest_track
        self.max_tracks = max_tracks
        self.graph_manager = GraphManager("./pyscript/connections.yml")

    def add_event(self, area, person=None):
        new_track = Track(area, person)
        self.try_associate_track(new_track)

    def try_associate_track(self, new_track):
        log.info(
            f"trying to associate track: {new_track.get_track()} with {self.get_tracks()}"
        )
        if len(self.get_tracks() )> 0:
            track_scores = []

            area = new_track.get_area()
            for track in self.tracks:
                log.info(f"track: {track}, area: {area}")
                score = self.graph_manager.get_distance(track.get_area(), area)
                track_scores.append((track, score))

                for track, score in track_scores:
                    log.info(f"track: {track}, score: {score}")
        else:
            log.info("no tracks, adding new track")
            self.tracks.append(new_track)

    def get_tracks(self):
        tracks = []
        for track in self.tracks:
            tracks.append(track.get_track())

        return tracks


class GraphManager:
    def __init__(self, connection_config):
        self.connections = load_yaml(connection_config)
        self.graph = self.create_graph(self.connections)
        self.tracks = None

    def create_graph(self, connections):
        log.info(f"CONNECTIONS: {connections}")
        connection_pairs = []
        for connection in connections["connections"]:
            for start, end in connection.items():
                connection_pairs.append((start, end))

        log.info(f"connection_pairs: {connection_pairs}")
        graph = nx.Graph()
        graph.add_edges_from(connection_pairs)
        return graph

    def visualize_graph(self, output_file="graph.png"):
        log.info(f"graph: {self.graph}")
        if self.graph is not None:
            self._visualize_graph(self.graph, self.tracks, filename=output_file)
        else:
            log.info("No graph to visualize")

    # Function to visualize the graph
    def _visualize_graph(self, graph, tracks=None, filename="graph.png"):
        pos = nx.kamada_kawai_layout(graph)  # Adjust layout if needed
        # colors = [
        #     "cyan" if area_info[node]["state"] == "occupied" else "green"  # Cyan for occupied areas
        #     for node in graph.nodes
        # ]

        kwargs = {}
        if tracks is not None:
            visit_numbers = {}  # Initialize dictionary for visit order
            for i, track in enumerate(tracks):
                for j, (start, end) in enumerate(track):
                    visit_numbers[start] = i * 10 + j + 1  # Assign unique numbers

            labels = {
                node: f"{node}\n{visit_numbers.get(node, '')}" for node in graph.nodes
            }  # Add numbers to labels
            kwargs["labels"] = labels
            kwargs["with_labels"] = True

        nx.draw(
            graph,
            pos,
            font_color="black",
            arrows=True,
            arrowsize=10,
            node_size=400,
            **kwargs,
        )

        if tracks:
            for track in tracks:
                nx.draw_networkx_edges(graph, pos, edgelist=track, edge_color="cyan")

        plt.axis("off")

        plt.savefig(filename)  # Save the image

    def get_distance(self, area_1, area_2):
        shortest_path_length = nx.shortest_path_length(self.graph, area_1, area_2)
        return shortest_path_length


example_track = [
    ("outside", "living_room"),
    ("living_room", "dining_room"),
    ("dining_room", "kitchen"),
    ("kitchen", "outside"),
]


@service
def plot_graph():
    log.info(f"STARTING")
    graph_manager = GraphManager("./pyscript/connections.yml")
    graph_manager.visualize_graph()


plot_graph()
# Example usage:
# visualize_graph(graph, area_info, filename="house_graph.png")


@service
def test_track_manager():
    track_manager = TrackManager()
    track_manager.add_event("living_room")
    track_manager.add_event("dining_room")
    track_manager.add_event("kitchen")
    track_manager.add_event("outside")
    log.info(track_manager.get_tracks())
