"""Advanced room-level presence tracking.

This module implements a particle filter based multi-person tracking system.
It builds on the existing ``tracker`` module but adds probabilistic motion
tracking for sparse sensor data.
"""

from __future__ import annotations

import time
import random
import datetime
from collections import defaultdict
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import json
import os
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

    def likelihood_still_present(
        self, room_id: str, current_time: Optional[float] = None
    ) -> float:
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

    def __init__(
        self, room_graph: RoomGraph, sensor_model: SensorModel, num_particles: int = 100
    ):
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


@dataclass
class Phone:
    """Represents a mobile device providing location hints."""

    id: str
    last_room: Optional[str] = None
    last_seen: float = 0.0
    person_id: Optional[str] = None


@dataclass
class Person:
    """Wrapper around ``PersonTracker`` with phone associations."""

    id: str
    tracker: PersonTracker
    phones: List[str] = field(default_factory=list)


class MultiPersonTracker:
    def __init__(
        self,
        room_graph: RoomGraph,
        sensor_model: SensorModel,
        *,
        debug: bool = True,
        debug_dir: str = "debug",
        event_window: int = 600,
        test_name: Optional[str] = None,
    ):
        self.room_graph = room_graph
        self.sensor_model = sensor_model
        self.people: Dict[str, Person] = {}
        self.phones: Dict[str, Phone] = {}
        self.trackers: Dict[str, PersonTracker] = {}
        self.debug = debug
        self.debug_dir = debug_dir
        self.event_window = event_window
        self.test_name = test_name
        self._debug_counter = 0
        self._current_event_dir: Optional[str] = None
        self._last_event_time: float = 0.0
        self._event_history: List[str] = []
        self._highlight_room: Optional[str] = None
        self._estimate_paths: Dict[str, List[str]] = defaultdict(list)
        self._true_paths: Dict[str, List[str]] = defaultdict(list)
        if self.debug:
            os.makedirs(self.debug_dir, exist_ok=True)
            # Use a deterministic spring layout with spacing based on graph size
            # so plots remain consistent across runs.
            num_nodes = len(self.room_graph.graph.nodes)
            k = 2.0 / (num_nodes**0.5) if num_nodes else 0.5
            self._layout = nx.spring_layout(
                self.room_graph.graph,
                seed=42,
                k=k,
                scale=2.0,
                iterations=100,
            )

    def _start_event(self, timestamp: float) -> None:
        """Create a new directory for debug frames for a sensor event."""
        date_dir = datetime.datetime.fromtimestamp(timestamp).strftime("%Y/%m/%d")
        if self.test_name:
            path = os.path.join(self.debug_dir, date_dir, "tests", self.test_name)
        else:
            event_dir = datetime.datetime.fromtimestamp(timestamp).strftime("%H%M%S")
            path = os.path.join(self.debug_dir, date_dir, event_dir)
        os.makedirs(path, exist_ok=True)
        self._current_event_dir = path
        self._last_event_time = timestamp
        self._debug_counter = 0
        self._event_history = []
        self._estimate_paths = defaultdict(list)
        self._true_paths = defaultdict(list)

    def process_event(
        self, person_id: str, room_id: str, timestamp: Optional[float] = None
    ) -> None:
        now = time.time() if timestamp is None else timestamp
        person = self.people.get(person_id)
        if person is None:
            tracker = PersonTracker(self.room_graph, self.sensor_model)
            person = Person(person_id, tracker)
            self.people[person_id] = person
            self.trackers[person_id] = tracker
        tracker = person.tracker
        if self.debug:
            if (
                self._current_event_dir is None
                or now - self._last_event_time > self.event_window
            ):
                self._start_event(now)
        tracker.update(now, sensor_room=room_id)
        if self.debug:
            estimate = tracker.estimate()
            self._estimate_paths[person_id].append(estimate)
            self._true_paths[person_id].append(room_id)
            self._highlight_room = room_id
            self._event_history.append(
                f"{now:.1f}s: motion {room_id} fired, est={estimate}"
            )
            self._visualize(now)
            self._highlight_room = None

    def step(self) -> None:
        now = time.time()
        for pid, person in self.people.items():
            person.tracker.update(now)
            if self.debug:
                self._estimate_paths[pid].append(person.tracker.estimate())
        if self.debug:
            if (
                self._current_event_dir is None
                or now - self._last_event_time > self.event_window
            ):
                self._start_event(now)
            self._visualize(now)

    def estimate_locations(self) -> Dict[str, str]:
        return {pid: person.tracker.estimate() for pid, person in self.people.items()}

    def add_phone(self, phone_id: str) -> Phone:
        """Create a phone entry if needed and return it."""
        phone = self.phones.get(phone_id)
        if phone is None:
            phone = Phone(phone_id)
            self.phones[phone_id] = phone
        return phone

    def associate_phone(self, phone_id: str, person_id: str) -> None:
        """Associate ``phone_id`` with ``person_id`` creating objects as needed."""
        phone = self.add_phone(phone_id)
        person = self.people.get(person_id)
        if person is None:
            tracker = PersonTracker(self.room_graph, self.sensor_model)
            person = Person(person_id, tracker)
            self.people[person_id] = person
            self.trackers[person_id] = tracker
        if phone_id not in person.phones:
            person.phones.append(phone_id)
        phone.person_id = person_id

    def process_phone_data(
        self, phone_id: str, room_id: str, timestamp: Optional[float] = None
    ) -> None:
        """Record phone location and update the associated person's tracker."""
        phone = self.add_phone(phone_id)
        now = time.time() if timestamp is None else timestamp
        phone.last_room = room_id
        phone.last_seen = now
        if phone.person_id:
            self.process_event(phone.person_id, room_id, timestamp=now)

    def dump_state(self) -> str:
        """Return a JSON representation of current tracker state."""
        data = {
            "people": {
                pid: {
                    "estimate": person.tracker.estimate(),
                    "phones": list(person.phones),
                }
                for pid, person in self.people.items()
            },
            "phones": {
                phid: {
                    "person": phone.person_id,
                    "last_room": phone.last_room,
                    "last_seen": phone.last_seen,
                }
                for phid, phone in self.phones.items()
            },
        }
        return json.dumps(data)

    def _visualize(self, current_time: float) -> None:
        plt.clf()
        # Bigger figure for improved readability
        fig, ax = plt.subplots(figsize=(16, 10))
        nx.draw_networkx(
            self.room_graph.graph,
            pos=self._layout,
            ax=ax,
            node_color="skyblue",
            edgecolors="black",
            edge_color="gray",
            font_size=9,
            font_color="black",
        )

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
                node_colors.append((*base, intensity))
            nx.draw_networkx_nodes(
                self.room_graph.graph,
                pos=self._layout,
                nodelist=list(self.room_graph.graph.nodes),
                node_color=node_colors,
                node_size=600,
                ax=ax,
            )

            # Draw estimated path arrows
            path = self._estimate_paths.get(pid, [])
            for start, end in zip(path[:-1], path[1:]):
                start_pos = self._layout[start]
                end_pos = self._layout[end]
                ax.annotate(
                    "",
                    xy=end_pos,
                    xytext=start_pos,
                    arrowprops=dict(
                        arrowstyle="->",
                        color=colors.get(idx % 3, (0, 0, 0)),
                        lw=2,
                    ),
                )

            # If we have ground truth for tests, draw it too
            if self.test_name:
                true_path = self._true_paths.get(pid, [])
                for start, end in zip(true_path[:-1], true_path[1:]):
                    start_pos = self._layout[start]
                    end_pos = self._layout[end]
                    ax.annotate(
                        "",
                        xy=end_pos,
                        xytext=start_pos,
                        arrowprops=dict(
                            arrowstyle="->",
                            color="orange",
                            lw=2,
                            linestyle="dashed",
                        ),
                    )
        if self._highlight_room:
            nx.draw_networkx_nodes(
                self.room_graph.graph,
                pos=self._layout,
                nodelist=[self._highlight_room],
                node_color="yellow",
                edgecolors="black",
                linewidths=2,
                node_size=800,
                ax=ax,
            )
        ax.set_title(f"t={current_time:.1f}", fontsize=13)
        ax.axis("off")

        # Debug text overlay
        if self._current_event_dir:
            event_name = os.path.relpath(self._current_event_dir, self.debug_dir)
        else:
            event_name = "no_event"
        fig.suptitle(f"event: {event_name}", y=0.98, fontsize=13)
        for idx, (pid, person) in enumerate(self.people.items()):
            text = f"{pid}: est={person.tracker.estimate()}"
            if person.tracker.last_sensor_room:
                text += f", last={person.tracker.last_sensor_room}"
            fig.text(
                0.01,
                0.92 - idx * 0.04,
                text,
                fontsize=9,
                ha="left",
                va="top",
            )

        # Legend for node colors and alpha
        legend_lines = [
            "Legend:",
            "  Node color: person id (red, green, blue)",
            "  Alpha: probability",
        ]
        for idx, line in enumerate(legend_lines):
            fig.text(
                0.72,
                0.92 - idx * 0.04,
                line,
                fontsize=9,
                ha="left",
                va="top",
            )

        # Event history log
        log_start = 0.92 - len(legend_lines) * 0.04 - 0.04
        fig.text(0.02, log_start, "Event log:", fontsize=9, ha="left", va="top")
        for idx, message in enumerate(self._event_history[-10:]):
            fig.text(
                0.02,
                log_start - (idx + 1) * 0.04,
                message,
                fontsize=9,
                ha="left",
                va="top",
            )

        plt.tight_layout(rect=[0, 0, 1, 0.95])

        target_dir = self._current_event_dir
        filename = os.path.join(target_dir, f"frame_{self._debug_counter:06d}.png")
        plt.savefig(filename)
        plt.close(fig)
        self._debug_counter += 1


def init_from_yaml(
    connections_path: str,
    *,
    debug: bool = False,
    debug_dir: str = "debug",
    test_name: Optional[str] = None,
) -> MultiPersonTracker:
    graph = load_room_graph_from_yaml(connections_path)
    sensor_model = SensorModel()
    return MultiPersonTracker(
        graph,
        sensor_model,
        debug=debug,
        debug_dir=debug_dir,
        test_name=test_name,
    )
