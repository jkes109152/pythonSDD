"""Shared lighting shader for the 3D air-defense scene.

The built-in Ursina shadow shader provides diffuse lighting and shadow maps,
but does not include a specular term.  This small adapter keeps that shader's
stable vertex/shadow contract and adds a restrained sun glint so the converted
meshes keep visible form instead of becoming flat blocks of colour.
"""

from ursina import color
from ursina.shader import Shader
from ursina.shaders import lit_with_shadows_shader


_SPECULAR_UNIFORMS = """
uniform vec4 sun_specular_color;
uniform float sun_specular_strength;
uniform float sun_specular_shininess;
"""

_SPECULAR_TERM = """
        // Blinn-Phong highlight in the same view space as the shadow shader.
        // Restrict it to lit faces so the highlight cannot brighten shadows.
        vec3 view_direction = normalize(-vertex_position);
        vec3 halfway_direction = normalize(L + view_direction);
        float specular_factor = pow(
            max(dot(normal_vector, halfway_direction), 0.0),
            sun_specular_shininess
        );
        float facing_light = step(0.0, dot(normal_vector, L));
        color.rgb += shadow * facing_light * specular_factor
            * sun_specular_color.rgb * sun_specular_strength;
"""


def _fragment_with_sun_glint() -> str:
    """Extend the pinned Ursina shadow fragment shader without duplicating it."""

    fragment = lit_with_shadows_shader.fragment
    uniform_marker = "uniform int shadow_samples;"
    if uniform_marker not in fragment:
        raise RuntimeError("Ursina shadow shader no longer exposes shadow_samples")
    fragment = fragment.replace(
        uniform_marker,
        uniform_marker + _SPECULAR_UNIFORMS,
        1,
    )
    lighting_marker = "        color.rgb += light_contribution - converted_shadow_color;\n"
    if lighting_marker not in fragment:
        raise RuntimeError("Ursina shadow shader lighting block changed")
    return fragment.replace(lighting_marker, lighting_marker + _SPECULAR_TERM, 1)


_DEFAULT_INPUT = dict(lit_with_shadows_shader.default_input)
_DEFAULT_INPUT.update(
    {
        # Neutral charcoal shadows avoid the blue cast of Ursina's example
        # default and leave the per-instance gameplay tint intact.
        "shadow_color": color.rgba(0.06, 0.07, 0.09, 0.58),
        "shadow_bias": 0.0015,
        "shadow_blur": 0.004,
        "shadow_samples": 2,
        "sun_specular_color": color.rgba(1.0, 0.94, 0.82, 1.0),
        "sun_specular_strength": 0.42,
        "sun_specular_shininess": 28.0,
    }
)


lit_with_sun_specular_shader = Shader(
    language=lit_with_shadows_shader.language,
    name="air_defense_lit_with_sun_specular",
    vertex=lit_with_shadows_shader.vertex,
    fragment=_fragment_with_sun_glint(),
    default_input=_DEFAULT_INPUT,
)
lit_with_sun_specular_shader.continuous_input.update(
    lit_with_shadows_shader.continuous_input
)


__all__ = ["lit_with_sun_specular_shader"]
