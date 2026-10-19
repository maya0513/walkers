"""Relaxed locomotion in metres (-Y forward, Z up).

Continuous sole rocker geometry and C2 trajectory joins are shared with runtime
support metadata. References and artistic choices: docs/gait_reference.ja.md.
"""
import math
from mathutils import Vector, Quaternion

TAU = math.tau
SIDES = [("Left", 1, 0), ("Right", -1, .5)]
DURATIONS = {"Walk": 1.05, "Jog": .7}
SPEEDS = {"Walk": 1.4, "Jog": 2.8}
DUTIES = {"Walk": .56, "Jog": .36}


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


def swing_lift(u, height, apex):
    # A curved apex, with zero velocity AND acceleration at the ground joins.
    curvature = -8*height
    if u <= apex:
        return quintic(u/apex, 0, height, a1=curvature*apex*apex)
    width = 1-apex
    return quintic((u-apex)/width, height, 0, a0=curvature*width*width)


class SoleRocker:
    """Smooth lower sole envelope, with no-slip ankle travel integral.

    Soft minimum stays slightly below the skin, so the smooth virtual contact
    plane does not cut through the mesh. No heel/ball/toe pivot replacement.
    """
    def __init__(self, vertices):
        points = sorted(set((round(v.y, 8), round(v.z, 8)) for v in vertices))
        hull = []
        for p in points:
            while len(hull) > 1:
                a, b = hull[-2:]
                cross=(b[0]-a[0])*(p[1]-b[1])-(b[1]-a[1])*(p[0]-b[0])
                if cross > 0: break
                hull.pop()
            hull.append(p)
        self.points=hull
        self.x=sum(v.x for v in vertices)/len(vertices)
        self.step=math.radians(.1)
        self.first=math.radians(-30)
        self.integrals=[0.]
        for i in range(900):
            a=self.first+i*self.step
            self.integrals.append(self.integrals[-1]-self.step*(self.contact(a)[0]+4*self.contact(a+self.step*.5)[0]+self.contact(a+self.step)[0])/6)
        self.zero=self._integral(0)

    def contact(self, angle):
        s,c=math.sin(angle),math.cos(angle)
        heights=[s*y+c*z for y,z in self.points]
        lo=min(heights); softness=.0005
        weights=[math.exp(-(v-lo)/softness) for v in heights]
        total=sum(weights)
        height=-lo+softness*math.log(total)+.0007
        y=sum(w*p[0] for w,p in zip(weights,self.points))/total
        z=sum(w*p[1] for w,p in zip(weights,self.points))/total
        # A virtual point on the smooth supporting plane, below the sole skin.
        z+=(-height-(s*y+c*z))/c
        return height,Vector((self.x,y,z))

    def _integral(self, angle):
        index=(angle-self.first)/self.step
        i=max(0,min(len(self.integrals)-2,int(index)))
        a=self.first+i*self.step
        h0,p0=self.contact(a);h1,p1=self.contact(a+self.step)
        # d height / d angle for the soft lower envelope (virtual-plane offset
        # differs by <2mm; differentiating the soft weights is unnecessary here).
        def derivative(x):
            eps=1e-5
            return (self.contact(x+eps)[0]-self.contact(x-eps)[0])/(2*eps)
        return quintic(index-i,self.integrals[i],self.integrals[i+1],-h0*self.step,-h1*self.step,
                       -derivative(a)*self.step**2,-derivative(a+self.step)*self.step**2)

    def travel(self, angle):
        return self._integral(angle)-self.zero


class Author:
    def __init__(self, rest, body, solve_leg, aim, rotate):
        self.rest,self.solve_leg,self.aim,self.rotate=rest,solve_leg,aim,rotate
        self.feet={s:rest[s+"Foot"].to_quaternion() for s,_,_ in SIDES}
        self.soles={s:[v.co.copy()-rest[s+"Foot"].translation for v in body.data.vertices
                       if v.co.z<.13 and v.co.x*sign>0] for s,sign,_ in SIDES}
        self.rockers={s:SoleRocker(self.soles[s]) for s,_,_ in SIDES}
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

    def foot(self,name,side,t):
        jog=name=="Jog";duty=DUTIES[name];stride=DURATIONS[name]*SPEEDS[name]
        front=-(.32 if jog else .36)*stride*duty
        back=front+stride*duty
        touchdown=math.radians(1.5 if jog else -13)
        push=math.radians(32 if jog else 45)
        push_rate=math.radians(150 if jog else 105)
        rocker=self.rockers[side]
        if t<duty:
            settle=.065 if jog else .12
            leave=duty-(.13 if jog else .20)
            roll=touchdown*(1-smooth(t/settle))
            if t>leave:
                roll+=quintic((t-leave)/(duty-leave),0,push,v1=push_rate*(duty-leave))
            y=front+stride*t+rocker.travel(roll)
            height=0
            contact=smooth(t/.035)*(1-smooth((t-(duty-.045))/.045))
        else:
            u=(t-duty)/(1-duty)
            roll=quintic(u/.45,push,math.radians(7 if jog else 10),v0=push_rate*(1-duty)*.45) if u<.45 else quintic((u-.45)/.55,math.radians(7 if jog else 10),touchdown)
            tangent=stride*(1-duty)
            end=front+rocker.travel(touchdown)
            # The rear heel continues rising through toe-off. Preserve this
            # velocity while recovering early and retracting before touchdown.
            turn=.80
            width=1-turn
            minimum=end-.4*tangent*width
            curvature=.5*tangent/width
            initial=(stride-rocker.contact(push)[0]*push_rate)*(1-duty)
            eps=1e-5
            height_derivative=(rocker.contact(push+eps)[0]-rocker.contact(push-eps)[0])/(2*eps)
            initial_acceleration=-height_derivative*push_rate**2*(1-duty)**2
            if u<turn:
                y=quintic(u/turn,back+rocker.travel(push),minimum,initial*turn,0,initial_acceleration*turn*turn,curvature*turn*turn)
            else:
                y=quintic((u-turn)/width,minimum,end,0,tangent*width,curvature*width*width,0)
            height=swing_lift(u,.205 if jog else .070,.40 if jog else .48)
            contact=0
        support,pivot=rocker.contact(roll)
        return Vector((0,y,support+height)),Quaternion(Vector((1,0,0)),roll),contact,pivot

    def gait(self,name,phase,_raw_height=False):
        jog=name=="Jog";phase%=1
        p={n:m.copy() for n,m in self.rest.items()}
        lateral=(.009 if jog else .014)*math.sin(TAU*phase)
        self.rotate(p,"Hips",Quaternion(Vector((1,0,0)),math.radians(4.0 if jog else .8)))
        self.rotate(p,"Hips",Quaternion(Vector((0,0,1)),math.radians(3 if jog else 2.5)*math.sin(TAU*phase)))
        self.rotate(p,"Chest",Quaternion(Vector((0,0,1)),-math.radians(5 if jog else 4)*math.sin(TAU*phase)))
        # Small thorax compliance rather than a rigid torso block.
        if jog:self.rotate(p,"Chest",Quaternion(Vector((1,0,0)),math.radians(.7)*math.sin(2*TAU*(phase-.12))))
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
            toe=s+"Toes"
            self.rotate(p,toe,self.rest[toe].to_quaternion()@p[toe].to_quaternion().inverted())
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
            values.append([v.x,v.z,-v.y])
        return values

    def support_metadata(self):
        return {s:{r:[v.x,v.z,-v.y] for r,v in points.items()} for s,points in self.points.items()}
