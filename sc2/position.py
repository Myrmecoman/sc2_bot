from __future__ import annotations

import itertools
import math
import random
from collections.abc import Iterable
from typing import (
    Any,
    Protocol,
    SupportsFloat,
    SupportsIndex,
    TypeVar,
    Union,
)

from s2clientprotocol import common_pb2 as common_pb


class HasPosition2D(Protocol):
    @property
    def position(self) -> Point2: ...


_PointLike = Union[tuple[float, float], tuple[float, float], tuple[float, ...]]
_PosLike = Union[HasPosition2D, _PointLike]
_TPosLike = TypeVar("_TPosLike", bound=_PosLike)

EPSILON: float = 10**-8


def _sign(num: SupportsFloat | SupportsIndex) -> float:
    return math.copysign(1, num)


class Pointlike(tuple[float, ...]):
    T = TypeVar("T", bound="Pointlike")

    @property
    def position(self: T) -> T:
        return self

    def distance_to(self, target: _PosLike) -> float:
        """Calculate a single distance from a point or unit to another point or unit

        :param target:"""
        # pyrefly: ignore
        position: tuple[float, ...] = target if isinstance(target, tuple) else target.position
        return math.hypot(self[0] - position[0], self[1] - position[1])

    def distance_to_point2(self, p: _PointLike) -> float:
        """Same as the function above, but should be a bit faster because of the dropped asserts
        and conversion.

        :param p:"""
        return math.hypot(self[0] - p[0], self[1] - p[1])

    def _distance_squared(self, p2: _PointLike) -> float:
        """Function used to not take the square root as the distances will stay proportionally the same.
        This is to speed up the sorting process.

        :param p2:"""
        return (self[0] - p2[0]) ** 2 + (self[1] - p2[1]) ** 2

    def sort_by_distance(self, ps: Iterable[_TPosLike]) -> list[_TPosLike]:
        """This returns the target points sorted as list.
        You should not pass a set or dict since those are not sortable.
        If you want to sort your units towards a point, use 'units.sorted_by_distance_to(point)' instead.

        :param ps:"""
        return sorted(ps, key=lambda p: self.distance_to_point2(p if isinstance(p, tuple) else p.position))

    def closest(self, ps: Iterable[_TPosLike]) -> _TPosLike:
        """This function assumes the 2d distance is meant

        :param ps:"""
        assert ps, "ps is empty"

        return min(ps, key=lambda p: self.distance_to_point2(p if isinstance(p, tuple) else p.position))

    def distance_to_closest(self, ps: Iterable[_TPosLike]) -> float:
        """This function assumes the 2d distance is meant
        :param ps:"""
        assert ps, "ps is empty"
        closest_distance = math.inf
        for p in ps:
            # pyrefly: ignore
            p2: tuple[float, ...] = p if isinstance(p, tuple) else p.position
            distance = self.distance_to_point2(p2)
            if distance <= closest_distance:
                closest_distance = distance
        return closest_distance

    def furthest(self, ps: Iterable[_TPosLike]) -> _TPosLike:
        """This function assumes the 2d distance is meant

        :param ps: Units object, or iterable of Unit or Point2"""
        assert ps, "ps is empty"

        return max(ps, key=lambda p: self.distance_to_point2(p if isinstance(p, tuple) else p.position))

    def distance_to_furthest(self, ps: Iterable[_PosLike]) -> float:
        """This function assumes the 2d distance is meant

        :param ps:"""
        assert ps, "ps is empty"
        furthest_distance = -math.inf
        for p in ps:
            # pyrefly: ignore
            p2: tuple[float, ...] = p if isinstance(p, tuple) else p.position
            distance = self.distance_to_point2(p2)
            if distance >= furthest_distance:
                furthest_distance = distance
        return furthest_distance

    def offset(self: T, p: _PointLike) -> T:
        """

        :param p:
        """
        return self.__class__(a + b for a, b in itertools.zip_longest(self, p[: len(self)], fillvalue=0))

    def unit_axes_towards(self: T, p: _PointLike) -> T:
        """

        :param p:
        """
        return self.__class__(_sign(b - a) for a, b in itertools.zip_longest(self, p[: len(self)], fillvalue=0))

    def towards(self: T, p: _PosLike, distance: float = 1, limit: bool = False) -> T:
        """

        :param p:
        :param distance:
        :param limit:
        """
        # pyrefly: ignore
        p2: tuple[float, ...] = p if isinstance(p, tuple) else p.position
        # assert self != p, f"self is {self}, p is {p}"
        # TODO test and fix this if statement
        if self == p2:
            return self
        # end of test
        d = self.distance_to_point2(p2)
        if limit:
            distance = min(d, distance)
        return self.__class__(
            a + (b - a) / d * distance for a, b in itertools.zip_longest(self, p2[: len(self)], fillvalue=0)
        )

    def __eq__(self, other: Any) -> bool:
        try:
            return all(abs(a - b) <= EPSILON for a, b in itertools.zip_longest(self, other, fillvalue=0))
        except TypeError:
            return False

    def __hash__(self) -> int:
        return hash(tuple(self))


