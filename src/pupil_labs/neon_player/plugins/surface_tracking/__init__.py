from surface_tracker import surface as surface_module

from .plugin import SurfaceTrackingPlugin

# this function seems to return vertices in reverse order
__src_bounding_quadrangle = surface_module._bounding_quadrangle
def __patched_bounding_quadrangle(*args, **kwargs):
    v = __src_bounding_quadrangle(*args, **kwargs)
    return v[[3, 2, 1, 0]]

surface_module._bounding_quadrangle = __patched_bounding_quadrangle

__all__ = [
    "SurfaceTrackingPlugin",
]
