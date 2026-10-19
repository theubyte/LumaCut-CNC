"""CNC geometry only: no motion outputs, no hardware operations.

Laser center is machine XY; probe trigger point equals laser XY + (dx,dy).
Positive Z moves the optical datum away from the work surface.
All Z measurements share one optical datum.
"""
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class Bounds:
    xmin: float
    xmax: float
    ymin: float
    ymax: float

    def contains(self,x:float,y:float)->bool:
        return self.xmin<=x<=self.xmax and self.ymin<=y<=self.ymax

def finite(*values):
    if not all(isfinite(v) for v in values):
        raise ValueError("Expected finite numeric dimensions")

def laser_xy_for_probe(sample_x:float,sample_y:float,probe_dx:float,
                       probe_dy:float,bounds:Bounds)->tuple[float,float]:
    """Move laser center to sample - offset so the PROBE touches the sample."""
    finite(sample_x,sample_y,probe_dx,probe_dy)
    lx,ly=sample_x-probe_dx,sample_y-probe_dy
    if not bounds.contains(lx,ly):
        raise ValueError("Laser center outside travel bounds")
    if not bounds.contains(sample_x,sample_y):
        raise ValueError("Probe sample outside work bounds")
    return lx,ly

def raise_z_after_probe(focus_from_datum:float,tip_from_datum:float)->float:
    """Signed +Z motion AFTER trigger for optical datum to reach focus height."""
    finite(focus_from_datum,tip_from_datum)
    if focus_from_datum<=0 or tip_from_datum<=0:
        raise ValueError("Focus and trigger-tip distances must be positive")
    return focus_from_datum-tip_from_datum

def planned_mesh_grid(x0:float,y0:float,x1:float,y1:float,nx:int,ny:int,
                      dx:float,dy:float,bounds:Bounds)->list[dict[str,float]]:
    finite(x0,y0,x1,y1,dx,dy)
    if type(nx)!=int or type(ny)!=int or not 2<=nx<=30 or not 2<=ny<=30:
        raise ValueError("Mesh count must be 2..30 per axis")
    if x0>=x1 or y0>=y1: raise ValueError("Invalid mesh rectangle")
    result=[]
    for row in range(ny):
        sy=y0+(y1-y0)*row/(ny-1)
        indices=range(nx) if row%2==0 else range(nx-1,-1,-1)
        for col in indices:
            sx=x0+(x1-x0)*col/(nx-1)
            lx,ly=laser_xy_for_probe(sx,sy,dx,dy,bounds)
            result.append(dict(sample_x=sx,sample_y=sy,laser_x=lx,laser_y=ly))
    return result
