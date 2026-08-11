from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

MotionState = Literal["stationary", "moving", "starting", "stopping", "unknown"]
SpeedBand = Literal["low", "medium", "high", "unknown"]
ManeuverType = Literal["lane_keeping", "lane_change", "turn", "u_turn", "unknown"]
Direction = Literal["left", "right", "straight"] | None
TriState = Literal["present", "absent", "unknown"]
YesNoUnknown = Literal["yes", "no", "unknown"]


@dataclass
class EgoMotion:
    state: MotionState = "unknown"
    speed_band: SpeedBand = "unknown"


@dataclass
class EgoManeuver:
    type: ManeuverType = "unknown"
    direction: Direction = None


@dataclass
class TrafficRelation:
    lead: TriState = "unknown"
    trail: TriState = "unknown"


@dataclass
class RoadContext:
    intersection: YesNoUnknown = "unknown"
    traffic_light_intersection: YesNoUnknown = "unknown"
    traffic_light_relevant: YesNoUnknown = "unknown"
    on_stopline_crosswalk: YesNoUnknown = "unknown"


@dataclass
class SimplifiedFrameTags:
    ego_motion: EgoMotion = field(default_factory=EgoMotion)
    ego_maneuver: EgoManeuver = field(default_factory=EgoManeuver)
    traffic_relation: TrafficRelation = field(default_factory=TrafficRelation)
    road_context: RoadContext = field(default_factory=RoadContext)
    interaction_tags: list[str] = field(default_factory=list)
    source_scenarios: list[str] = field(default_factory=list)
    unmapped_scenarios: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
