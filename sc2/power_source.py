from __future__ import annotations

from dataclasses import dataclass

from s2clientprotocol import raw_pb2
from sc2.position import Point2


@dataclass
class PowerSource:
    position: Point2
    radius: float
    unit_tag: int

    def __post_init__(self) -> None:
        assert self.radius > 0

    @classmethod
    def from_proto(cls, proto: raw_pb2.PowerSource) -> PowerSource:
        return PowerSource(Point2.from_proto(proto.pos), proto.radius, proto.tag)

    def covers(self, position: Point2) -> bool:
        return self.position.distance_to(position) <= self.radius

    def __repr__(self) -> str:
        return f"PowerSource({self.position}, {self.radius})"


@dataclass
class PsionicMatrix:
    sources: list[PowerSource]

    @classmethod
    def from_proto(cls, proto: list[raw_pb2.PowerSource]) -> PsionicMatrix:
        return PsionicMatrix([PowerSource.from_proto(p) for p in proto])

    def covers(self, position: Point2) -> bool:
        return any(source.covers(position) for source in self.sources)
