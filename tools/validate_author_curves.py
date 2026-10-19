"""One-sided join observations of the authored ankle/roll/contact functions.

Run through validate_blender.py. This is separate from 60Hz baked-pose finite
changes: compare the left/right limit at each piecewise mathematical join.
Four stencil sizes distinguish convergence from float32 Vector roundoff.
"""
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def lagrange_weights(order):
    weights = []
    for i in range(1, 6):
        poly = [1.]
        for j in range(1, 6):
            if i == j: continue
            result = [0.]*(len(poly)+1)
            for k, value in enumerate(poly):
                result[k] -= j*value/(i-j)
                result[k+1] += value/(i-j)
            poly = result
        weights.append(poly[order]*math.factorial(order))
    return weights


WEIGHTS = [lagrange_weights(k) for k in range(3)]


def limits(function, boundary, step, duration):
    sides = []
    for direction in [-1, 1]:
        values = [function((boundary+direction*step*i) % 1) for i in range(1, 6)]
        sides.append([[sum(w*value[channel] for w, value in zip(weights, values))/(direction*step*duration)**order
                       for channel in range(len(values[0]))] for order, weights in enumerate(WEIGHTS)])
    return [[a-b for a, b in zip(left, right)] for left, right in zip(*sides)]


def norm(values):
    return math.sqrt(sum(v*v for v in values))


def check(rig, body):
    sys.path.insert(0, str(ROOT/'tools'))
    import build_character as build
    from motion_authoring import Author, DUTIES, DURATIONS
    names = set(build.NAMES.values())
    rest = {bone.name: bone.matrix_local.copy() for bone in rig.data.bones if bone.name in names}
    build.DESC = {bone.name: [child.name for child in bone.children_recursive if child.name in rest] for bone in rig.data.bones}
    author = Author(rest, body, build.solve_leg, build.aim, build.world_rotate)
    result, failures = {}, []
    for clip in ['Walk', 'Jog']:
        duty, duration = DUTIES[clip], DURATIONS[clip]
        jog = clip == 'Jog'
        joins = {'cycle': 0., 'contact_rise_end': .035,
                 'heel_settle': .065 if jog else .12,
                 'push_start': duty-(.13 if jog else .20),
                 'contact_fall_start': duty-.045, 'toe_off': duty,
                 'swing_roll_middle': duty+.45*(1-duty),
                 'swing_retraction': duty+.8*(1-duty),
                 'swing_apex': duty+(.40 if jog else .48)*(1-duty)}
        observations = {}
        for side in ['Left', 'Right']:
            def function(t):
                position, rotation, weight, support = author.foot(clip, side, t)
                return list(position)+[2*math.atan2(rotation.x, rotation.w), weight]+list(support)
            for label, phase in joins.items():
                rows = []
                for step in [.002, .001, .0005, .00025]:
                    difference = limits(function, phase, step, duration)
                    rows.append({'phase_step': step,
                                 'ankle_position_limit_difference_m': norm(difference[0][:3]),
                                 'ankle_velocity_limit_difference_mps': norm(difference[1][:3]),
                                 'ankle_acceleration_limit_difference_mps2': norm(difference[2][:3]),
                                 'roll_position_limit_difference_radians': abs(difference[0][3]),
                                 'roll_velocity_limit_difference_radps': abs(difference[1][3]),
                                 'roll_acceleration_limit_difference_radps2': abs(difference[2][3]),
                                 'contact_position_limit_difference': abs(difference[0][4]),
                                 'contact_velocity_limit_difference_per_second': abs(difference[1][4]),
                                 'contact_acceleration_limit_difference_per_second2': abs(difference[2][4]),
                                 'support_position_limit_difference_m': norm(difference[0][5:]),
                                 'support_velocity_limit_difference_mps': norm(difference[1][5:]),
                                 'support_acceleration_limit_difference_mps2': norm(difference[2][5:])})
                best = {name: min(row[name] for row in rows) for name in rows[0] if name != 'phase_step'}
                observations[side+'_'+label] = {'phase': phase, 'stencils': rows, 'best_resolved_difference': best}
                thresholds = {'ankle_position_limit_difference_m': .00001,
                              'ankle_velocity_limit_difference_mps': .01,
                              'ankle_acceleration_limit_difference_mps2': 3.,
                              'roll_position_limit_difference_radians': .0001,
                              'roll_velocity_limit_difference_radps': .01,
                              'roll_acceleration_limit_difference_radps2': 8.,
                              'contact_position_limit_difference': .0001,
                              'contact_velocity_limit_difference_per_second': .02,
                              'contact_acceleration_limit_difference_per_second2': 3.,
                              'support_position_limit_difference_m': .00001,
                              'support_velocity_limit_difference_mps': .02,
                              'support_acceleration_limit_difference_mps2': 5.}
                for field, threshold in thresholds.items():
                    if best[field] > threshold:
                        failures.append(f'{clip} {side} {label}: authored join {field}={best[field]:.6g}')
        result[clip] = observations
    return {'method': 'one-sided fourth-degree extrapolation of 5 points, phase steps .002/.001/.0005/.00025; derivative units use true cycle duration',
            'precision': 'best resolved difference across stencils; Blender Vector/Quaternion components are float32, so acceleration differences include numerical noise',
            'note': 'This tests joins of authored functions, separate from finite 60Hz motion and FK/IK. Support pressure-centre sample travel is reported, not treated as skin-point slip.',
            'clips': result, 'failures': failures}
