"""BlendClone NATIVE render/preview_notes.py — how CPU preview maps to viewport/glwidget.py.

MODES (viewport/glwidget.py shader mapping):
  solid    — flat lambert + matcap-ish hemisphere ambient; uses Material.base_color
             only (metallic/roughness ignored). 1 hemisphere ambient + 0 dir lights.
  studio   — hemisphere ambient + 1 key dir light (dir_light [0.5,0.8,0.6], I=1.0);
             Blinn-Phong specular from roughness (shininess = mix(128, 8, roughness)).
             Matches shade_lambert() + single dir light in pathtracer.py.
  rendered — full pathtracer.render_tile() linear-HDR -> color.float_to_uint8()
             (Reinhard exposure + linear->sRGB). spp=1 draft, spp=4+ refine.

LIGHTS:
  hemisphere (sky [0.6,0.7,0.9]*0.5 + ground [0.2,0.18,0.15]*0.3, fixed in shader)
  + 1 dir key light from render/lights.py dir_light(). Max 8 via set_lights();
  point/sun supported in data but shadows ignored in M1 (same as JS reference).

CAPTURE:
  PNG export via QWidget.grabFramebuffer() AFTER makeCurrent()+updateGL flush;
  buffer is already sRGB uint8 (no double conversion). Offscreen tile path uses
  render_tile() + float_to_uint8() directly to QImage/PNG without GL.

No runtime code here beyond constants (keeps import Qt/GL-free).
"""

SOLID_MODE = "solid"
STUDIO_MODE = "studio"
RENDERED_MODE = "rendered"

HEMISPHERE_SKY = (0.6, 0.7, 0.9)
HEMISPHERE_GROUND = (0.2, 0.18, 0.15)
KEY_LIGHT_DIR = (0.5, 0.8, 0.6)
KEY_LIGHT_INTENSITY = 1.0

PREVIEW_EXPOSURE = 0.0
DRAFT_SPP = 1
REFINE_SPP = 4
