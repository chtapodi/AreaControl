"""Advanced room-level presence tracking.

This module implements a particle filter based multi-person tracking system.
It builds on the existing ``tracker`` module but adds probabilistic motion
tracking for sparse sensor data.
"""

from __future__ import annotations

import time
import random
from collections import defaultdict
from typing import Dict, List, Optional
import os
import json
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import networkx as nx


class RoomGraph:
    """Graph describing connectivity between rooms."""

    def __init__(self, adjacency: Dict[str, List[str]]):
        self.graph = nx.Graph()
        for room, neighbours in adjacency.items():
            for n in neighbours:
                self.graph.add_edge(room, n)

    def get_neighbors(self, room_id: str) -> List[str]:
        return list(self.graph.neighbors(room_id))


def load_room_graph_from_yaml(path: str) -> RoomGraph:
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    adjacency: Dict[str, List[str]] = defaultdict(list)
    for pair in data.get("connections", []):
        for a, b in pair.items():
            adjacency[a].append(b)
            adjacency[b].append(a)
    return RoomGraph(adjacency)


class SensorModel:
    """Models likelihood that a person remains in a room."""

    def __init__(self, cooldown: int = 420, floor_prob: float = 0.05):
        self.cooldown = cooldown
        self.floor_prob = floor_prob
        self.last_fire: Dict[str, float] = defaultdict(lambda: 0.0)

    def record_trigger(self, room_id: str, timestamp: Optional[float] = None) -> None:
        self.last_fire[room_id] = time.time() if timestamp is None else timestamp

    def likelihood_still_present(self, room_id: str, current_time: Optional[float] = None) -> float:
        now = time.time() if current_time is None else current_time
        dt = now - self.last_fire.get(room_id, 0.0)
        if dt <= 0:
            return 1.0
        if dt >= self.cooldown:
            return self.floor_prob
        return 1.0 - (dt / self.cooldown) * (1.0 - self.floor_prob)


class Particle:
    def __init__(self, room: str, weight: float = 1.0):
        self.room = room
        self.weight = weight

    def move(self, room_graph: RoomGraph) -> None:
        neighbors = room_graph.get_neighbors(self.room)
        if neighbors:
            self.room = random.choice(neighbors)

    def copy(self) -> "Particle":
        return Particle(self.room, self.weight)


class PersonTracker:
    """Particle filter tracker for a single person."""

    def __init__(self, room_graph: RoomGraph, sensor_model: SensorModel, num_particles: int = 100):
        self.room_graph = room_graph
        self.sensor_model = sensor_model
        self.particles: List[Particle] = []
        self.last_sensor_room: Optional[str] = None
        self.last_sensor_time: float = 0.0
        self._init_particles(num_particles)

    def _init_particles(self, n: int) -> None:
        rooms = list(self.room_graph.graph.nodes)
        for _ in range(n):
            room = random.choice(rooms)
            self.particles.append(Particle(room))

    def update(self, current_time: float, sensor_room: Optional[str] = None) -> None:
        if sensor_room is not None:
            self.last_sensor_room = sensor_room
            self.last_sensor_time = current_time
            self.sensor_model.record_trigger(sensor_room, current_time)

        for p in self.particles:
            p.move(self.room_graph)
            weight = self.sensor_model.likelihood_still_present(p.room, current_time)
            if self.last_sensor_room and p.room == self.last_sensor_room:
                weight *= 1.5
            p.weight = weight

        # Resample
        total = sum(p.weight for p in self.particles)
        if total == 0:
            total = 1.0
        cumulative = []
        acc = 0.0
        for p in self.particles:
            acc += p.weight / total
            cumulative.append(acc)
        new_particles = []
        for _ in self.particles:
            r = random.random()
            for i, c in enumerate(cumulative):
                if r <= c:
                    new_particles.append(Particle(self.particles[i].room))
                    break
        self.particles = new_particles

    def estimate(self) -> str:
        counts: Dict[str, int] = defaultdict(int)
        for p in self.particles:
            counts[p.room] += 1
        if not counts:
            return "unknown"
        return max(counts.items(), key=lambda x: x[1])[0]

    def distribution(self) -> Dict[str, float]:
        counts: Dict[str, int] = defaultdict(int)
        for p in self.particles:
            counts[p.room] += 1
        total = len(self.particles)
        if total == 0:
            return {}
        return {room: count / total for room, count in counts.items()}


