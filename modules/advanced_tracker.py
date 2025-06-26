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
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import json
import os
import yaml
import matplotlib

matplotlib.use("Agg")

# Default delay between saved debug frames. A larger value keeps the number
# of generated images manageable during long test scenarios.
DEFAULT_MIN_PLOT_TIME = 30.0
import matplotlib.pyplot as plt
import matplotlib.patheffects as patheffects
from matplotlib import colors as mcolors

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
        self.presence: Dict[str, bool] = {}
        # Track whether motion has been seen recently in a room. The
        # ``motion_state`` flag remains ``True`` for ``cooldown`` seconds
        # after the initial trigger.
        self.motion_state: Dict[str, bool] = defaultdict(lambda: False)

    def record_trigger(self, room_id: str, timestamp: Optional[float] = None) -> None:
        """Record a motion sensor trigger for *room_id*.

        If the room is already in the active motion state and the cooldown has
        not yet elapsed, the trigger is ignored so the active period is not
        extended.
        """
        now = time.time() if timestamp is None else timestamp
        last = self.last_fire.get(room_id, 0.0)
        if self.motion_state.get(room_id, False) and now - last < self.cooldown:
            return
        self.motion_state[room_id] = True
        self.last_fire[room_id] = now

    def set_presence(self, room_id: str, present: bool) -> None:
        """Record explicit presence information."""
        self.presence[room_id] = present

    def likelihood_still_present(
        self, room_id: str, current_time: Optional[float] = None
    ) -> float:
        pres = self.presence.get(room_id)
        if pres is True:
            return 1.0
        if pres is False:
            return 0.0
        now = time.time() if current_time is None else current_time
        last = self.last_fire.get(room_id, 0.0)
        state = self.motion_state.get(room_id, False)
        dt = now - last
        if state and dt < self.cooldown:
            return 1.0
        if state and dt >= self.cooldown:
            self.motion_state[room_id] = False
        return self.floor_prob


class Particle:
    def __init__(self, room: str, weight: float = 1.0):
        self.room = room
        self.weight = weight

    def move(self, room_graph: RoomGraph, *, stay_prob: float = 0.5) -> None:
        """Move to a random neighbouring room with probability ``1 - stay_prob``."""
        neighbors = room_graph.get_neighbors(self.room)
        if neighbors and random.random() > stay_prob:
            self.room = random.choice(neighbors)

    def copy(self) -> "Particle":
        return Particle(self.room, self.weight)


