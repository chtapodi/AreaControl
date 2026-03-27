import copy
import math
import yaml


class _NullLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def _clamp(value):
    return max(0, min(255, int(round(value))))


class ColorMapper:
    """
    Maps RGB values between light profiles using configurable calibration and sample pairs.

    The YAML config accepts:
      reference_profile: canonical profile name (default: "hue")
      profiles:
        kauf:
          calibration: [1.0, 1.0, 1.0]
          rgb_to_color_temp:
            samples:
              - source: [255, 200, 160]
                target: 2200
            distance_bias: 1.0
      mappings:
        hue:
          kauf:
            samples:
              - source: [255, 255, 255]
                target: [255, 255, 255]
            distance_bias: 1.0   # optional, reduces sensitivity to small deltas
            bidirectional: true  # optional, auto-generate reverse mapping when missing
    """

    def __init__(
        self,
        config_path=None,
        defaults=None,
        reference_profile="hue",
        logger=None,
        config_data=None,
    ):
        self.log = logger or _NullLogger()
        self.reference_profile = reference_profile
        self.config_path = config_path
        self.profile_multipliers = {}
        self.mappings = {}
        self.temperature_mappings = {}

        if defaults:
            for name, multipliers in defaults.items():
                normalized = self._normalize_multipliers(multipliers)
                if normalized:
                    self.profile_multipliers[name] = normalized

        if config_data is not None:
            self._load_from_dict(config_data)
        else:
            self._load_from_path(config_path)

    def to_profile(self, rgb, target_profile, source_profile=None):
        """Map an RGB color to the requested profile using weighted samples + calibration."""
        if rgb is None:
            return None

        target = target_profile or self.reference_profile
        source = source_profile or self.reference_profile
        base_color = list(rgb)

        # Normalize into reference space when starting from a device-specific profile.
        if source != self.reference_profile:
            candidate = self._map_between_profiles(base_color, source, self.reference_profile)
            if candidate is not None:
                base_color = candidate

        reference_color = base_color if source == self.reference_profile else base_color

        # Map from reference to target profile using all configured samples.
        mapped = reference_color
        if target != self.reference_profile:
            candidate = self._map_between_profiles(reference_color, self.reference_profile, target)
            if candidate is not None:
                mapped = candidate

        calibrated = self._apply_multipliers(mapped, self.profile_multipliers.get(target))
        return calibrated

    # Internal helpers
    def _load_from_path(self, path):
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
        except Exception as exc:
            self.log.warning(f"ColorMapper: failed to load {path}: {exc}")
            return
        self._load_from_dict(data)

    def _load_from_dict(self, data):
        config = data or {}
        self.reference_profile = config.get("reference_profile", self.reference_profile)

        for name, profile_data in (config.get("profiles") or {}).items():
            normalized = self._normalize_multipliers(profile_data)
            if normalized:
                self.profile_multipliers[name] = normalized
            if isinstance(profile_data, dict):
                temp_map = self._parse_temperature_mapping(profile_data)
                if temp_map:
                    self.temperature_mappings[name] = temp_map

        for source, targets in (config.get("mappings") or {}).items():
            if targets is None:
                continue
            for target, mapping in targets.items():
                if mapping is None:
                    continue
                self._register_mapping(source, target, mapping)

    def _register_mapping(self, source, target, mapping):
        samples = []
        for sample in mapping.get("samples", []):
            src = self._coerce_rgb(sample.get("source") or sample.get("from"))
            tgt = self._coerce_rgb(sample.get("target") or sample.get("to"))
            if src is None or tgt is None:
                continue
            samples.append({"source": src, "target": tgt})

        if not samples:
            return

        entry = copy.deepcopy(mapping)
        entry["samples"] = samples
        entry.setdefault("distance_bias", 1.0)
        self.mappings.setdefault(source, {})[target] = entry

        # Optionally auto-generate reverse mapping so both directions stay in sync.
        should_reverse = entry.pop("bidirectional", True)
        if should_reverse and source not in self.mappings.get(target, {}):
            reverse_entry = copy.deepcopy(entry)
            reverse_entry["samples"] = [
                {"source": item["target"], "target": item["source"]} for item in samples
            ]
            self.mappings.setdefault(target, {}).setdefault(source, reverse_entry)

    def _parse_temperature_mapping(self, mapping):
        """Parse rgb->color_temp mapping for a profile."""
        if mapping is None:
            return None
        temp_mapping = mapping.get("rgb_to_color_temp") or mapping.get("rgb_to_temp")
        if temp_mapping is None:
            return None

        samples = []
        for sample in temp_mapping.get("samples", []):
            src = self._coerce_rgb(sample.get("source") or sample.get("from"))
            tgt = sample.get("target") or sample.get("to") or sample.get("temp")
            if src is None or tgt is None:
                continue
            try:
                temp = int(round(float(tgt)))
            except Exception:
                continue
            samples.append({"source": src, "target": temp})

        if not samples:
            return None

        entry = copy.deepcopy(temp_mapping)
        entry["samples"] = samples
        entry.setdefault("distance_bias", 1.0)
        return entry

    def _map_between_profiles(self, rgb, source_profile, target_profile):
        mapping = self.mappings.get(source_profile, {}).get(target_profile)
        if not mapping:
            return None

        samples = mapping.get("samples", [])
        distance_bias = mapping.get("distance_bias", 1.0) or 1.0

        weighted = [0.0, 0.0, 0.0]
        weight_total = 0.0
        for sample in samples:
            src = sample.get("source")
            tgt = sample.get("target")
            if src is None or tgt is None:
                continue

            distance = self._distance(rgb, src)
            weight = 1.0 / (distance + distance_bias)
            weight_total += weight
            for i in range(3):
                weighted[i] += tgt[i] * weight

        if weight_total == 0:
            return None

        return [_clamp(value / weight_total) for value in weighted]

    def _map_to_temperature(self, rgb, mapping):
        samples = mapping.get("samples", [])
        distance_bias = mapping.get("distance_bias", 1.0) or 1.0

        weighted = 0.0
        weight_total = 0.0
        for sample in samples:
            src = sample.get("source")
            tgt = sample.get("target")
            if src is None or tgt is None:
                continue

            distance = self._distance(rgb, src)
            weight = 1.0 / (distance + distance_bias)
            weight_total += weight
            weighted += tgt * weight

        if weight_total == 0:
            return None
        return int(round(weighted / weight_total))

    def to_color_temp(self, rgb, target_profile=None):
        """Map an RGB color to a color_temp for the target profile using samples."""
        if rgb is None:
            return None
        profile = target_profile or self.reference_profile
        mapping = self.temperature_mappings.get(profile)
        if not mapping:
            return None
        return self._map_to_temperature(rgb, mapping)

    def _apply_multipliers(self, rgb, multipliers):
        if rgb is None:
            return None
        if not multipliers:
            return list(rgb)

        adjusted = []
        for comp, factor in zip(rgb, multipliers):
            try:
                value = comp * float(factor)
            except Exception:
                value = comp
            adjusted.append(_clamp(value))
        return adjusted

    def _normalize_multipliers(self, value):
        if value is None:
            return None
        if isinstance(value, dict):
            for key in ("calibration", "multipliers", "scale"):
                if key in value:
                    return self._normalize_multipliers(value[key])
            return None
        if isinstance(value, (list, tuple)):
            if len(value) < 3:
                return None
            return [float(value[i]) for i in range(3)]
        if isinstance(value, (int, float)):
            return [float(value)] * 3
        return None

    def _coerce_rgb(self, value):
        if value is None:
            return None
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            return [_clamp(component) for component in value[:3]]
        return None

    @staticmethod
    def _distance(color_one, color_two):
        if color_one is None or color_two is None:
            return math.inf
        return math.sqrt(
            sum((float(a) - float(b)) ** 2 for a, b in zip(color_one[:3], color_two[:3]))
        )
