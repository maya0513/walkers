"""Authored relaxed locomotion in Blender metres (-Y forward, Z up).

References and choices are explained for humans in docs/gait_reference.ja.md.
Quaternius stays in the .blend as a reference, not an uncorrected body rotation.
"""
import math
from mathutils import Vector, Quaternion

TAU = math.tau
SIDES = [("Left", 1, 0), ("Right", -1, .5)]
DURATIONS = {"Walk": .9, "Jog": .7}
SPEEDS = {"Walk": 1.4, "Jog": 2.8}
DUTIES = {"Walk": .56, "Jog": .36}


def smooth(t):
    t = max(0., min(1., t))
    return t*t*(3-2*t)


class Author:
    def __init__(self, rest, body, solve_leg, aim, rotate):
        self.rest, self.solve_leg, self.aim, self.rotate = rest, solve_leg, aim, rotate
        self.feet = {s: rest[s+"Foot"].to_quaternion() for s,_,_ in SIDES}
        self.soles = {s: [v.co.copy()-rest[s+"Foot"].translation for v in body.data.vertices
                          if v.co.z < .13 and v.co.x*sign > 0] for s,sign,_ in SIDES}
        self.points = {}
        for s,_,_ in SIDES:
            points = self.soles[s]
            center_x = sum(v.x for v in points)/len(points)
            # Lower skin envelope near the centreline, heel, metatarsal and toe.
            lo, hi = min(v.y for v in points), max(v.y for v in points)
            positions = {"heel":hi-.015,"sole":lo+(hi-lo)*.55,"ball":lo+.065,"toes":lo+.018}
            self.points[s] = {}
            for region,y in positions.items():
                candidates = [v for v in points if abs(v.y-y)<.025 and abs(v.x-center_x)<.035]
                if not candidates: candidates = points
                self.points[s][region] = min(candidates,key=lambda v:v.z).copy()
        self.idle = self._neutral()
        self.hip_profiles = {}
        self._build_hip_profiles()

    def _neutral(self):
        p = {n:m.copy() for n,m in self.rest.items()}
        for s,sign,_ in SIDES:
            upper,lower,hand = [s+n for n in ["UpperArm","LowerArm","Hand"]]
            l1=(p[lower].translation-p[upper].translation).length
            l2=(p[hand].translation-p[lower].translation).length
            d=Vector((sign*.065,0,-1)).normalized()
            self.aim(p,upper,lower,p[upper].translation+d*l1)
            d=Vector((sign*.035,-.08,-1)).normalized()
            self.aim(p,lower,hand,p[lower].translation+d*l2)
            ankle=p[s+"Foot"].translation.copy()
            # Slightly narrower than hip joints; straight, relaxed knees.
            ankle.x=sign*.078
            ankle.y=0
            ankle.z=-min(v.z for v in self.soles[s])+.003
            self.solve_leg(p,s,ankle,self.feet[s])
        self.relax_hands(p)
        return p

    def standing(self, phase=0):
        return {n:m.copy() for n,m in self.idle.items()}

    def gait(self, name, phase, _raw_height=False):
        jog=name=="Jog"
        phase%=1
        p={n:m.copy() for n,m in self.rest.items()}
        stride=DURATIONS[name]*SPEEDS[name]
        duty=DUTIES[name]
        # Two steps in a complete same-foot-contact to same-foot-contact cycle.
        lateral=(.010 if jog else .016)*math.sin(TAU*phase)
        lean=math.radians(5.0 if jog else 1.0)
        self.rotate(p,"Hips",Quaternion(Vector((1,0,0)),lean))
        self.rotate(p,"Hips",Quaternion(Vector((0,0,1)),math.radians(3 if jog else 2.5)*math.sin(TAU*phase)))
        self.rotate(p,"Chest",Quaternion(Vector((0,0,1)),-math.radians(5 if jog else 4)*math.sin(TAU*phase)))
        for n in p:
            if n!="Root":p[n].translation.x+=lateral
        targets=[]
        contacts=[]
        regions=[]
        for s,sign,offset in SIDES:
            t=(phase+offset)%1
            front=-(.37 if jog else .44)*stride*duty
            back=front+stride*duty
            if t<duty:
                y=front+stride*t
                if jog:
                    # Midfoot touch, compliant heel settling, then forefoot push.
                    roll=math.radians(1.5)*(1-smooth(t/.055))+math.radians(24)*smooth((t-(duty-.13))/.13)
                    region="sole" if t<.12 else "ball" if t<duty-.045 else "toes"
                else:
                    roll=-math.radians(13)*(1-smooth(t/.105))+math.radians(30)*smooth((t-(duty-.16))/.16)
                    region="heel" if t<.10 else "sole" if t<duty-.14 else "ball" if t<duty-.045 else "toes"
                height=0
                contact=smooth(t/.025)*(1-smooth((t-(duty-.045))/.045))
            else:
                u=(t-duty)/(1-duty)
                tangent=stride*(1-duty)
                y=(2*u**3-3*u*u+1)*back+(u**3-2*u*u+u)*tangent+(-2*u**3+3*u*u)*front+(u**3-u*u)*tangent
                height=(.255 if jog else .075)*math.sin(math.pi*u)
                roll=math.radians(24 if jog else 30)*(1-smooth(u/.65))-(0 if jog else math.radians(13))*smooth((u-.60)/.40)
                region="air"
                contact=0
            q=Quaternion(Vector((1,0,0)),roll)
            support=-min((q@v).z for v in self.soles[s])
            # Rolling about heel/forefoot moves the ankle forward relative to
            # the planted patch. Do not model the ankle as a sliding point foot.
            pivot_name = (region if region != "air" else "ball" if roll >= 0 else "heel")
            pivot = self.points[s][pivot_name]
            y += pivot.y-(q@pivot).y
            targets.append((s,Vector((sign*(.02 if jog else .05),y,support+height)),q@self.feet[s],t))
            contacts.append(round(contact,5))
            regions.append(region)
        # Reach-based pelvis, with running spring compression during support.
        # No unconditional sinking of the original retargeted pelvis.
        hip_z=self.rest["Hips"].translation.z
        desired=hip_z+(.012 if jog else -.008)*math.cos(2*TAU*(phase-.20))
        for s,target,_,t in targets:
            h=p[s+"UpperLeg"].translation
            k=p[s+"LowerLeg"].translation
            a=p[s+"Foot"].translation
            l1,l2=(k-h).length,(a-k).length
            knee=math.radians((12+22*math.sin(math.pi*t/duty)) if jog and t<duty else 5)
            reach=math.sqrt(l1*l1+l2*l2+2*l1*l2*math.cos(knee))
            horizontal=(target.x-h.x)**2+(target.y-h.y)**2
            ceiling=target.z+math.sqrt(max(.01,reach*reach-horizontal))-(h.z-hip_z)
            desired=min(desired,ceiling)
        # Swing poses continue smoothly through the flight window.
        if jog:
            compression=.035*math.sin(TAU*(phase+.10))**2
            desired=min(desired,hip_z-.010-compression)
        if _raw_height:
            return desired
        profile = self.hip_profiles[name]
        index=phase*len(profile)
        i=int(index)%len(profile)
        value=profile[i]*(1-index%1)+profile[(i+1)%len(profile)]*(index%1)
        desired=min(desired,value)
        shift=Vector((0,0,desired-p["Hips"].translation.z))
        for n in p:
            if n!="Root":p[n].translation+=shift
        for s,target,q,t in targets:
            self.solve_leg(p,s,target,q)
            # Keep forefoot deformation neutral; support rolls at the ankle.
            # A gentle toe extension accompanies toe-off rather than forcing flat soles.
            toe=s+"Toes"
            toe_rot=self.rest[toe].to_quaternion()
            self.rotate(p,toe,toe_rot@p[toe].to_quaternion().inverted())
        for s,sign,offset in SIDES:
            theta=-(math.radians(22 if jog else 16))*math.cos(TAU*(phase+offset))
            elbow=math.radians(78 if jog else 12)
            upper,lower,hand=[s+n for n in ["UpperArm","LowerArm","Hand"]]
            l1=(p[lower].translation-p[upper].translation).length
            l2=(p[hand].translation-p[lower].translation).length
            d=Vector((sign*.065,-math.sin(theta),-math.cos(theta))).normalized()
            self.aim(p,upper,lower,p[upper].translation+d*l1)
            d=Vector((sign*.025,-math.sin(theta+elbow),-math.cos(theta+elbow))).normalized()
            self.aim(p,lower,hand,p[lower].translation+d*l2)
        self.relax_hands(p, jog)
        return p,contacts

    def _build_hip_profiles(self):
        # Start with anatomical reach ceilings over the WHOLE cycle, including
        # landing anticipation. A conservative smooth envelope avoids a late
        # pelvis drop and retains reachable, unstretched support legs.
        count=240
        for name in DURATIONS:
            raw=[self.gait(name,i/count,_raw_height=True) for i in range(count)]
            period=DURATIONS[name]
            envelope=[]
            if name == "Walk":
                # Walking vaults over the support leg: highest near midstance,
                # lower in double support. Derive the low point from heel-strike
                # reach; do not spread that minimum over the whole stance.
                low=raw[0]
                high=self.rest["Hips"].translation.z-.004
                envelope=[low+(high-low)*math.sin(TAU*i/count)**2 for i in range(count)]
            else:
                acceleration=8.0
                for i in range(count):
                    envelope.append(min(raw[j]+.5*acceleration*(min(abs(i-j),count-abs(i-j))*period/count)**2 for j in range(count)))
            radius=8
            weights=[math.exp(-.5*(j/3.0)**2) for j in range(-radius,radius+1)]
            filtered=[sum(envelope[(i+j)%count]*w for j,w in zip(range(-radius,radius+1),weights))/sum(weights) for i in range(count)]
            overshoot=max(0,max(value-ceiling for value,ceiling in zip(filtered,raw)))+.0005
            self.hip_profiles[name]=[value-overshoot for value in filtered]

    def relax_hands(self, poses, jogging=False):
        for side,sign,_ in SIDES:
            for finger in ["Index","Middle","Ring","Little"]:
                for part,degrees in [("Proximal",22),("Intermediate",32),("Distal",18)]:
                    name=side+finger+part
                    axis=poses[name].to_3x3().col[0].normalized()
                    self.rotate(poses,name,Quaternion(axis,math.radians(degrees+(10 if jogging else 0))))
            # Thumb rests alongside the fingers instead of a spread T-pose.
            name=side+"ThumbProximal"
            axis=poses[name].to_3x3().col[0].normalized()
            self.rotate(poses,name,Quaternion(axis,math.radians(12)))

    def support(self,name,phase):
        if name not in DUTIES:return ["sole","sole"]
        duty=DUTIES[name]; result=[]
        for _,_,offset in SIDES:
            t=(phase+offset)%1
            if t>=duty:region="air"
            elif name=="Jog":region="sole" if t<.12 else "ball" if t<duty-.045 else "toes"
            else:region="heel" if t<.10 else "sole" if t<duty-.14 else "ball" if t<duty-.045 else "toes"
            result.append(region)
        return result

    def support_metadata(self):
        # Rest-skeleton-space offset from ankle; Godot X,Y,Z = Blender X,Z,-Y.
        return {s:{r:[v.x,v.z,-v.y] for r,v in points.items()} for s,points in self.points.items()}
