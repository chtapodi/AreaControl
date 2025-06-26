"""Advanced room-level presence tracking.

This module implements a particle filter based multi-person tracking system.
It builds on the existing ``tracker`` module but adds probabilistic motion
tracking for sparse sensor data.
"""

from __future__ import annotations

import time
import random
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import json
import os
import yaml
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.lines as mlines

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
    """Models room occupancy based on motion and presence sensors."""

    def __init__(self, cooldown: int = 420, floor_prob: float = 0.05):
        self.cooldown = cooldown
        self.floor_prob = floor_prob
        self.last_fire: Dict[str, float] = defaultdict(lambda: 0.0)
        # ``presence`` stores the last known presence state per room.  ``None``
        # means no presence sensor information is available.
        self.presence: Dict[str, Optional[bool]] = defaultdict(lambda: None)

    def record_trigger(self, room_id: str, timestamp: Optional[float] = None) -> None:
        """Record a motion event for ``room_id``."""
        ts = time.time() if timestamp is None else timestamp
        self.last_fire[room_id] = ts

    def set_presence(self, room_id: str, value: bool, timestamp: Optional[float] = None) -> None:
        """Update explicit presence sensor state for ``room_id``."""
        ts = time.time() if timestamp is None else timestamp
        self.presence[room_id] = value
        if value:
            # Treat presence "on" the same as a motion trigger to reset decay.
            self.last_fire[room_id] = ts

    def likelihood_still_present(self, room_id: str, current_time: Optional[float] = None) -> float:
        """Return probability that someone remains in ``room_id``."""
        presence_state = self.presence.get(room_id)
        if presence_state is True:
            return 1.0
        if presence_state is False:
            return 0.0

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
        """Advance the particle filter by one timestep."""

        move_particles = True
        if sensor_room is not None:
            self.last_sensor_room = sensor_room
            self.last_sensor_time = current_time
            self.sensor_model.record_trigger(sensor_room, current_time)
            for p in self.particles:
                p.room = sensor_room
            move_particles = False
        else:
            if (
                self.last_sensor_room is not None
                and current_time - self.last_sensor_time < self.sensor_model.cooldown
            ):
                move_particles = False

        for p in self.particles:
            if move_particles:
                p.move(self.room_graph)
            weight = self.sensor_model.likelihood_still_present(p.room, current_time)
            if self.last_sensor_room and p.room == self.last_sensor_room:
                weight *= 2.0
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
        debug: bool = False,
        debug_dir: str = "debug",
        event_window: int = 300,
        debug_interval: float = 5.0,
        test_name: Optional[str] = None,
    ):
        self.room_graph = room_graph
        self.sensor_model = sensor_model
        self.people: Dict[str, Person] = {}
        self.phones: Dict[str, Phone] = {}
        self.trackers: Dict[str, PersonTracker] = {}
        self.debug = debug
        self.event_window = event_window
        self.test_name = test_name
        if self.debug and self.test_name:
            self.debug_dir = os.path.join(debug_dir, "tests", self.test_name)
        else:
            self.debug_dir = debug_dir
        self._debug_counter = 0
        self.debug_interval = debug_interval
        self._last_plot_time: float = float("-inf")
        self._updated_since_plot: bool = False
        self._highlight_room: Optional[str] = None
        self._event_history: List[str] = []
        self._estimate_history: Dict[str, List[Tuple[float, str]]] = defaultdict(list)
        self._last_legend_lines: List[str] = []
        if self.debug:
            os.makedirs(self.debug_dir, exist_ok=True)
            self._layout = nx.kamada_kawai_layout(self.room_graph.graph)

    def set_highlight_room(self, room_id: Optional[str]) -> None:
        """Set the room for probability highlighting during visualization."""
        self._highlight_room = room_id

    def _format_highlight_probabilities(self) -> Optional[str]:
        """Return formatted probability list for the highlighted room."""
        if not self._highlight_room:
            return None
        now = time.time()
        entries = []
        for pid, tracker in self.trackers.items():
            if tracker.last_sensor_room == self._highlight_room:
                prob = self.sensor_model.likelihood_still_present(
                    self._highlight_room, current_time=now
                )
            else:
                prob = 0.0
            entries.append((prob, pid))
        entries.sort(reverse=True)
        lines = [f"{pid}: {int(prob * 100 + 0.5)}%" for prob, pid in entries]
        return "\n".join(lines)

    def _maybe_visualize(self, current_time: float) -> None:
        """Render a debug frame if enough time has passed and there was an update."""
        if not self.debug:
            return
        if not self._updated_since_plot:
            return
        if current_time - self._last_plot_time < self.debug_interval:
            return
        self._visualize(current_time)
        self._last_plot_time = current_time
        self._updated_since_plot = False

    def process_event(self, person_id: str, room_id: str, timestamp: Optional[float] = None) -> None:
        now = time.time() if timestamp is None else timestamp
        self._event_history.append(f"{now} {person_id} {room_id}")
        cutoff = now - self.event_window
        self._event_history = [e for e in self._event_history if float(e.split()[0]) >= cutoff]
        person = self.people.get(person_id)
        if person is None:
            tracker = PersonTracker(self.room_graph, self.sensor_model)
            person = Person(person_id, tracker)
            self.people[person_id] = person
            self.trackers[person_id] = tracker
        tracker = person.tracker
        tracker.update(now, sensor_room=room_id)
        self._updated_since_plot = True
        self._maybe_visualize(now)

    def step(self, timestamp: Optional[float] = None) -> None:
        """Advance all trackers and maybe render a debug frame."""
        now = time.time() if timestamp is None else timestamp
        for person in self.people.values():
            person.tracker.update(now)
        self._updated_since_plot = True
        self._maybe_visualize(now)

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

    def process_phone_data(self, phone_id: str, room_id: str, timestamp: Optional[float] = None) -> None:
        """Record phone location and update the associated person's tracker."""
        phone = self.add_phone(phone_id)
        now = time.time() if timestamp is None else timestamp
        phone.last_room = room_id
        phone.last_seen = now
        if phone.person_id:
            self.process_event(phone.person_id, room_id, timestamp=now)

    def record_presence(self, room_id: str, is_present: bool, timestamp: Optional[float] = None) -> None:
        """Update presence sensor state and refresh all trackers."""
        now = time.time() if timestamp is None else timestamp
        self.sensor_model.set_presence(room_id, is_present, now)
        for person in self.people.values():
            person.tracker.update(now)
        self._updated_since_plot = True
        self._maybe_visualize(now)

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
        fig, ax = plt.subplots(figsize=(6, 4))
        nx.draw_networkx(
            self.room_graph.graph,
            pos=self._layout,
            ax=ax,
            node_color="lightgray",
            edgecolors="black",
        )

        cmap = matplotlib.cm.get_cmap("tab10")
        legend_handles = []
        for idx, (pid, person) in enumerate(self.people.items()):
            dist = person.tracker.distribution()
            node_colors = []
            for node in self.room_graph.graph.nodes:
                intensity = dist.get(node, 0.0)
                base_color = cmap(idx % cmap.N)[:3]
                node_colors.append(tuple(intensity * c for c in base_color))
            nx.draw_networkx_nodes(
                self.room_graph.graph,
                pos=self._layout,
                nodelist=list(self.room_graph.graph.nodes),
                node_color=node_colors,
                node_size=400,
                ax=ax,
            )

            est_room = person.tracker.estimate()
            self._estimate_history[pid].append((current_time, est_room))
            cutoff = current_time - self.event_window
            self._estimate_history[pid] = [
                (t, r) for t, r in self._estimate_history[pid] if t >= cutoff
            ]
            est_points = [self._layout[r] for _, r in self._estimate_history[pid]]
            if len(est_points) >= 2:
                ax.plot(
                    [p[0] for p in est_points],
                    [p[1] for p in est_points],
                    color=cmap(idx % cmap.N),
                )

            ev_points = []
            for entry in self._event_history:
                ts, pid_e, room_e = entry.split()
                if pid_e == pid and float(ts) >= cutoff:
                    ev_points.append(self._layout[room_e])
            if len(ev_points) >= 2:
                ax.plot(
                    [p[0] for p in ev_points],
                    [p[1] for p in ev_points],
                    color="orange",
                    linestyle="--",
                )

            max_prob = max(dist.values()) if dist else 0.0
            legend_handles.append(
                mlines.Line2D(
                    [],
                    [],
                    color=cmap(idx % cmap.N),
                    label=f"{pid}: {int(max_prob * 100 + 0.5)}%",
                )
            )

        legend_handles.append(
            mlines.Line2D([], [], color="black", label="solid line: estimated path")
        )
        legend_handles.append(
            mlines.Line2D(
                [], [], color="orange", linestyle="--", label="dashed orange: true path (tests only)"
            )
        )
        ax.legend(handles=legend_handles, loc="upper left", fontsize=8)
        self._last_legend_lines = [h.get_label() for h in legend_handles]

        ax.set_title(f"t={current_time:.1f}")
        ax.axis("off")

        highlight_text = self._format_highlight_probabilities()
        if highlight_text:
            fig.text(
                0.98,
                0.02,
                highlight_text,
                ha="right",
                va="bottom",
                fontsize=8,
            )
        filename = os.path.join(self.debug_dir, f"frame_{self._debug_counter:06d}.png")
        plt.savefig(filename)
        plt.close(fig)
        self._debug_counter += 1


def init_from_yaml(
    connections_path: str,
    *,
    debug: bool = False,
    debug_dir: str = "debug",
    event_window: int = 300,
    debug_interval: float = 5.0,
    test_name: Optional[str] = None,
) -> MultiPersonTracker:
    graph = load_room_graph_from_yaml(connections_path)
    sensor_model = SensorModel()
    return MultiPersonTracker(
        graph,
        sensor_model,
        debug=debug,
        debug_dir=debug_dir,
        event_window=event_window,
        debug_interval=debug_interval,
        test_name=test_name,
    )