class Point2(Pointlike):
    T = TypeVar("T", bound="Point2")

    @classmethod
    def from_proto(
        cls, data: common_pb.Point | common_pb.Point2D | common_pb.Size2DI | common_pb.PointI | Point2 | Point3
    ) -> Point2:
        """
        :param data:
        """
        return cls((data.x, data.y))

    @property
    def as_Point2D(self) -> common_pb.Point2D:
        return common_pb.Point2D(x=self.x, y=self.y)

    @property
    def as_PointI(self) -> common_pb.PointI:
        """Represents points on the minimap. Values must be between 0 and 64."""
        return common_pb.PointI(x=int(self[0]), y=int(self[1]))

    @property
    def rounded(self) -> Point2:
        return Point2((math.floor(self[0]), math.floor(self[1])))

    @property
    def length(self) -> float:
        """This property exists in case Point2 is used as a vector."""
        return math.hypot(self[0], self[1])

    @property
    def normalized(self: Point2 | Point3) -> Point2:
        """This property exists in case Point2 is used as a vector."""
        length = self.length
        # Cannot normalize if length is zero
        assert length
        return Point2((self[0] / length, self[1] / length))

    @property
    def x(self) -> float:
        return self[0]

    @property
    def y(self) -> float:
        return self[1]

    @property
    def to2(self) -> Point2:
        return Point2(self[:2])

    @property
    def to3(self) -> Point3:
        return Point3((*self, 0))

    def round(self, decimals: int) -> Point2:
        """Rounds each number in the tuple to the amount of given decimals."""
        return Point2((round(self[0], decimals), round(self[1], decimals)))

    def offset(self: T, p: _PointLike) -> T:
        return self.__class__((self[0] + p[0], self[1] + p[1]))

    def random_on_distance(self, distance: float | tuple[float, float] | list[float]) -> Point2:
        if isinstance(distance, (tuple, list)):  # interval
            dist = distance[0] + random.random() * (distance[1] - distance[0])
        else:
            dist = distance
        assert dist > 0, "Distance is not greater than 0"
        angle = random.random() * 2 * math.pi

        dx, dy = math.cos(angle), math.sin(angle)
        return Point2((self.x + dx * dist, self.y + dy * dist))

    def towards_with_random_angle(
        self,
        p: Point2 | Point3,
        distance: int | float = 1,
        max_difference: int | float = (math.pi / 4),
    ) -> Point2:
        tx, ty = self.to2.towards(p.to2, 1)
        angle = math.atan2(ty - self.y, tx - self.x)
        angle = (angle - max_difference) + max_difference * 2 * random.random()
        return Point2((self.x + math.cos(angle) * distance, self.y + math.sin(angle) * distance))

    def circle_intersection(self, p: Point2, r: float) -> set[Point2]:
        """self is point1, p is point2, r is the radius for circles originating in both points
        Used in ramp finding

        :param p:
        :param r:"""
        assert self != p, "self is equal to p"
        distance_between_points = self.distance_to(p)
        assert r >= distance_between_points / 2
        # remaining distance from center towards the intersection, using pythagoras
        remaining_distance_from_center = (r**2 - (distance_between_points / 2) ** 2) ** 0.5
        # center of both points
        offset_to_center = Point2(((p.x - self.x) / 2, (p.y - self.y) / 2))
        center = self.offset(offset_to_center)

        # stretch offset vector in the ratio of remaining distance from center to intersection
        vector_stretch_factor = remaining_distance_from_center / (distance_between_points / 2)
        v = offset_to_center
        offset_to_center_stretched = Point2((v.x * vector_stretch_factor, v.y * vector_stretch_factor))

        # rotate vector by 90° and -90°
        vector_rotated_1 = Point2((offset_to_center_stretched.y, -offset_to_center_stretched.x))
        vector_rotated_2 = Point2((-offset_to_center_stretched.y, offset_to_center_stretched.x))
        intersect1 = center.offset(vector_rotated_1)
        intersect2 = center.offset(vector_rotated_2)
        return {intersect1, intersect2}

    @property
    def neighbors4(self: T) -> set[T]:
        return {
            self.__class__((self[0] - 1, self[1])),
            self.__class__((self[0] + 1, self[1])),
            self.__class__((self[0], self[1] - 1)),
            self.__class__((self[0], self[1] + 1)),
        }

    @property
    def neighbors8(self: T) -> set[T]:
        return self.neighbors4 | {
            self.__class__((self[0] - 1, self[1] - 1)),
            self.__class__((self[0] - 1, self[1] + 1)),
            self.__class__((self[0] + 1, self[1] - 1)),
            self.__class__((self[0] + 1, self[1] + 1)),
        }

    def negative_offset(self: T, other: Point2) -> T:
        return self.__class__((self[0] - other[0], self[1] - other[1]))

    def __add__(self, other: Point2) -> Point2:
        return self.offset(other)

    def __sub__(self, other: Point2) -> Point2:
        return self.negative_offset(other)

    def __neg__(self: T) -> T:
        return self.__class__(-a for a in self)

    def __abs__(self) -> float:
        return math.hypot(self[0], self[1])

    def __bool__(self) -> bool:
        return self[0] != 0 or self[1] != 0

    def __mul__(self, other: _PointLike | float) -> Point2:
        if isinstance(other, (int, float)):
            return Point2((self[0] * other, self[1] * other))
        return Point2((self[0] * other[0], self[1] * other[1]))

    def __rmul__(self, other: _PointLike | float) -> Point2:
        return self.__mul__(other)

    def __truediv__(self, other: float | Point2) -> Point2:
        if isinstance(other, (int, float)):
            return self.__class__((self[0] / other, self[1] / other))
        return self.__class__((self[0] / other[0], self[1] / other[1]))

    def is_same_as(self, other: Point2, dist: float = 0.001) -> bool:
        return self.distance_to_point2(other) <= dist

    def direction_vector(self, other: Point2) -> Point2:
        """Converts a vector to a direction that can face vertically, horizontally or diagonal or be zero, e.g. (0, 0), (1, -1), (1, 0)"""
        return self.__class__((_sign(other[0] - self[0]), _sign(other[1] - self[1])))

    def manhattan_distance(self, other: Point2) -> float:
        """
        :param other:
        """
        return abs(other[0] - self[0]) + abs(other[1] - self[1])

    @staticmethod
    def center(points: list[Point2]) -> Point2:
        """Returns the central point for points in list

        :param points:"""
        s = Point2((0, 0))
        for p in points:
            s += p
        return s / len(points)


