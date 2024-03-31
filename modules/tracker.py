import yaml
import networkx as nx
import matplotlib.pyplot as plt
import time
import copy



@pyscript_compile
def load_yaml(path):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data


def are_events_same(event1, event2):
    return event1.get_area() == event2.get_area()


class Event:
    def __init__(self, area, inpulse=True):
        """
        Creates a new event starting at now.
        An Event is an impulse if there is no status on ongoing presence.
        This event can continued to be updated with presence until it is triggerd absence.

        Design philosophy should attempt to keep it so one event only is updated until a new area is triggered.  

        Parameters:
            area (str): The area associated with the event.
            inpulse (bool, optional): Determines if the Event is ongoing or not.
        """
        self.first_presence_time=time.time()
        self.area = area
        self.last_rising_edge_time=self.first_presence_time
        if not inpulse:
            self.last_falling_edge_time=self.first_presence_time
        else :
            self.last_falling_edge_time=None

    def get_presence(self) :
        return self.last_falling_edge_time is not None

    def get_area(self):
        return self.area

    def get_duration(self):
        if self.last_falling_edge_time is not None:
            return self.last_falling_edge_time - self.first_presence_time
        elif self.last_rising_edge_time != self.first_presence_time: # If there have been multiple impulses, return difference
            return self.last_rising_edge_time - self.first_presence_time 
        else : # If only one impulse, duration is 0
            return 0

    def get_time_since_first_trigger(self) :
        return time.time() - self.first_presence_time

    def get_time_since_last_trigger(self) :
        if self.last_falling_edge_time is not None:
            return time.time() - self.last_falling_edge_time
        else :
            return time.time() - self.last_rising_edge_time

    def presence(self) :
        # Triggering continuing presence.
        self.last_rising_edge_time=time.time()
        self.last_falling_edge_time=None

    def impulse(self) :
        # Triggering new presence impulse
        self.last_rising_edge_time=time.time()

    def absence(self) :
        # Triggering ending presence
        self.last_falling_edge_time=time.time()

    def end(self, end_timestamp=None) :
        log.info("ENDING")
        if end_timestamp is not None:
            self.last_falling_edge_time=end_timestamp
        else :
            self.absence()

    def get_pretty_string(self):
        duration=self.get_duration()
        if duration is not None:
            return str(f"{self.area}({duration:.3f})")
        else :
            return str(f"{self.area}")

    def get_copy(self) :
        copy=Event(self.area)
        copy.first_presence_time=self.first_presence_time
        copy.last_rising_edge_time=self.last_rising_edge_time
        copy.last_falling_edge_time=self.last_falling_edge_time
        return copy

    def get_first_presence_time(self) :
        return self.first_presence_time


