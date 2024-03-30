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

    def merge_tracks(self, track_to_merge):
        current_track_events=self.get_track()
        track_to_merge_events=track_to_merge.get_track()
        current_track_age=0
        track_to_merge_age=0
        total_events = len(current_track_events) + len(track_to_merge_events)
        # iterate over both tracks, and using the last event time, add the events to the current track in order

        new_track=[]
        # iterate over length of total events, adding the newest events first
        for i in range(total_events) :
            current_track_event_age = current_track_age + current_track_events[0][1]
            if len(current_track_events)>0: current_track_event_age+=current_track_events[0][1]
            track_to_merge_event_age = track_to_merge_age
            if len(track_to_merge_events)>0: track_to_merge_event_age+=track_to_merge_events[0][1]

            #FIXME: Durations will get all sorts of messed up if zipping
            if len(track_to_merge_events)>0 and (track_to_merge_event_age+track_to_merge_events[0][1]) < current_track_event_age:
                new_track.append(track_to_merge_events.pop(0))
                track_to_merge_age = track_to_merge_event_age
            elif len(current_track_events)>0 :
                new_track.append(current_track_events.pop(0))
                current_track_age = current_track_event_age

        self.track = new_track
        self.last_event_time = time.time()-self.get_head()[1] # the last event time is now - last event duration


    def get_head(self):
        return self.get_track()[0]

    def get_track(self):
        """
        Return the track with updated duration based on the last event time.
        e.g. Head will have time since last update, other events will have duration
        """
        track = self.track
        head = track[0]
        duration = time.time() - self.last_event_time
        track[0] = (head[0], duration)
        return track

    def _trim(self):
        log.info(f"trimming track: {self.track} to {self.max_length}")
        if len(self.track) > self.max_length:
            self.track = self.track[:self.max_length]
            log.info(f"trimmed track: {self.track}")

    def get_duration(self):
        total = 0
        for event in self.get_track():
            total += event[1]
        return total

    def get_area(self):
        return self.get_head()[0]

    def get_pretty_string(self):
        string=""
        track=self.get_track()
        for i in range(len(track)):
            string+=f"{track[i][0]}"
            if i<len(track)-1: string+=" <- "
        string+=f" ({self.get_duration():.3f}s)"
        return string


class TrackManager:
    def __init__(self, max_track_length=5, oldest_track=30 * 60, max_tracks=10, score_threshold=2.5):
        self.tracks = []
        self.max_track_length = max_track_length
        self.oldest_track = oldest_track
        self.max_tracks = max_tracks
        self.score_threshold = score_threshold # Tracks with score worse than threshold will not be fused
        self.graph_manager = GraphManager("./pyscript/connections.yml")

    def add_event(self, area, person=None):
        if self.graph_manager.is_area_in_graph(area):
            log.info(f"TrackManager: add event: {area}")
            new_track = Track(area)
            self.try_associate_track(new_track)
            self.cleanup_tracks()
            self.output_stats()
        else :
            log.info(f"TrackManager: add event: {area} - not in graph")

    def output_stats(self) :
        heads=[]
        for track in self.tracks:
            heads.append(track.get_head()[0])
        log.info(f"heads: {heads}")
        state.set("pyscript.last_heads", heads)


    def cleanup_tracks(self):
        for track in self.tracks:
            # remove tracks that have not been updated in too long
            if time.time() - track.last_event_time > self.oldest_track:
                self.tracks.remove(track)
            
            # trim tracks that have too many events
            if len(track.get_track()) > self.max_track_length:
                track._trim()

        if len(self.tracks) > self.max_tracks:
            log.warning(f"trimming tracks: {self.tracks}")
            self.tracks = self.tracks[-self.max_tracks :]


    def try_associate_track(self, new_track):
        log.info(
            f"trying to associate track: {new_track.get_track()} with {self.get_tracks()}"
        )
        if len(self.get_tracks() )> 0:
            track_scores = []

            area = new_track.get_area()
            for track in self.tracks:
                score = self.graph_manager.get_distance(track.get_area(), area)
                log.info(f"{track.get_area()}->{area} = {score}")
                track_scores.append((track, score))

            # get track with lowest score
            track, score = min(track_scores, key=lambda x: x[1])
            best_tracks=[]
            best_score=None

            for track, score in track_scores:
                if score < self.score_threshold:
                    if best_score is None or score < best_score:
                        best_tracks=[track]
                        best_score = score
                    elif score == best_score :
                        best_tracks.append(track)

            if len(best_tracks) > 1: #TODO: pick best track based on velocity, COG
                log.warning(f"MULTIPLE best tracks: {best_tracks}")

            if len(best_tracks) > 0:
                best_track=best_tracks[0] 
                log.info(f"Merging {best_track.get_track()}")
                best_track.merge_tracks(new_track)
            else :
                log.info("All tracks out of range, adding new track")
                self.tracks.append(new_track)
        else :
            log.info("First, Adding new track")
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

    def visualize_graph(self, output_file="pyscript/graph2.png"):
        log.info(f"graph: {self.graph}")
        if self.graph is not None:
            self._visualize_graph(self.graph, self.tracks, filename=output_file)
        else:
            log.info("No graph to visualize")

    def is_area_in_graph(self, area):
        if area in self.graph.nodes:
            return True
        return False


    # Function to visualize the graph
    #TODO: Make it so the graph is labeled with the names of the nodes
    def _visualize_graph(self, graph, tracks=None, filename="pyscript/graph2.png", **kwargs,):
        pos = nx.kamada_kawai_layout(graph, scale=50)

        colors = []
        for node in graph.nodes:
            if node=="hallway":
                colors.append("cyan")
            else:
                colors.append("white")


        options = {
            "font_size": 8,
            "node_size": 500,
            "node_color": colors,
            "edgecolors": "black",
            "linewidths": 2,
            "width": 1,
            "with_labels":True,
        }
        nx.draw_networkx(graph, pos, **options)

        plt.axis("off")
        log.info(f"Saving graph to {filename}")
        plt.savefig(filename)  # Save the image
        plt.clf()
        plt.close()
        

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


# @service
# def test_track_manager():
#     track_manager = TrackManager()
#     track_manager.add_event("laundry_room")
#     track_manager.add_event("kitchen")
#     track_manager.add_event("dining_room")
#     track_manager.add_event("office")
#     track_manager.add_event("hallway")
#     track_manager.add_event("outside")
#     log.info("Getting tracks")
#     log.info(track_manager.get_tracks())
#     for track in track_manager.tracks:
#         log.info(f"Track: {track.get_pretty_string()}")