class Point3(Point2):
    @classmethod
    def from_proto(cls, data: common_pb.Point | Point3) -> Point3:
        """
        :param data:
        """
        return cls((data.x, data.y, data.z))

    @property
    def as_Point(self) -> common_pb.Point:
        return common_pb.Point(x=self.x, y=self.y, z=self.z)

    @property
    def rounded(self) -> Point3:
        return Point3((math.floor(self[0]), math.floor(self[1]), math.floor(self[2])))

    @property
    def z(self) -> float:
        return self[2]

    @property
    def to3(self) -> Point3:
        return Point3(self)

    def __add__(self, other: Point2 | Point3) -> Point3:
        if not isinstance(other, Point3):
            return Point3((self[0] + other[0], self[1] + other[1], self[2]))
        return Point3((self[0] + other[0], self[1] + other[1], self[2] + other[2]))


class Size(Point2):
    @classmethod
    def from_proto(
        cls, data: common_pb.Point | common_pb.Point2D | common_pb.Size2DI | common_pb.PointI | Point2
    ) -> Size:
        """
        :param data:
        """
        return cls((data.x, data.y))

    @property
    def width(self) -> float:
        return self[0]

    @property
    def height(self) -> float:
        return self[1]


class Rect(Point2):
    @classmethod
    def from_proto(cls, data: common_pb.RectangleI) -> Rect:
        """
        :param data:
        """
        assert data.p0.x < data.p1.x and data.p0.y < data.p1.y
        return cls((data.p0.x, data.p0.y, data.p1.x - data.p0.x, data.p1.y - data.p0.y))

    @property
    def x(self) -> float:
        return self[0]

    @property
    def y(self) -> float:
        return self[1]

    @property
    def width(self) -> float:
        return self[2]

    @property
    def height(self) -> float:
        return self[3]

    @property
    def right(self) -> float:
        """Returns the x-coordinate of the rectangle of its right side."""
        return self.x + self.width

    @property
    def top(self) -> float:
        """Returns the y-coordinate of the rectangle of its top side."""
        return self.y + self.height

    @property
    def size(self) -> Size:
        return Size((self[2], self[3]))

    @property
    def center(self) -> Point2:
        return Point2((self.x + self.width / 2, self.y + self.height / 2))

    def offset(self, p: _PointLike) -> Rect:
        return self.__class__((self[0] + p[0], self[1] + p[1], self[2], self[3]))
