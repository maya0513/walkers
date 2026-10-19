"""Spatial sole envelope shared by the builder and replacement-model exporter."""
import math


def samples(vertices, weights, region_height=.13, cell_size=.02):
    result = {}
    for side, sign in [("Left",1),("Right",-1)]:
        candidates = [i for i,v in enumerate(vertices) if v.z < region_height and v.x*sign > 0]
        selected = set()
        cells = {}
        for i in candidates:
            v = vertices[i]
            dominant = max(weights[i],key=lambda p:p[1])[0]
            key = (math.floor(v.x/cell_size),math.floor(v.y/cell_size),dominant)
            if key not in cells or v.z < vertices[cells[key]].z:
                cells[key] = i
        selected.update(cells.values())
        # Include boundary points for tilted soles as well as interior patches
        # that can overlap a stair riser while the convex hull is on two treads.
        for tilt in [0,25,50,75]:
            for azimuth in range(16):
                t,a=math.radians(tilt),azimuth*math.tau/16
                direction=(math.sin(t)*math.cos(a),math.sin(t)*math.sin(a),math.cos(t))
                selected.add(min(candidates,key=lambda i:sum(vertices[i][j]*direction[j] for j in range(3))))
        result[side]=[{"position":[vertices[i].x,vertices[i].z,-vertices[i].y],"weights":weights[i]} for i in sorted(selected)]
    return result
