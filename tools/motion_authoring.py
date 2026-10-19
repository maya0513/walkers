"""Relaxed locomotion in metres (-Y forward, Z up).

Continuous sole rocker geometry and C2 trajectory joins are shared with runtime
support metadata. References and artistic choices: docs/gait_reference.ja.md.
"""
import math
from mathutils import Vector, Quaternion
import numpy as np

TAU = math.tau
SIDES = [("Left", 1, 0), ("Right", -1, .5)]
DURATIONS = {"Walk": 1.05, "Jog": .7}
SPEEDS = {"Walk": 1.4, "Jog": 2.8}
DUTIES = {"Walk": .56, "Jog": .36}
PUSH_RATES = {"Walk": 190., "Jog": 180.}
SWING_HEIGHTS = {"Walk": .20, "Jog": .30}
SWING_APICES = {"Walk": .44, "Jog": .42}
REAR_TIME = .10
REAR_CURVATURE = 1.0
REAR_DISTANCE = .35
FOOT_FRONT_FACTORS = {"Walk": .36, "Jog": .37}
PUSH_ANGLES = {"Walk": 45., "Jog": 45.}


def smooth(t):
    t = max(0., min(1., t))
    return t*t*t*(10+t*(-15+6*t))


def quintic(t, p0, p1, v0=0., v1=0., a0=0., a1=0.):
    """Hermite segment; derivatives are with respect to segment parameter."""
    t = max(0., min(1., t))
    c0, c1, c2 = p0, v0, a0*.5
    d, v, a = p1-c0-c1-c2, v1-c1-2*c2, a1-2*c2
    c3, c4, c5 = 10*d-4*v+.5*a, -15*d+7*v-a, 6*d-3*v+.5*a
    return c0+t*(c1+t*(c2+t*(c3+t*(c4+t*c5))))



class SoleRocker:
    """Skin-weighted flexible sole; support follows the articulated toe joint.

    Coordinates are rest-skeleton axes relative to the ankle. The smooth lower
    envelope stays below actual skin; its convex weights also identify a material
    point that runtime can transport when the toe bends.
    """
    def __init__(self, vertices, toe_weights, toe_pivot):
        self.vertices = np.asarray([list(v) for v in vertices], dtype=float)
        self.toe_weights = np.asarray(toe_weights, dtype=float)
        self.toe_pivot = np.asarray(list(toe_pivot), dtype=float)

    def contact(self, angle, bend=0.):
        c, s = math.cos(bend), math.sin(bend)
        dy = self.vertices[:, 1]-self.toe_pivot[1]
        dz = self.vertices[:, 2]-self.toe_pivot[2]
        deformed = self.vertices.copy()
        deformed[:, 1] += self.toe_weights*((c-1)*dy+s*dz)
        deformed[:, 2] += self.toe_weights*(-s*dy+(c-1)*dz)
        sa, ca = math.sin(angle), math.cos(angle)
        heights = sa*deformed[:, 1]+ca*deformed[:, 2]
        lo = float(heights.min()); softness = .00035
        weights = np.exp(-(heights-lo)/softness)
        total = float(weights.sum()); weights /= total
        height = -lo+softness*math.log(total)+.0007
        point = (deformed*weights[:, None]).sum(axis=0)
        # Below-skin offset is virtual, separate from the material correspondence.
        point[2] += (-height-(sa*point[1]+ca*point[2]))/ca
        material_dy = self.toe_weights*(-s*dy+c*dz)
        material_dz = self.toe_weights*(-c*dy-s*dz)
        material_velocity = float((weights*(ca*material_dy-sa*material_dz)).sum())
        return height, point, material_velocity, weights


