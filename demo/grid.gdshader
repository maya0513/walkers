shader_type spatial;
render_mode diffuse_burley;
uniform vec4 surface_color : source_color = vec4(0.61, 0.65, 0.65, 1.0);
uniform vec4 line_color : source_color = vec4(0.48, 0.54, 0.54, 1.0);
varying vec3 world_position;
void vertex() { world_position = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }
void fragment() {
    vec2 grid = abs(fract(world_position.xz + 0.5) - 0.5) / max(fwidth(world_position.xz), vec2(0.0001));
    float line = 1.0 - min(min(grid.x, grid.y), 1.0);
    float fade = 1.0 - smoothstep(8.0, 28.0, length(world_position.xz));
    ALBEDO = mix(surface_color.rgb, line_color.rgb, line * 0.4 * fade);
    ROUGHNESS = 0.85;
}