class PersonTracker:
    """Particle filter tracker for a single person."""

    def __init__(
        self,
        room_graph: RoomGraph,
        sensor_model: SensorModel,
        num_particles: int = 100,
        *,
        stay_prob: float = 0.5,
    ):
        self.room_graph = room_graph
        self.sensor_model = sensor_model
        self.stay_prob = stay_prob
        self.particles: List[Particle] = []
        self.last_sensor_room: Optional[str] = None
        self.last_sensor_time: float = 0.0
        self._init_particles(num_particles)

    def _init_particles(self, n: int) -> None:
        rooms = list(self.room_graph.graph.nodes)
        for _ in range(n):
            room = random.choice(rooms)
            self.particles.append(Particle(room))

    def move_particles(self, sensor_room: Optional[str] = None) -> None:
        if sensor_room is not None:
            for p in self.particles:
                p.room = sensor_room
        else:
            for p in self.particles:
                p.move(self.room_graph, stay_prob=self.stay_prob)

    def update(self, current_time: float, sensor_room: Optional[str] = None) -> None:
        if sensor_room is not None:
            self.last_sensor_room = sensor_room
            self.last_sensor_time = current_time
            self.sensor_model.record_trigger(sensor_room, current_time)
        self.move_particles(sensor_room)

        for p in self.particles:
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
        debug: bool = True,
        debug_dir: str = "debug",
        event_window: int = 600,
        test_name: Optional[str] = None,
        min_plot_time: float = DEFAULT_MIN_PLOT_TIME,
        stay_prob: float = 0.5,
        layout: Optional[Dict[str, Tuple[float, float]]] = None,
    ):
        self.room_graph = room_graph
        self.sensor_model = sensor_model
        self.stay_prob = stay_prob
        self.people: Dict[str, Person] = {}
        self.phones: Dict[str, Phone] = {}
        self.trackers: Dict[str, PersonTracker] = {}
        self.debug = debug
        self.debug_dir = debug_dir
        self.event_window = event_window
        self.test_name = test_name
        self._min_plot_time = float(min_plot_time)
        self._debug_counter = 0
        self._current_event_dir: Optional[str] = None
        self._last_event_time: float = 0.0
        self._last_plot_time: float = 0.0
        self._pending_update: bool = False
        self._event_history: List[str] = []
        self._estimate_history: List[str] = []
        self._highlight_room: Optional[str] = None
        self._estimate_paths: Dict[str, List[str]] = defaultdict(list)
        self._true_paths: Dict[str, List[str]] = defaultdict(list)
        self._sensor_events: List[Tuple[float, str]] = []
        self._sensor_glow: Dict[str, int] = defaultdict(int)
        self._start_time: float = 0.0
        self._last_estimates: Dict[str, str] = {}
        if self.debug:
            os.makedirs(self.debug_dir, exist_ok=True)
            if layout is not None:
                self._layout = layout
            else:
                # Generate a deterministic layout
                num_nodes = len(self.room_graph.graph.nodes)
                k = 3.0 / (num_nodes ** 0.5) if num_nodes else 0.6
                spring_pos = nx.spring_layout(
                    self.room_graph.graph,
                    seed=42,
                    k=k,
                    scale=3.0,
                    iterations=200,
                )
                self._layout = nx.kamada_kawai_layout(
                    self.room_graph.graph,
                    pos=spring_pos,
                    scale=3.0,
                    weight=None,
                )

    def _start_event(self, timestamp: float) -> None:
        """Create a new directory for debug frames for a sensor event."""
        if self.test_name:
            # When running under tests, keep all output under a fixed
            # "tests" date directory and use the test name instead of
            # timestamp-based subfolders. This keeps paths stable and
            # ensures subsequent events append to the same directory.
            path = os.path.join(self.debug_dir, "tests", self.test_name)
        else:
            date_dir = datetime.datetime.fromtimestamp(timestamp).strftime("%Y/%m/%d")
            event_dir = datetime.datetime.fromtimestamp(timestamp).strftime("%H%M%S")
            path = os.path.join(self.debug_dir, date_dir, event_dir)
        os.makedirs(path, exist_ok=True)
        self._current_event_dir = path
        self._last_event_time = timestamp
        self._debug_counter = 0
        self._event_history = []
        self._estimate_history = []
        self._last_estimates = {}
        self._estimate_paths = defaultdict(list)
        self._true_paths = defaultdict(list)
        self._sensor_events = []
        self._sensor_glow = defaultdict(int)
        self._start_time = timestamp

    def _maybe_visualize(self, now: float, *, force: bool = False) -> None:
        """Save a debug frame if enough time has passed and there was an update.

        When ``force`` is ``True`` a frame is written regardless of the
        ``min_plot_time`` setting and the image file name is the timestamp of
        ``now``. This is used so each sensor event produces a standalone
        visualization.
        """
        if self._pending_update and (force or now - self._last_plot_time >= self._min_plot_time):
            if (
                self._current_event_dir is None
                or now - self._last_event_time > self.event_window
            ):
                self._start_event(now)
            filename = f"{now:.1f}.png" if force else None
            self._visualize(now, filename=filename)
            self._last_plot_time = now
            self._pending_update = False

    def process_event(
        self, person_id: str, room_id: str, timestamp: Optional[float] = None
    ) -> None:
        now = time.time() if timestamp is None else timestamp
        person = self.people.get(person_id)
        if person is None:
            tracker = PersonTracker(
                self.room_graph,
                self.sensor_model,
                stay_prob=self.stay_prob,
            )
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
        self._last_event_time = now
        if self.debug:
            estimate = tracker.estimate()
            self._estimate_paths[person_id].append(estimate)
            self._true_paths[person_id].append(room_id)
            if estimate != self._last_estimates.get(person_id):
                prob = tracker.distribution().get(estimate, 0.0)
                true_loc = tracker.last_sensor_room or "unknown"
                self._estimate_history.append(
                    f"{now:.1f}s: {person_id}: {estimate} ({prob:.2f}) true={true_loc}"
                )
                self._last_estimates[person_id] = estimate
            self._highlight_room = room_id
            self._sensor_events.append((now, room_id))
            self._sensor_glow[room_id] = 5
            self._event_history.append(
                f"{now:.1f}s: motion {room_id} fired, est={estimate}"
            )
            self._pending_update = True
            self._maybe_visualize(now, force=True)
            self._highlight_room = None

    def step(self, timestamp: Optional[float] = None, skip_ids: Optional[set[str]] = None) -> None:
        now = time.time() if timestamp is None else timestamp
        changed: List[str] = []
        for pid, person in self.people.items():
            if skip_ids and pid in skip_ids:
                if self.debug:
                    est = person.tracker.estimate()
                    self._estimate_paths[pid].append(est)
                    if est != self._last_estimates.get(pid):
                        changed.append(pid)
                continue
            person.tracker.update(now)
            if self.debug:
                est = person.tracker.estimate()
                self._estimate_paths[pid].append(est)
                if est != self._last_estimates.get(pid):
                    changed.append(pid)
        if self.debug and changed:
            for pid in changed:
                person = self.people[pid]
                est = person.tracker.estimate()
                prob = person.tracker.distribution().get(est, 0.0)
                true_loc = person.tracker.last_sensor_room or "unknown"
                self._estimate_history.append(
                    f"{now:.1f}s: {pid}: {est} ({prob:.2f}) true={true_loc}"
                )
                self._last_estimates[pid] = est
            self._pending_update = True
            self._maybe_visualize(now)

    def estimate_locations(self) -> Dict[str, str]:
        return {pid: person.tracker.estimate() for pid, person in self.people.items()}

    def set_highlight_room(self, room_id: Optional[str]) -> None:
        self._highlight_room = room_id

    def _format_highlight_probabilities(self) -> str:
        if not self._highlight_room:
            return ""
        parts = []
        for pid, person in self.people.items():
            prob = person.tracker.distribution().get(self._highlight_room, 0.0)
            parts.append(f"{pid}:{prob:.2f}")
        if not parts:
            return ""
        return f"{self._highlight_room}: " + ", ".join(parts)

    def record_presence(self, room_id: str, present: bool, timestamp: Optional[float] = None) -> None:
        now = time.time() if timestamp is None else timestamp
        self.sensor_model.set_presence(room_id, present)
        for pid, person in self.people.items():
            person.tracker.update(now)
        self._last_event_time = now
        if self.debug:
            self._highlight_room = room_id
            self._sensor_events.append((now, room_id))
            self._sensor_glow[room_id] = 5
            self._event_history.append(
                f"{now:.1f}s: presence {room_id}={present}"
            )
            self._pending_update = True
            self._maybe_visualize(now, force=True)
            self._highlight_room = None

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
            tracker = PersonTracker(
                self.room_graph,
                self.sensor_model,
                stay_prob=self.stay_prob,
            )
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
        self._last_event_time = now

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

    def _visualize(self, current_time: float, *, filename: Optional[str] = None) -> None:
        """Create a debug figure showing tracker state."""
        plt.clf()
        fig = plt.figure(figsize=(16, 10))
        gs = fig.add_gridspec(2, 2, width_ratios=[3, 1], height_ratios=[3, 1])
        ax = fig.add_subplot(gs[0, 0])
        timeline_ax = fig.add_subplot(gs[1, 0])
        info_ax = fig.add_subplot(gs[:, 1])
        info_ax.axis("off")

        graph = self.room_graph.graph
        nx.draw_networkx_edges(
            graph,
            pos=self._layout,
            ax=ax,
            edge_color="gray",
        )
        nx.draw_networkx_nodes(
            graph,
            pos=self._layout,
            ax=ax,
            node_color="skyblue",
            edgecolors="black",
        )
        labels = {
            node: f"{node} ({int(self.sensor_model.motion_state.get(node, False))})"
            for node in graph.nodes
        }
        label_artists = nx.draw_networkx_labels(
            graph,
            pos=self._layout,
            labels=labels,
            ax=ax,
            font_size=9,
            font_color="black",
        )
        for text in label_artists.values():
            text.set_path_effects(
                [patheffects.withStroke(linewidth=2, foreground="white")]
            )

        colors = {0: "red", 1: "green", 2: "blue"}
        for idx, (pid, person) in enumerate(self.people.items()):
            dist = person.tracker.distribution()
            node_colors = []
            node_sizes = []
            base_rgb = mcolors.to_rgb(colors.get(idx % 3, "black"))
            grey = (0.6, 0.6, 0.6)
            for node in graph.nodes:
                prob = dist.get(node, 0.0)
                color = tuple(
                    prob * c + (1 - prob) * g for c, g in zip(base_rgb, grey)
                )
                node_colors.append(color)
                node_sizes.append(400 + prob * 600)
            nx.draw_networkx_nodes(
                graph,
                pos=self._layout,
                nodelist=list(graph.nodes),
                node_color=node_colors,
                node_size=node_sizes,
                alpha=0.9,
                ax=ax,
            )

            # Numeric probabilities near nodes
            for node, pos in self._layout.items():
                prob = dist.get(node, 0.0)
                if prob > 0.01:
                    ax.text(
                        pos[0],
                        pos[1] + 0.1 + 0.05 * idx,
                        f"{prob:.2f}",
                        color=colors.get(idx % 3, (0, 0, 0)),
                        fontsize=7,
                        ha="center",
                        path_effects=[
                            patheffects.withStroke(linewidth=2, foreground="white")
                        ],
                    )

            # Draw estimated path as a continuous line
            path = self._estimate_paths.get(pid, [])
            if len(path) > 1:
                xs, ys = zip(*(self._layout[p] for p in path))
                ax.plot(
                    xs,
                    ys,
                    color=colors.get(idx % 3, (0, 0, 0)),
                    lw=2,
                    marker="o",
                    ms=4,
                )

            # Ground truth path for tests
            if self.test_name:
                true_path = self._true_paths.get(pid, [])
                if len(true_path) > 1:
                    xs, ys = zip(*(self._layout[p] for p in true_path))
                    ax.plot(
                        xs,
                        ys,
                        color="orange",
                        lw=2,
                        ls="dashed",
                        marker="o",
                        ms=4,
                    )

        # Highlight current sensor room strongly
        if self._highlight_room:
            nx.draw_networkx_nodes(
                graph,
                pos=self._layout,
                nodelist=[self._highlight_room],
                node_color="yellow",
                edgecolors="black",
                linewidths=2,
                node_size=800,
                ax=ax,
            )

        # Draw fading glow for recent sensors
        for room, count in list(self._sensor_glow.items()):
            if count > 0:
                nx.draw_networkx_nodes(
                    graph,
                    pos=self._layout,
                    nodelist=[room],
                    node_color="yellow",
                    alpha=0.3,
                    node_size=1000,
                    ax=ax,
                )
                self._sensor_glow[room] -= 1
            else:
                del self._sensor_glow[room]

        ax.set_title(f"t={current_time:.1f}", fontsize=13)
        ax.axis("off")

        # Sensor activation timeline
        if self._sensor_events:
            rooms = sorted({r for _, r in self._sensor_events})
            indices = {r: i for i, r in enumerate(rooms)}
            times = [t - self._start_time for t, _ in self._sensor_events]
            ys = [indices[r] for _, r in self._sensor_events]
            timeline_ax.scatter(
                times,
                ys,
                marker="o",
                s=60,
                color="black",
                zorder=3,
            )
            timeline_ax.set_yticks(list(indices.values()))
            timeline_ax.set_yticklabels(rooms)
            timeline_ax.set_xlabel("Time (s)")
            timeline_ax.set_title("Sensor activations")
            timeline_ax.set_xlim(0, max(1.0, current_time - self._start_time + 1))
            timeline_ax.set_ylim(-1, len(rooms))
            timeline_ax.axvline(current_time - self._start_time, color="gray", ls="--")
            timeline_ax.grid(True, axis="x", linestyle="--", alpha=0.5)
        else:
            timeline_ax.text(0.5, 0.5, "No sensor data", ha="center", va="center")
            timeline_ax.set_xticks([])
            timeline_ax.set_yticks([])

        # Build legend and textual info
        if self._current_event_dir:
            event_name = os.path.relpath(self._current_event_dir, self.debug_dir)
        else:
            event_name = "no_event"
        info_ax.text(0.0, 0.98, f"event: {event_name}", fontsize=10, ha="left", va="top")
        for idx, (pid, person) in enumerate(self.people.items()):
            text = f"{pid}: est={person.tracker.estimate()}"
            if person.tracker.last_sensor_room:
                text += f", last={person.tracker.last_sensor_room}"
            info_ax.text(0.0, 0.92 - idx * 0.05, text, fontsize=9, ha="left", va="top")

        legend_lines = [
            "Legend:",
            "  Node color: person id",
            "  Size ~ probability",
            "  label (1/0): motion sensor state",
        ]
        color_names = {0: "red", 1: "green", 2: "blue"}
        for idx, pid in enumerate(self.people.keys()):
            color_name = color_names.get(idx % 3, "unknown")
            legend_lines.append(f"  {pid}: {color_name}")
        legend_lines.append("  solid line: estimated path")
        legend_lines.append("  dashed orange: true path (tests only)")

        self._last_legend_lines = legend_lines

        for idx, line in enumerate(legend_lines):
            info_ax.text(0.0, 0.8 - idx * 0.04, line, fontsize=9, ha="left", va="top")

        log_start = 0.8 - len(legend_lines) * 0.04 - 0.04
        info_ax.text(0.0, log_start, "Event log:", fontsize=9, ha="left", va="top")
        for idx, message in enumerate(self._event_history[-10:]):
            info_ax.text(
                0.0,
                log_start - (idx + 1) * 0.04,
                message,
                fontsize=9,
                ha="left",
                va="top",
            )

        if self._highlight_room:
            prob_text = self._format_highlight_probabilities()
            if prob_text:
                info_ax.text(0.0, log_start - (len(self._event_history[-10:]) + 1) * 0.04, prob_text, fontsize=9, ha="left", va="top")

        est_start = (
            log_start
            - (len(self._event_history[-10:]) + 2) * 0.04
        )
        info_ax.text(0.0, est_start, "Estimates:", fontsize=9, ha="left", va="top")
        for idx, line in enumerate(self._estimate_history[-10:]):
            info_ax.text(
                0.0,
                est_start - (idx + 1) * 0.04,
                line,
                fontsize=9,
                ha="left",
                va="top",
            )

        plt.tight_layout()

        target_dir = self._current_event_dir
        if filename is None:
            fname = f"frame_{self._debug_counter:06d}.png"
        else:
            fname = filename if filename.endswith(".png") else f"{filename}.png"
        full_path = os.path.join(target_dir, fname)
        plt.savefig(full_path)
        plt.close(fig)
        self._debug_counter += 1


def init_from_yaml(
    connections_path: str,
    *,
    debug: bool = False,
    debug_dir: str = "debug",
    test_name: Optional[str] = None,
    stay_prob: float = 0.5,
) -> MultiPersonTracker:
    graph = load_room_graph_from_yaml(connections_path)
    sensor_model = SensorModel()
    return MultiPersonTracker(
        graph,
        sensor_model,
        debug=debug,
        debug_dir=debug_dir,
        test_name=test_name,
        stay_prob=stay_prob,
    )