class Author:
    def __init__(self, rest, body, solve_leg, aim, rotate):
        self.rest,self.solve_leg,self.aim,self.rotate=rest,solve_leg,aim,rotate
        self.parents={bone.name:bone.parent.name for bone in body.parent.data.bones if bone.name in rest and bone.parent}
        self.hierarchy=sorted(rest,key=lambda name:len(body.parent.data.bones[name].parent_recursive))
        self.feet={s:rest[s+"Foot"].to_quaternion() for s,_,_ in SIDES}
        group_names={group.index:group.name for group in body.vertex_groups}
        self.sole_indices={s:[v.index for v in body.data.vertices if v.co.z<.13 and v.co.x*sign>0] for s,sign,_ in SIDES}
        self.soles={s:[body.data.vertices[i].co.copy()-rest[s+"Foot"].translation for i in self.sole_indices[s]] for s,_,_ in SIDES}
        self.sole_bindings={s:[[(group_names[g.group],g.weight) for g in body.data.vertices[i].groups if g.weight>0 and group_names[g.group] in rest] for i in self.sole_indices[s]] for s,_,_ in SIDES}
        self.sole_rest={s:[body.data.vertices[i].co.copy() for i in self.sole_indices[s]] for s,_,_ in SIDES}
        self.rockers={s:SoleRocker(self.soles[s], [sum(w for n,w in bindings if n==s+"Toes") for bindings in self.sole_bindings[s]], rest[s+"Toes"].translation-rest[s+"Foot"].translation) for s,_,_ in SIDES}
        self.skin_bindings={}
        for side,_,_ in SIDES:
            entries={}
            for i,(point,influences) in enumerate(zip(self.sole_rest[side],self.sole_bindings[side])):
                for bone,weight in influences:
                    local=rest[bone].inverted()@point
                    entries.setdefault(bone,[]).append((i,local,weight))
            self.skin_bindings[side]={bone:(np.array([i for i,_,_ in rows]), np.array([list(point*weight) for _,point,weight in rows]), np.array([weight for _,_,weight in rows])) for bone,rows in entries.items()}
        self.travel_profiles={}
        self.height_endpoints={}
        self._build_travel_profiles()
        self.points={}
        for s,_,_ in SIDES:
            points=self.soles[s]
            lo,hi=min(v.y for v in points),max(v.y for v in points)
            positions={"heel":hi-.015,"sole":lo+(hi-lo)*.55,"ball":lo+.065,"toes":lo+.018}
            self.points[s]={r:min(points,key=lambda v:abs(v.y-y)+2*max(0,v.z+.07)).copy() for r,y in positions.items()}
        self.idle=self._neutral()
        self.hip_profiles={}
        self._build_hip_profiles()

    def _neutral(self):
        p={n:m.copy() for n,m in self.rest.items()}
        for s,sign,_ in SIDES:
            upper,lower,hand=[s+n for n in ["UpperArm","LowerArm","Hand"]]
            l1=(p[lower].translation-p[upper].translation).length
            l2=(p[hand].translation-p[lower].translation).length
            self.aim(p,upper,lower,p[upper].translation+Vector((sign*.065,0,-1)).normalized()*l1)
            self.aim(p,lower,hand,p[lower].translation+Vector((sign*.035,-.08,-1)).normalized()*l2)
            ankle=p[s+"Foot"].translation.copy()
            ankle.x,ankle.y=sign*.078,0
            ankle.z=-min(v.z for v in self.soles[s])+.003
            self.solve_leg(p,s,ankle,self.feet[s])
        self.relax_hands(p)
        return p

    def standing(self,phase=0):
        return {n:m.copy() for n,m in self.idle.items()}

    def foot_angles(self,name,t):
        jog=name=="Jog"; duty=DUTIES[name]
        touchdown=math.radians(4 if jog else -16)
        push=math.radians(PUSH_ANGLES[name])
        push_rate=math.radians(PUSH_RATES[name])
        leave=duty-(.14 if jog else .22)
        settle=.09 if jog else .15
        if t<=duty:
            loading=touchdown*(1-smooth(t/settle))
            extension=quintic((t-leave)/(duty-leave),0,push,v1=push_rate*(duty-leave)) if t>leave else 0.
            return loading+extension, .85*extension
        u=(t-duty)/(1-duty)
        middle=math.radians(7 if jog else 10)
        roll=quintic(u/.45,push,middle,v0=push_rate*(1-duty)*.45) if u<.45 else quintic((u-.45)/.55,middle,touchdown)
        # The toe joint releases after leaving the floor rather than remaining
        # world-horizontal throughout swing and landing.
        bend=quintic(u/.35,.85*push,0,v0=.85*push_rate*(1-duty)*.35) if u<.35 else 0.
        return roll,bend

    def _travel_rate(self,name,side,t):
        eps=1e-5
        # Stance endpoints use the exact polynomial continuation through toe-off.
        a,b=self.foot_angles(name,t)
        ap,bp=self.foot_angles(name,t+eps)
        am,bm=self.foot_angles(name,t-eps)
        da,db=(ap-am)/(2*eps),(bp-bm)/(2*eps)
        height,_,material_velocity,_=self.rockers[side].contact(a,b)
        return -height*da-material_velocity*db

    def _build_travel_profiles(self):
        # Integrate the no-slip velocity of the *same skin material*, including
        # toe deformation. A changing pressure centre is not a fixed skin point.
        count=1024
        for name in DURATIONS:
            step=DUTIES[name]/count
            for side,_,_ in SIDES:
                values=[0.]
                rates=[self._travel_rate(name,side,i*step) for i in range(count+1)]
                for i in range(count):
                    mid=self._travel_rate(name,side,(i+.5)*step)
                    values.append(values[-1]+step*(rates[i]+4*mid+rates[i+1])/6)
                accelerations=[(rates[min(count,i+1)]-rates[max(0,i-1)])/((min(count,i+1)-max(0,i-1))*step) for i in range(count+1)]
                self.travel_profiles[name,side]=(step,values,rates,accelerations)
                def ground_height(t):
                    a,b=self.foot_angles(name,t)
                    return self.rockers[side].contact(a,b)[0]
                t=DUTIES[name]; eps=1e-4
                h=ground_height(t)
                velocity=(ground_height(t+eps)-ground_height(t-eps))/(2*eps)
                acceleration=(ground_height(t+eps)-2*h+ground_height(t-eps))/eps**2
                self.height_endpoints[name,side]=(h,velocity,acceleration,ground_height(0))

    def travel(self,name,side,t):
        step,values,rates,accelerations=self.travel_profiles[name,side]
        t=max(0.,min(DUTIES[name],t)); x=t/step
        i=min(len(values)-2,int(x))
        return quintic(x-i,values[i],values[i+1],rates[i]*step,rates[i+1]*step,accelerations[i]*step*step,accelerations[i+1]*step*step)

    def foot(self,name,side,t):
        jog=name=="Jog";duty=DUTIES[name];stride=DURATIONS[name]*SPEEDS[name]
        front=-FOOT_FRONT_FACTORS[name]*stride*duty
        back=front+stride*duty
        roll,bend=self.foot_angles(name,t)
        rocker=self.rockers[side]
        if t<duty:
            y=front+stride*t+self.travel(name,side,t)
            contact=smooth(t/.035)*(1-smooth((t-(duty-.045))/.045))
        else:
            u=(t-duty)/(1-duty)
            tangent=stride*(1-duty)
            end=front
            turn=.80; width=1-turn
            minimum=end-.4*tangent*width
            curvature=.5*tangent/width
            initial=(stride+self._travel_rate(name,side,duty))*(1-duty)
            eps=1e-5
            acceleration=(self._travel_rate(name,side,duty+eps)-self._travel_rate(name,side,duty-eps))/(2*eps)
            initial_acceleration=acceleration*(1-duty)**2
            rear=REAR_TIME
            maximum=back+self.travel(name,side,duty)+REAR_DISTANCE*initial*rear
            rear_curvature=-REAR_CURVATURE*initial/rear
            if jog and u<turn:
                y=quintic(u/turn,back+self.travel(name,side,duty),minimum,initial*turn,0,initial_acceleration*turn*turn,curvature*turn*turn)
            elif u<rear:
                y=quintic(u/rear,back+self.travel(name,side,duty),maximum,initial*rear,0,initial_acceleration*rear*rear,rear_curvature*rear*rear)
            elif u<turn:
                width=turn-rear
                y=quintic((u-rear)/width,maximum,minimum,0,0,rear_curvature*width*width,curvature*width*width)
            else:
                y=quintic((u-turn)/width,minimum,end,0,tangent*width,curvature*width*width,0)
            contact=0.
        support,pivot,_,_=rocker.contact(roll,bend)
        z=support
        if t>=duty:
            # In flight the ankle follows its own recovery arc. Rolling an
            # imaginary floor under an airborne deforming foot adds false jolts.
            start,velocity,acceleration,end=self.height_endpoints[name,side]
            apex=SWING_APICES[name]; peak=SWING_HEIGHTS[name]
            curvature=-1.0 if jog else -.65
            if u<apex:
                z=quintic(u/apex,start,peak,velocity*(1-duty)*apex,0,acceleration*(1-duty)**2*apex**2,curvature*apex**2)
            else:
                width=1-apex
                z=quintic((u-apex)/width,peak,end,0,0,curvature*width**2,0)
        return Vector((0,y,z)),Quaternion(Vector((1,0,0)),roll),contact,pivot

    def gait(self,name,phase,_raw_height=False):
        jog=name=="Jog";phase%=1
        p={n:m.copy() for n,m in self.rest.items()}
        lateral=(.009 if jog else .014)*math.sin(TAU*phase)
        # Pelvis leads the leg; the spine distributes counter-rotation instead
        # of leaving the abdomen rigid or rotating all the torso as one block.
        wave=math.cos(TAU*phase)
        sway=math.sin(TAU*phase)
        twist=math.cos(TAU*(phase-.035))
        pelvis_yaw=math.radians(3.2 if jog else 4.0)*-wave
        pelvis_roll=math.radians(1.3 if jog else 2.0)*-sway
        pitch_wave=math.sin(2*TAU*(phase-.12))
        self.rotate(p,"Hips",Quaternion(Vector((1,0,0)),math.radians(4.0 if jog else .8)+math.radians(.45 if jog else .3)*pitch_wave))
        self.rotate(p,"Hips",Quaternion(Vector((0,1,0)),pelvis_roll))
        self.rotate(p,"Hips",Quaternion(Vector((0,0,1)),pelvis_yaw))
        for bone,yaw_share,roll_share,pitch_share in [("Spine",.45,.48,.4),("Chest",.35,.32,.35),("UpperChest",.20,.20,.25)]:
            self.rotate(p,bone,Quaternion(Vector((0,0,1)),math.radians(6.0 if jog else 6.2)*twist*yaw_share))
            self.rotate(p,bone,Quaternion(Vector((0,1,0)),-pelvis_roll*.85*roll_share))
            self.rotate(p,bone,Quaternion(Vector((1,0,0)),-math.radians(.35 if jog else .22)*pitch_wave*pitch_share))
        self.rotate(p,"Neck",Quaternion(Vector((0,0,1)),-.55*(pelvis_yaw+math.radians(6.0 if jog else 6.2)*twist)))
        self.rotate(p,"Neck",Quaternion(Vector((0,1,0)),-.5*pelvis_roll*.15))
        for n in p:
            if n!="Root":p[n].translation.x+=lateral
        targets=[];contacts=[]
        hip_z=self.rest["Hips"].translation.z
        ceiling=hip_z
        for s,sign,offset in SIDES:
            t=(phase+offset)%1
            target,q,contact,_=self.foot(name,s,t)
            target.x=sign*(.02 if jog else .05)
            targets.append((s,target,q@self.feet[s],t));contacts.append(round(contact,6))
            h,k,a=[p[s+n].translation for n in ["UpperLeg","LowerLeg","Foot"]]
            l1,l2=(k-h).length,(a-k).length
            reach=math.sqrt(l1*l1+l2*l2+2*l1*l2*math.cos(math.radians(16 if jog else 12)))
            horizontal=(target.x-h.x)**2+(target.y-h.y)**2
            ceiling=min(ceiling,target.z+math.sqrt(max(.01,reach*reach-horizontal))-(h.z-hip_z))
        if _raw_height:return ceiling
        center,amplitude,offset=self.hip_profiles[name]
        desired=center-amplitude*math.cos(2*TAU*(phase-offset))
        shift=Vector((0,0,desired-p["Hips"].translation.z))
        for n in p:
            if n!="Root":p[n].translation+=shift
        for s,target,q,t in targets:
            self.solve_leg(p,s,target,q)
            # Relative metatarsophalangeal extension, never a world-rest reset.
            _,bend=self.foot_angles(name,t)
            self.rotate(p,s+"Toes",Quaternion(Vector((1,0,0)),-bend))
            # Include real skin weights shared with the shin, not just the
            # flexible rocker approximation used for trajectory integration.
            a,b=self.foot_angles(name,t)
            desired_floor=target.z-self.rockers[s].contact(a,b)[0]
            for _ in range(2):
                _,_,bottom=self.skin_contact(p,s)
                toe_rotation=p[s+"Toes"].to_quaternion().copy()
                self.solve_leg(p,s,p[s+"Foot"].translation+Vector((0,0,desired_floor-bottom)),q)
                self.rotate(p,s+"Toes",toe_rotation@p[s+"Toes"].to_quaternion().inverted())
        up=(p["Neck"].translation-p["Chest"].translation).normalized()
        left=(p["LeftUpperArm"].translation-p["RightUpperArm"].translation).normalized()
        forward=left.cross(up).normalized()
        for s,sign,offset in SIDES:
            wave=math.cos(TAU*(phase+offset))
            theta=math.radians(-9-29*wave) if jog else -math.radians(18)*wave
            elbow=math.radians(92.5-12.5*wave) if jog else math.radians(13+4*math.sin(TAU*(phase+offset)-.3))
            upper,lower,hand=[s+n for n in ["UpperArm","LowerArm","Hand"]]
            l1=(p[lower].translation-p[upper].translation).length
            l2=(p[hand].translation-p[lower].translation).length
            d=(left*(sign*.07)+forward*math.sin(theta)-up*math.cos(theta)).normalized()
            self.aim(p,upper,lower,p[upper].translation+d*l1)
            d=(left*(sign*.035)+forward*math.sin(theta+elbow)-up*math.cos(theta+elbow)).normalized()
            self.aim(p,lower,hand,p[lower].translation+d*l2)
        self.relax_hands(p,jog)
        return p,contacts

    def _build_hip_profiles(self):
        # One high/low pair per step, globally lowered ONCE to fit the whole
        # reachable envelope. Never min() several competing curves at runtime.
        count=600
        for name in DURATIONS:
            jog=name=="Jog"
            offset=.16 if jog else -.025
            amplitude=.0175 if jog else .029
            center=self.rest["Hips"].translation.z-(.035 if jog else .028)
            excess=max(center-amplitude*math.cos(2*TAU*(i/count-offset))-self.gait(name,i/count,_raw_height=True) for i in range(count))
            self.hip_profiles[name]=(center-max(0,excess)-.001,amplitude,offset)

    def relax_hands(self,poses,jogging=False):
        for side,sign,_ in SIDES:
            for finger in ["Index","Middle","Ring","Little"]:
                for part,degrees in [("Proximal",22),("Intermediate",32),("Distal",18)]:
                    name=side+finger+part
                    axis=poses[name].to_3x3().col[0].normalized()
                    self.rotate(poses,name,Quaternion(axis,math.radians(degrees+(10 if jogging else 0))))
            name=side+"ThumbProximal";axis=poses[name].to_3x3().col[0].normalized()
            self.rotate(poses,name,Quaternion(axis,math.radians(12)))

    def support(self,name,phase):
        if name not in DUTIES:return ["sole","sole"]
        duty=DUTIES[name];result=[]
        for _,_,offset in SIDES:
            t=(phase+offset)%1
            if t>=duty:r="air"
            elif name=="Jog":r="sole" if t<.12 else "ball" if t<duty-.045 else "toes"
            else:r="heel" if t<.10 else "sole" if t<duty-.14 else "ball" if t<duty-.045 else "toes"
            result.append(r)
        return result

    def offsets(self,name,phase):
        if name not in DUTIES:
            return [[0,-self.rest[s+"Foot"].translation.z,0] for s,_,_ in SIDES]
        values=[]
        for s,_,offset in SIDES:
            _,_,_,v=self.foot(name,s,(phase+offset)%1)
            values.append([float(v[0]),float(v[2]),float(-v[1])])
        return values

    def skinned_sole(self,poses,side):
        points=np.zeros((len(self.sole_rest[side]),3))
        for bone,(indices,positions,weights) in self.skin_bindings[side].items():
            matrix=poses[bone]
            points[indices]+=positions@np.asarray(matrix.to_3x3(),dtype=float).T+np.asarray(matrix.translation,dtype=float)*weights[:,None]
        return points

    def skin_contact(self,poses,side):
        points=self.skinned_sole(poses,side)
        lo=float(points[:,2].min()); softness=.00035
        weights=np.exp(-(points[:,2]-lo)/softness)
        total=float(weights.sum()); weights/=total
        bottom=lo-softness*math.log(total)-.0007
        return points,weights,bottom

    def clear_blended_feet(self,poses):
        # Blend rotations in the real hierarchy before checking skin geometry.
        # A global-space position blend alone does not preserve limb lengths.
        for bone in self.hierarchy:
            if bone in ["Root","Hips"]:continue
            # Evaluate parents first, independently of dictionary ordering.
            parent=self.parents[bone]
            poses[bone].translation=poses[parent]@(self.rest[parent].inverted()@self.rest[bone].translation)
        for side,_,_ in SIDES:
            for _ in range(3):
                _,_,bottom=self.skin_contact(poses,side)
                # Smooth positive clearance avoids a hard kink where a blended
                # sole changes from floating to penetrating the floor.
                lift=.5*(-bottom+math.sqrt(bottom*bottom+1e-8))
                foot=poses[side+"Foot"]
                target=foot.translation+Vector((0,0,lift))
                toe_rotation=poses[side+"Toes"].to_quaternion().copy()
                self.solve_leg(poses,side,target,foot.to_quaternion())
                self.rotate(poses,side+"Toes",toe_rotation@poses[side+"Toes"].to_quaternion().inverted())
        return poses

    def contact_metadata(self,poses):
        offsets=[]; materials=[]
        for side,_,_ in SIDES:
            points,weights,bottom=self.skin_contact(poses,side)
            point=Vector((points*weights[:,None]).sum(axis=0))
            point.z=bottom
            foot=poses[side+"Foot"]
            offset=self.rest[side+"Foot"].to_3x3()@(foot.to_3x3().inverted()@(point-foot.translation))
            offsets.append([offset.x,offset.z,-offset.y])
            bindings={}
            for bone,(indices,positions,skin_weights) in self.skin_bindings[side].items():
                w=weights[indices]
                total=float(np.dot(w,skin_weights))
                if total<1e-12:continue
                position=self.rest[bone].to_3x3()@Vector((positions*w[:,None]).sum(axis=0))+self.rest[bone].translation*total
                bindings[bone]={"bone":bone,"position":[float(position.x),float(position.z),float(-position.y)],"weight":total}
            materials.append(list(bindings.values()))
        return offsets,materials

    def support_metadata(self):
        return {s:{r:[v.x,v.z,-v.y] for r,v in points.items()} for s,points in self.points.items()}