class Track:
    """
    A track can only exist if there is at least one event.
    if there is only one event, duration is time since trigger

    """

    def __init__(self, max_length=5):
        self.event_list = []  # First event
        self.max_length = max_length
        self.last_event_time = time.time()
        self.first_event_time=self.last_event_time

    def add_event(self, area, impulse=True):
        self.last_event_time = time.time()
        if len(self.event_list) == 0:
            self.event_list.append(Event(area))
        else :
            if self.get_head().get_area() == area:
                log.info(f"TrackManager: add event: {area} - already head")
                if impulse: self.get_head().impulse()
                else : self.get_head().presence()
            else :
                track = self.get_track_list()
                new_event=Event(area)
                self.get_head().end() #end last Event
                # add new event to track start
                track.insert(0, new_event)
                log.info(f"new track: {track}")
                self.event_list = track

        log.info(f"NEW EVENT ADDED {self.get_pretty_string()}")

    def merge_tracks(self, track_to_merge):
        """
        Merges the given track to merge with the current track.

        Parameters:
            track_to_merge (list): The track to merge with the current track.


        Description:
        This function merges the given track to merge with the current track. It creates a new event list and initializes it with the first event of the current track. Then, it iterates through the events of the track to merge and inserts them into the new event list based on their time since the last trigger.

        Note:
        - Assumes that tracks and their events are monotonic
        """
        
        log.info("Let us merge")
        new_event_list=[]
        current_track=self.get_copy()
        log.info(f"Current track: {current_track}")
        # current_track=copy.deepcopy(current_track) #deepcopy not working

        log.info(f"merging {track_to_merge.get_pretty_string()} with {self.get_pretty_string()}")

        track_to_merge_event_list=track_to_merge.get_copy()

        if self.get_last_event_time() < track_to_merge.get_first_presence_time():
            # If entire current track is older than entire new track, can just add new track to end of current track
            for event in track_to_merge.get_track_list():
                if (self.event_list[0].get_duration() == 0) : 
                    self.event_list[0].end(event.get_first_presence_time())
                self.event_list.insert(0,event)

            self.last_event_time=track_to_merge.get_last_event_time()

        else :

            # Start the new track with the first event
            event_to_add=None
            if track_to_merge[0].get_time_since_last_trigger() < current_track[0].get_time_since_last_trigger():
                event_to_add=track_to_merge.pop(0)
            else :
                event_to_add=current_track.pop(0)

            if (new_event_list[0].get_duration() == 0) : 
                new_event_list[0].end(event_to_add.get_first_presence_time())


            new_event_list.append(event_to_add)

            # Add the rest of the events in order of them happening
            while len(current_track) > 0:

                while len(track_to_merge) > 0:

                    if track_to_merge[0].get_time_since_last_trigger() < current_track[0].get_time_since_last_trigger():
                        new_event_list[0].end(track_to_merge[0].get_first_presence_time())
                        new_event_list.append(track_to_merge.pop(0))
                    else :
                        break

                new_event_list.append( current_track.pop(0))

            while len(track_to_merge) > 0:
                new_event_list.append( track_to_merge.pop(0))

            log.info(f"new merged track: {new_event_list}")
            self.event_list=new_event_list


    def get_copy(self) :
        copy=[]
        for event in self.get_track_list():
            copy.append(event.get_copy())
        return copy

    def get_head(self):
        if len(self.get_track_list()) == 0:
            return None
        return self.get_track_list()[0]

    def get_track_list(self):

        return self.event_list

    def _trim(self):
        log.info(f"trimming track: {self.event_list} to {self.max_length}")
        if len(self.event_list) > self.max_length:
            self.event_list = self.event_list[:self.max_length]
            log.info(f"trimmed track: {self.event_list}")

    def get_duration(self):
        start=self.get_first_event().get_time_since_first_trigger()
        end=self.get_last_event().get_time_since_last_trigger()


    def get_first_event(self) :
        return self.get_track_list()[-1]

    def get_last_event_time(self) :
        return self.last_event_time

    def get_first_presence_time(self) :
        return self.first_event_time

    def get_last_event(self) :
        return self.get_track_list()[0] 


    def get_area(self):
        """
        Returns the area of the head of the object if it exists, otherwise returns None.

        :return: The area of the head of the object, or None if the head does not exist.
        :rtype: int or None
        """
        head=self.get_head()
        if head is None: return None
        return head.get_area()

    def get_previous_event(self, offset=1) :
        """
        Get the previous event from the track list.
        Parameters:
            offset (int): The offset from the current event index. Defaults to 1.
        Returns:
            Any: The previous event from the track list, or None if the track list is empty.
        """
        if len(self.get_track_list()) <= offset:
            return None
        return self.get_track_list()[offset]

    def get_pretty_string(self):
        string="⚬"
        track=self.get_track_list()
        for i, event in enumerate(track):
            string+=f"{event.get_pretty_string()}"
            if i < len(track)-1:
                string+=" <- "
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
            new_track = Track()
            new_track.add_event(area)
            self.try_associate_track(new_track)
            self.cleanup_tracks()
            self.output_stats()
        else :
            log.info(f"TrackManager: add event: {area} - not in graph")

    def output_stats(self) :
        track_data=""
        head_data=""
        head_names=[]
        for track in self.tracks:
            if len(track_data)<250 : # max string length for HA state
                track_data+=track.get_pretty_string()+"\n"

            head_data+=track.get_head().get_pretty_string()+"\n"
            head_names.append(track.get_head().get_area())
        log.info(f"track_data: {track_data}")
        state.set("pyscript.last_heads", head_data[:254])
        state.set("pyscript.last_tracks", track_data[:254])

        self.graph_manager.visualize_graph(head_names)


    def cleanup_tracks(self):
        for track in self.tracks:
            # remove tracks that have not been updated in too long
            if time.time() - track.last_event_time > self.oldest_track:
                self.tracks.remove(track)
            
            # trim tracks that have too many events
            if len(track.get_track_list()) > self.max_track_length:
                track._trim()

        if len(self.tracks) > self.max_tracks:
            log.warning(f"trimming tracks: {self.tracks}")
            self.tracks = self.tracks[-self.max_tracks :]


    def try_associate_track(self, new_track):
        log.info(
            f"trying to associate track: {new_track.get_track_list()} with {self.get_tracks()}"
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
                log.info(f"Merging {best_track.get_track_list()}")
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
            tracks.append(track.get_track_list())

        return tracks

    def get_pretty_string(self):
        track_string=""
        for track in self.tracks:
            track_string+=track.get_pretty_string()+"\n"

        return track_string


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

    def visualize_graph(self, areas_to_highlight=None, output_file="pyscript/graph2.png"):
        log.info(f"graph: {self.graph}")
        if self.graph is not None:
            self._visualize_graph(self.graph, areas_to_highlight, filename=output_file)
        else:
            log.info("No graph to visualize")

    def is_area_in_graph(self, area):
        if area in self.graph.nodes:
            return True
        return False


    # Function to visualize the graph
    #TODO: Make it so the graph is labeled with the names of the nodes
    def _visualize_graph(self, graph, areas_to_highlight=None, filename="pyscript/graph2.png", **kwargs,):
        pos = nx.kamada_kawai_layout(graph, scale=50)

        colors = []
        for node in graph.nodes:
            if areas_to_highlight is not None and node in areas_to_highlight:
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
