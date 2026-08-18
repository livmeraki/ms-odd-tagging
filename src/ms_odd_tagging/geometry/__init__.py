"""Geometry ownership declarations.

Geometry stays with the domain that gives it meaning. This registry prevents
similar-looking lane experiments from being treated as interchangeable.
"""

from .registry import GEOMETRY_OWNERS, GeometryOwner, get_geometry_owner

__all__ = ["GEOMETRY_OWNERS", "GeometryOwner", "get_geometry_owner"]