class Phone:
    """Represents a mobile phone with sensor data."""

    def __init__(self, phone_id: str):
        self.id = phone_id
        self.location: Optional[str] = None
        self.activity: Optional[str] = None
        self.last_update: float = 0.0
        self.person: Optional["Person"] = None

    def update(self, *, location: Optional[str] = None, activity: Optional[str] = None, timestamp: Optional[float] = None) -> None:
        if location is not None:
            self.location = location
        if activity is not None:
            self.activity = activity
        self.last_update = time.time() if timestamp is None else timestamp


class Person:
    """Wraps a ``PersonTracker`` and optional phone association."""

    def __init__(self, person_id: str, tracker: PersonTracker, *, name: Optional[str] = None, generic: bool = False):
        self.id = person_id
        self.name = name
        self.tracker = tracker
        self.phone: Optional[Phone] = None
        self.generic = generic

    def associate_phone(self, phone: Phone) -> None:
        self.phone = phone
        phone.person = self

    def update(self, current_time: float, sensor_room: Optional[str] = None) -> None:
        room = sensor_room
        if room is None and self.phone and self.phone.location is not None:
            room = self.phone.location
        self.tracker.update(current_time, sensor_room=room)

    def estimate(self) -> str:
        return self.tracker.estimate()


class MultiPersonTracker:
    """Manage a set of :class:`PersonTracker` instances.

    When ``debug`` is enabled a PNG frame and matching JSON state dump are
    written for every call to :meth:`process_event` and :meth:`step`.  Files are
    saved in ``debug_dir`` with names ``frame_XXXXXX.png`` and
    ``state_XXXXXX.json`` where ``XXXXXX`` is a monotonically increasing
    counter.  The JSON structure looks like::

        {
            "estimates": {"p1": "bedroom"},
            "distributions": {
                "p1": {"bedroom": 0.8, "hallway": 0.2}
            }
        }

    ``dump_state()`` can be called manually to write the same information to a
    custom path.
    """

    def __init__(
        self,
        room_graph: RoomGraph,
        sensor_model: SensorModel,
        *,
        debug: bool = False,
        debug_dir: str = "debug",
        log_interval: float = 60.0,
        log_retention: int = 1000,
        image_size: tuple = (6, 4),
    ):
        self.room_graph = room_graph
        self.sensor_model = sensor_model
        self.people: Dict[str, Person] = {}
        self.phones: Dict[str, Phone] = {}
        self._generic_counter = 0
        self.debug = debug
        self.debug_dir = debug_dir
        self.log_interval = log_interval
        self.log_retention = log_retention
        self.image_size = image_size
        self._debug_counter = 0
        self._last_log_time = 0.0
        if self.debug:
            os.makedirs(self.debug_dir, exist_ok=True)
            self._layout = nx.kamada_kawai_layout(self.room_graph.graph)

    @property
    def trackers(self) -> Dict[str, PersonTracker]:
        """Backwards compatibility shim returning underlying trackers."""
        return {pid: person.tracker for pid, person in self.people.items()}

    def _get_or_create_person(self, person_id: str, *, generic: bool = False) -> Person:
        person = self.people.get(person_id)
        if person is None:
            tracker = PersonTracker(self.room_graph, self.sensor_model)
            person = Person(person_id, tracker, generic=generic)
            self.people[person_id] = person
        return person

    def create_generic_person(self) -> Person:
        pid = f"unknown_{self._generic_counter}"
        self._generic_counter += 1
        return self._get_or_create_person(pid, generic=True)

    def add_phone(self, phone_id: str) -> Phone:
        phone = self.phones.get(phone_id)
        if phone is None:
            phone = Phone(phone_id)
            self.phones[phone_id] = phone
        return phone

    def associate_phone(self, person_id: str, phone_id: str) -> None:
        phone = self.add_phone(phone_id)
        person = self._get_or_create_person(person_id)
        person.associate_phone(phone)

    def process_phone_data(self, phone_id: str, *, location: Optional[str] = None, activity: Optional[str] = None, timestamp: Optional[float] = None) -> None:
        phone = self.add_phone(phone_id)
        phone.update(location=location, activity=activity, timestamp=timestamp)
        if phone.person is not None:
            phone.person.update(phone.last_update, sensor_room=location)

    def process_event(self, person_id: Optional[str], room_id: str, timestamp: Optional[float] = None) -> None:
        now = time.time() if timestamp is None else timestamp
        if person_id is None:
            person = self.create_generic_person()
        else:
            person = self._get_or_create_person(person_id)
        person.update(now, sensor_room=room_id)
        if self.debug:
            self._visualize(now)

    def step(self) -> None:
        now = time.time()
        for person in self.people.values():
            person.update(now)
        if self.debug:
            self._visualize(now)

    def estimate_locations(self) -> Dict[str, str]:
        return {pid: person.estimate() for pid, person in self.people.items()}

    def dump_state(self, filename: str) -> None:
        """Write current estimates and distributions to ``filename`` as JSON."""
        state = {
            "estimates": self.estimate_locations(),
            "distributions": {pid: tracker.distribution() for pid, tracker in self.trackers.items()},
        }
        with open(filename, "w") as f:
            json.dump(state, f)

    def _visualize(self, current_time: float) -> None:
        if current_time - self._last_log_time < self.log_interval:
            return
        self._last_log_time = current_time

        # Remove old frames if exceeding retention limit
        old_idx = self._debug_counter - self.log_retention
        if old_idx >= 0:
            old_frame = os.path.join(self.debug_dir, f"frame_{old_idx:06d}.png")
            old_state = os.path.join(self.debug_dir, f"state_{old_idx:06d}.json")
            if os.path.exists(old_frame):
                os.remove(old_frame)
            if os.path.exists(old_state):
                os.remove(old_state)

        plt.clf()
        fig, ax = plt.subplots(figsize=self.image_size)
        nx.draw_networkx(self.room_graph.graph, pos=self._layout, ax=ax, node_color='lightgray', edgecolors='black')

        colors = {
            0: (1, 0, 0),
            1: (0, 1, 0),
            2: (0, 0, 1),
        }
        for idx, (pid, person) in enumerate(self.people.items()):
            dist = person.tracker.distribution()
            node_colors = []
            for node in self.room_graph.graph.nodes:
                intensity = dist.get(node, 0.0)
                base = colors.get(idx % 3, (0, 0, 0))
                node_colors.append(tuple(intensity * c for c in base))
            nx.draw_networkx_nodes(
                self.room_graph.graph,
                pos=self._layout,
                nodelist=list(self.room_graph.graph.nodes),
                node_color=node_colors,
                node_size=400,
                ax=ax,
            )
        ax.set_title(f"t={current_time:.1f}")
        ax.axis('off')
        frame_file = os.path.join(self.debug_dir, f"frame_{self._debug_counter:06d}.png")
        state_file = os.path.join(self.debug_dir, f"state_{self._debug_counter:06d}.json")
        plt.savefig(frame_file, dpi=80, bbox_inches="tight")
        plt.close(fig)
        self.dump_state(state_file)
        self._debug_counter += 1


def init_from_yaml(
    connections_path: str,
    *,
    debug: bool = False,
    debug_dir: str = "debug",
    log_interval: float = 60.0,
    log_retention: int = 1000,
    image_size: tuple = (6, 4),
) -> MultiPersonTracker:
    graph = load_room_graph_from_yaml(connections_path)
    sensor_model = SensorModel()
    return MultiPersonTracker(
        graph,
        sensor_model,
        debug=debug,
        debug_dir=debug_dir,
        log_interval=log_interval,
        log_retention=log_retention,
        image_size=image_size,
    )

