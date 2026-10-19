class_name LocomotionGait
extends Resource
## Add a cycle without changing the motor. The metadata must contain its contacts.

@export var animation: StringName = &"Sprint"
@export var speed: float = 5.0
@export var stride_length: float = 3.1
@export var transition_prefix: StringName = &"Jog"
