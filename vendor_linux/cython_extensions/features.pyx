# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True, initializedcheck=False, infer_types=True
"""Full-game observation features in the style of AlphaStar / DI-Star.

Three modalities, collected from a ``python-sc2`` ``BotAI`` instance:

* **entities** — one flat set of up to ``MAX_ENTITIES`` visible units
  (self, ally, neutral, enemy). Continuous state lives in
  ``entity_features`` (ratios / log-scales in ``[0, 1]``); discrete state
  lives in ``entity_categorical`` as integer indices (``0`` = none/unknown)
  meant to be embedded downstream. This mirrors the AlphaStar raw
  interface and DI-Star ``entity_list``: no one-hot expansion here.
* **spatial** — ``(C, 128, 128)`` map stack: static terrain planes plus
  unit-density / hp-mass *minimap feature layers* (PySC2-style inputs, same
  role as AlphaStar's seven minimap planes). The learned scatter connection
  itself (transformer embeddings → map cells) lives in the model, not here:
  ``entity_positions`` + ``entity_mask`` are its inputs (see the private
  note ``notes/scatter_connection.md`` for the reference op).
* **scalar** — ``(D,)`` global player vector: game time, log-scaled
  economy, supply, races, hashed upgrades, alerts, spawn, score stats
  (split killed units/structures, lost, spent).

Facing is encoded as a sin/cos pair (no 1.0 -> 0.0 wrap discontinuity).
Mined resources use an initial-contents table (1800 minerals / 2250
vespene, small-field variants excepted) mirroring AlphaStar's
``INITIAL_RESOURCE_CONTENTS``.

All spatial planes are ``float32`` in ``[0, 1]`` and already masked to the
playable area. ``entity_mask`` marks real rows (``1.0``) vs padding.
``unit_tags[i]`` is the game tag of entity row ``i``.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

cimport numpy as cnp

from libc.math cimport cos, log, sin
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.units import Units

# -----------------------------------------------------------------------------
# ID tables. Index 0 is reserved for none/unknown/padding everywhere, so every
# categorical column is a plain embedding lookup (no one-hot blowup even for
# the ~1380 abilities / ~2000 unit types).
# -----------------------------------------------------------------------------
ABILITY_IDS = [ability.value for ability in AbilityId]
BUFF_IDS = [buff.value for buff in BuffId]
UNIT_TYPE_IDS = [unit_type.value for unit_type in UnitTypeId]
UPGRADE_IDS = [upgrade.value for upgrade in UpgradeId]

ABILITY_DICT = {ability_id: i + 1 for i, ability_id in enumerate(ABILITY_IDS)}
BUFF_DICT = {buff_id: i + 1 for i, buff_id in enumerate(BUFF_IDS)}
UNIT_TYPE_DICT = {unit_id: i + 1 for i, unit_id in enumerate(UNIT_TYPE_IDS)}
UPGRADE_DICT = {upgrade_id: i + 1 for i, upgrade_id in enumerate(UPGRADE_IDS)}

NUM_ABILITIES = len(ABILITY_IDS) + 1
NUM_BUFFS = len(BUFF_IDS) + 1
NUM_UNIT_TYPES = len(UNIT_TYPE_IDS) + 1
NUM_UPGRADES = len(UPGRADE_IDS) + 1

# -----------------------------------------------------------------------------
# Layout constants.
# -----------------------------------------------------------------------------
MAX_ENTITIES = 512  # single AlphaStar-style entity pool (all alliances)
TARGET_SPATIAL_SIZE = (128, 128)  # AlphaStar minimap resolution

# Entity numeric columns (continuous, [0, 1]).
cdef int EN_X = 0
cdef int EN_Y = 1
cdef int EN_FACING_SIN = 2  # sin(facing) * 0.5 + 0.5
cdef int EN_FACING_COS = 3  # cos(facing) * 0.5 + 0.5
cdef int EN_HP = 4
cdef int EN_SHIELD = 5
cdef int EN_ENERGY = 6
cdef int EN_RADIUS = 7
cdef int EN_CARGO_TAKEN = 8
cdef int EN_CARGO_MAX = 9
cdef int EN_BUILD_PROGRESS = 10
cdef int EN_WEAPON_CD = 11
cdef int EN_SPEED = 12
cdef int EN_MINERALS = 13
cdef int EN_VESPENE = 14
cdef int EN_HARVESTERS = 15
cdef int EN_BUFF_DUR0 = 16
cdef int EN_BUFF_DUR1 = 17
cdef int EN_ORDER_X = 18
cdef int EN_ORDER_Y = 19
cdef int EN_ENGAGED = 20
cdef int EN_ORDER_PROGRESS = 21  # first order progress in [0, 1]
cdef int EN_MINED = 22  # log-norm mined resources (initial - current)
cdef int EN_DETECT = 23  # log-norm detect_range / 16
cdef int EN_POS_Z = 24  # clip(pos.z / 16)
ENTITY_NUM_DIM = 25

# Entity categorical columns (integer indices, 0 = none/unknown).
cdef int EC_TYPE = 0
cdef int EC_ALLIANCE = 1
cdef int EC_DISPLAY = 2
cdef int EC_CLOAK = 3
cdef int EC_ORDER_ABILITY = 4
cdef int EC_ORDER_TARGET_UNIT = 5
cdef int EC_BUFF0 = 6
cdef int EC_BUFF1 = 7
cdef int EC_FLYING = 8
cdef int EC_BURROWED = 9
cdef int EC_HALLUC = 10
cdef int EC_ACTIVE = 11
cdef int EC_POWERED = 12
cdef int EC_SELECTED = 13
cdef int EC_ATK_UP = 14
cdef int EC_ARMOR_UP = 15
cdef int EC_SHIELD_UP = 16
cdef int EC_ORDER_LENGTH = 17  # capped queued order count, 0-8
cdef int EC_ON_SCREEN = 18  # AlphaStar SELECTABLE mask input
cdef int EC_BLIP = 19  # sensor-tower snapshot (fog blip)
cdef int EC_IN_CARGO = 20  # transported (member of a passenger tag set)
cdef int EC_ADDON = 21  # addon unit-type idx, 0 = none, 1 = present-unknown
cdef int EC_ENGAGED_TYPE = 22  # engaged-target unit-type idx, 0 = none/unknown
cdef int EC_OWNER = 23  # proto.owner capped to 0-15 (e.g. neutral ~= 15)
ENTITY_CAT_DIM = 24

SPATIAL_CHANNEL_NAMES = [
    "height",          # 0: min-max normalised terrain height
    "pathable",        # 1: pathing grid as exposed by python-sc2
    "placement",       # 2: placement grid as exposed by python-sc2
    "playable",        # 3: playable-area mask
    "visibility",      # 4: 0=hidden, 0.5=fogged, 1=visible
    "creep",           # 5: zerg creep presence
    "power",           # 6: protoss psionic-matrix coverage (from sources)
    "rel_self",        # 7: binary presence, own units
    "rel_ally",        # 8: binary presence, allied units
    "rel_neutral",     # 9: binary presence, neutral units/resources
    "rel_enemy",       # 10: binary presence, enemy units
    "density_self",    # 11: log count of own+allied units
    "density_enemy",   # 12: log count of enemy units
    "hp_self",         # 13: log hp+shield mass of own+allied units
    "hp_enemy",        # 14: log hp+shield mass of enemy units
    "selected",        # 15: selected-units density
    "unit_buffs",      # 16: density of units carrying buffs
    "spawn",           # 17: start-location marker (camera proxy)
    "effects",         # 18: log density of persistent-effect circles
                       #     (storms, biles, nukes, liberator zones).
                       #     Nearly all such effects damage both sides,
                       #     so no alliance split: this plane means danger.
]
NUM_SPATIAL_CHANNELS = len(SPATIAL_CHANNEL_NAMES)

SCALAR_FEATURE_NAMES = [
    "game_loop",            # 0: state.game_loop / 45000 (~33 min)
    "game_time",            # 1: ai.time / 1800
    "minerals",             # 2: log1p / log1p(20000)
    "vespene",              # 3: log1p / log1p(20000)
    "supply_used",          # 4: / 200
    "supply_cap",           # 5: / 200
    "supply_left",          # 6: / 200
    "supply_army",          # 7: / 200
    "supply_workers",       # 8: / 200
    "larva",                # 9: / 20 (0 for non-Zerg)
    "workers",              # 10: / 100
    "townhalls",            # 11: / 10
    "gas_buildings",        # 12: / 20
    "idle_workers",         # 13: / 50
    "army_count",           # 14: / 200
    "enemy_count",          # 15: / 200
    "army_hp",              # 16: log hp+shield mass / log1p(20000)
    "enemy_hp",             # 17: log hp+shield mass / log1p(20000)
    "race_self_terran",     # 18: one-hot
    "race_self_zerg",       # 19: one-hot
    "race_self_protoss",    # 20: one-hot
    "race_self_random",     # 21: one-hot (random / other)
    "race_enemy_terran",    # 22: one-hot
    "race_enemy_zerg",      # 23: one-hot
    "race_enemy_protoss",   # 24: one-hot
    "race_enemy_random",    # 25: one-hot (random / other)
    "upgrades_count",       # 26: log1p(n) / log1p(64)
    "upgrade_hash_0",       # 27-34: hashed multi-hot, 8 buckets
    "upgrade_hash_1",
    "upgrade_hash_2",
    "upgrade_hash_3",
    "upgrade_hash_4",
    "upgrade_hash_5",
    "upgrade_hash_6",
    "upgrade_hash_7",
    "alerts_count",         # 35: log1p(n) / log1p(8)
    "alert_severity",       # 36: max alert id / 25, clipped
    "spawn_x",              # 37: start-location x (camera proxy)
    "spawn_y",              # 38: start-location y (camera proxy)
    "score_total",          # 39: log total value / log1p(20000)
    "killed_units",         # 40: log killed unit value / log1p(10000)
    "killed_structures",    # 41: log killed structure value / log1p(10000)
    "collected_minerals",   # 42: log / log1p(50000)
    "collected_vespene",    # 43: log / log1p(50000)
    "collection_rate_min",  # 44: log / log1p(5000)
    "collection_rate_ves",  # 45: log / log1p(5000)
    "apm",                  # 46: log current apm / log1p(1000)
    "effect_count",         # 47: log1p(n persistent effects) / log1p(8)
    "lost_value",           # 48: log lost minerals+vespene / log1p(50000)
    "spent_value",          # 49: log spent minerals+vespene / log1p(50000)
]
SCALAR_DIM = len(SCALAR_FEATURE_NAMES)

# Normalisation scales (documented once, used everywhere).
cdef double SCALE_MINERALS = 20000.0
cdef double SCALE_HP_MASS = 20000.0
cdef double SCALE_GAME_LOOP = 45000.0
cdef double SCALE_GAME_TIME = 1800.0
cdef double SCALE_SUPPLY = 200.0
cdef double SCALE_DENSITY = 32.0
cdef double SCALE_CELL_HP = 4000.0
cdef double SCALE_WEAPON_CD = 50.0
cdef double SCALE_SPEED = 8.0
cdef double SCALE_RESOURCE_CONTENTS = 2500.0
cdef double SCALE_BUFF_DURATION = 60.0
cdef double SCALE_CARGO = 8.0
cdef double SCALE_SPAWN_RADIUS = 4.0
cdef double SCALE_DETECT = 16.0
cdef double SCALE_POS_Z = 16.0
cdef double SCALE_ORDER_LENGTH = 8.0
cdef double SCALE_KILLED = 10000.0
cdef double SCALE_VALUE_WIDE = 50000.0
cdef double TWO_PI = 6.283185307179586


# -----------------------------------------------------------------------------
# Numeric helpers (nogil, branch-light).
# -----------------------------------------------------------------------------


cdef inline double _clip01_c(double v) noexcept nogil:
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


cdef inline double _safe_ratio_c(double num, double den) noexcept nogil:
    if den <= 1e-6:
        return 0.0
    return _clip01_c(num / den)


cdef inline double _log_norm_c(double value, double scale) noexcept nogil:
    cdef double denom = log(1.0 + scale)
    if value < 0.0:
        value = 0.0
    if denom <= 0.0:
        return 0.0
    return _clip01_c(log(1.0 + value) / denom)


cpdef double _safe_ratio(double num, double den):
    """Clipped ``num / den`` in ``[0, 1]`` (``0.0`` when ``den <= 0``)."""
    return _safe_ratio_c(num, den)


cpdef double _log_norm(double value, double scale):
    """``log1p(value) / log1p(scale)`` clipped to ``[0, 1]``."""
    return _log_norm_c(value, scale)


cpdef cnp.ndarray _np_one_hot(cnp.ndarray targets, int nb_classes):
    """One-hot encode integer ``targets`` into ``(*shape, nb_classes)``."""
    targ = np.ascontiguousarray(targets, dtype=np.int64)
    cdef cnp.int64_t[:] tflat = targ.ravel()
    cdef Py_ssize_t n = tflat.shape[0]
    cdef cnp.ndarray[cnp.float32_t, ndim=2] out = np.zeros(
        (n, nb_classes), dtype=np.float32
    )
    cdef cnp.float32_t[:, :] out_view = out
    cdef Py_ssize_t i
    cdef cnp.int64_t idx
    for i in range(n):
        idx = tflat[i]
        if 0 <= idx < nb_classes:
            out_view[i, idx] = 1.0
    return out.reshape(list(targ.shape) + [nb_classes])


cpdef tuple _unit_pos_2d(u):
    return (u._proto.pos.x, u._proto.pos.y)


cpdef tuple _normalize_pos(double x, double y, double map_width, double map_height):
    """Normalise map coordinates to ``[0, 1]``."""
    cdef double denom_x = map_width - 1.0
    cdef double denom_y = map_height - 1.0
    if denom_x < 1.0:
        denom_x = 1.0
    if denom_y < 1.0:
        denom_y = 1.0
    return x / denom_x, y / denom_y


cpdef _pad_to_length(object arr, int target_len):
    """Pad ``arr`` along axis 0 with zeros up to ``target_len``."""
    cdef tuple shp = tuple(np.shape(arr))
    cdef int n = shp[0] if shp else 0
    if n >= target_len:
        return arr[:target_len]
    pad = np.zeros((target_len - n,) + shp[1:], dtype=np.asarray(arr).dtype)
    return np.concatenate([arr, pad], axis=0)


cpdef cnp.ndarray _build_mask(int n, int max_n):
    """``1.0`` for the first ``min(n, max_n)`` rows, else ``0.0``."""
    cdef int fill_n = n if n < max_n else max_n
    mask = np.zeros((max_n,), dtype=np.float32)
    if fill_n > 0:
        mask[:fill_n] = 1.0
    return mask


cpdef cnp.ndarray _ensure_hw_grid(
    cnp.ndarray grid, double map_width, double map_height, str name
):
    """Return ``grid`` as ``(H, W)`` with y as rows and x as columns."""
    cdef int h = <int>map_height
    cdef int w = <int>map_width
    cdef cnp.npy_intp g0 = grid.shape[0]
    cdef cnp.npy_intp g1 = grid.shape[1]
    if g0 == h and g1 == w:
        return grid
    if g0 == w and g1 == h:
        return grid.T
    raise ValueError(f"{name} has shape {(g0, g1)}, expected {(h, w)} or {(w, h)}.")


cpdef cnp.ndarray _resize_nearest(cnp.ndarray stack, tuple size):
    """Nearest-neighbour resize of a ``(C, H, W)`` stack.

    Nearest (not bilinear) is deliberate: binary masks, presence planes and
    density counts must not bleed fractional ghosts into neighbours.
    """
    cdef cnp.ndarray[cnp.float32_t, ndim=3] src = np.ascontiguousarray(
        stack, dtype=np.float32
    )
    cdef int c = src.shape[0]
    cdef int h = src.shape[1]
    cdef int w = src.shape[2]
    cdef int new_h = size[0]
    cdef int new_w = size[1]
    if (h, w) == (new_h, new_w):
        return src

    cdef cnp.ndarray[cnp.int64_t, ndim=1] ys = (
        (np.arange(new_h, dtype=np.float64) * h / new_h).astype(np.int64)
    )
    cdef cnp.ndarray[cnp.int64_t, ndim=1] xs = (
        (np.arange(new_w, dtype=np.float64) * w / new_w).astype(np.int64)
    )
    np.clip(ys, 0, h - 1, out=ys)
    np.clip(xs, 0, w - 1, out=xs)
    return np.ascontiguousarray(src[:, ys[:, None], xs[None, :]], dtype=np.float32)


cdef void _splat_disc(
    cnp.float32_t[:, :] plane, double cx, double cy, double radius
) noexcept nogil:
    """Stamp a filled binary disc centred on ``(cx, cy)`` (map units)."""
    cdef int h = plane.shape[0]
    cdef int w = plane.shape[1]
    cdef int x0 = <int>(cx - radius)
    cdef int x1 = <int>(cx + radius + 1.0)
    cdef int y0 = <int>(cy - radius)
    cdef int y1 = <int>(cy + radius + 1.0)
    cdef int x, y
    cdef double dx, dy
    if x0 < 0:
        x0 = 0
    if y0 < 0:
        y0 = 0
    if x1 > w:
        x1 = w
    if y1 > h:
        y1 = h
    for y in range(y0, y1):
        dy = (y + 0.5) - cy
        for x in range(x0, x1):
            dx = (x + 0.5) - cx
            if dx * dx + dy * dy <= radius * radius:
                plane[y, x] = 1.0


cdef void _stamp_add_disc(
    cnp.float32_t[:, :] plane, double cx, double cy, double radius
) noexcept nogil:
    """Additively stamp a filled disc (overlaps accumulate)."""
    cdef int h = plane.shape[0]
    cdef int w = plane.shape[1]
    cdef int x0 = <int>(cx - radius)
    cdef int x1 = <int>(cx + radius + 1.0)
    cdef int y0 = <int>(cy - radius)
    cdef int y1 = <int>(cy + radius + 1.0)
    cdef int x, y
    cdef double dx, dy
    if x0 < 0:
        x0 = 0
    if y0 < 0:
        y0 = 0
    if x1 > w:
        x1 = w
    if y1 > h:
        y1 = h
    for y in range(y0, y1):
        dy = (y + 0.5) - cy
        for x in range(x0, x1):
            dx = (x + 0.5) - cx
            if dx * dx + dy * dy <= radius * radius:
                plane[y, x] += 1.0


cdef void _accumulate_unit_planes(
    cnp.float32_t[:, :, :] planes,
    const cnp.float32_t[:, :] pos,
    const cnp.float32_t[:] mask,
    const cnp.float32_t[:] hp,
    const cnp.int64_t[:] alliance,
    const cnp.float32_t[:] selected,
    const cnp.float32_t[:] has_buff,
    int p_self,
    int p_ally,
    int p_neutral,
    int p_enemy,
    int p_den_self,
    int p_den_enemy,
    int p_hp_self,
    int p_hp_enemy,
    int p_selected,
    int p_buffs,
) noexcept nogil:
    """Single summing pass of entity mass onto minimap feature planes.

    These planes are PySC2-style map inputs (counts, hp mass, presence) —
    not the learned scatter connection, which splats transformer embeddings
    model-side (see the private note ``notes/scatter_connection.md``).
    Counts and hp are *summed* per cell; normalisation to ``[0, 1]`` happens
    afterwards in vectorised numpy.
    """
    cdef int n = pos.shape[0]
    cdef int h = planes.shape[1]
    cdef int w = planes.shape[2]
    cdef int i, gx, gy, a
    cdef float px, py
    for i in range(n):
        if mask[i] <= 0.5:
            continue
        px = pos[i, 0]
        py = pos[i, 1]
        gx = <int>(px * w)
        gy = <int>(py * h)
        if gx < 0:
            gx = 0
        elif gx >= w:
            gx = w - 1
        if gy < 0:
            gy = 0
        elif gy >= h:
            gy = h - 1
        a = alliance[i]
        if a == 0:
            planes[p_self, gy, gx] = 1.0
            planes[p_den_self, gy, gx] += 1.0
            planes[p_hp_self, gy, gx] += hp[i]
        elif a == 1:
            planes[p_ally, gy, gx] = 1.0
            planes[p_den_self, gy, gx] += 1.0
            planes[p_hp_self, gy, gx] += hp[i]
        elif a == 2:
            planes[p_neutral, gy, gx] = 1.0
        else:
            planes[p_enemy, gy, gx] = 1.0
            planes[p_den_enemy, gy, gx] += 1.0
            planes[p_hp_enemy, gy, gx] += hp[i]
        if selected[i] > 0.5:
            planes[p_selected, gy, gx] += 1.0
        if has_buff[i] > 0.5:
            planes[p_buffs, gy, gx] += 1.0


cdef inline int _alliance_idx(int alliance) noexcept nogil:
    # python-sc2 alliance: 1=self, 2=ally, 3=neutral, 4=enemy -> 0..3.
    cdef int a = alliance - 1
    if a < 0:
        return 0
    if a > 3:
        return 3
    return a


cdef inline int _race_slot(object race):
    # Terran=1, Zerg=2, Protoss=3 -> slots 0..2, anything else -> 3.
    cdef int v
    try:
        v = int(race.value)
    except Exception:
        return 3
    if v == 1:
        return 0
    if v == 2:
        return 1
    if v == 3:
        return 2
    return 3


# Initial resource contents per unit type (raw SC2 ids). AlphaStar keeps an
# equivalent INITIAL_RESOURCE_CONTENTS table to encode *mined* resources.
# Defaults: 1800 minerals / 2250 vespene; only the small-field variants
# below differ. Values from UnitTypeId: MINERALFIELD750 family = 750,
# MINERALFIELD450 = 450, MINERALFIELDOPAQUE900 = 900.
cdef set _MINERAL_750_TYPES = {147, 483, 666, 797, 885, 887}
cdef set _MINERAL_450_TYPES = {1996}
cdef set _MINERAL_900_TYPES = {1998}
cdef double _SCALE_MINERAL_DEFAULT = 1800.0
cdef double _SCALE_VESPENE_DEFAULT = 2250.0


cdef inline double _initial_resource_c(int raw_type, double mineral_c,
                                       double vespene_c):
    # GIL-held on purpose (set membership); _encode_entities holds the GIL.
    if mineral_c > 0.0:
        if raw_type in _MINERAL_750_TYPES:
            return 750.0
        if raw_type in _MINERAL_450_TYPES:
            return 450.0
        if raw_type in _MINERAL_900_TYPES:
            return 900.0
        return _SCALE_MINERAL_DEFAULT
    if vespene_c > 0.0:
        return _SCALE_VESPENE_DEFAULT
    return 0.0


@dataclass(slots=True)
class Observation:
    """Batched (``1 × ...``) full-game observation.

    - ``entity_features``: ``(1, MAX_ENTITIES, ENTITY_NUM_DIM)`` float32
    - ``entity_categorical``: ``(1, MAX_ENTITIES, ENTITY_CAT_DIM)`` int64
    - ``entity_mask``: ``(1, MAX_ENTITIES)`` float32
    - ``entity_positions``: ``(1, MAX_ENTITIES, 2)`` float32, normalised.
      Model-side scatter input: zero the embeddings with ``entity_mask``
      *before* scattering (padding rows sit at cell ``(0, 0)``).
    - ``spatial``: ``(1, NUM_SPATIAL_CHANNELS, 128, 128)`` float32
    - ``scalar``: ``(1, SCALAR_DIM)`` float32, see ``SCALAR_FEATURE_NAMES``
    - ``unit_tags``: game tag per entity row
    """

    entity_features: np.ndarray
    entity_categorical: np.ndarray
    entity_mask: np.ndarray
    entity_positions: np.ndarray
    spatial: np.ndarray
    scalar: np.ndarray
    unit_tags: List[int]


class Features:
    """AlphaStar / DI-Star style feature encoder over ``python-sc2`` state.

    Construct once per game (caches static terrain), then call
    :meth:`build_observation` each step.
    """

    def __init__(self, ai) -> None:
        self.ai = ai
        self.entity_num_dim = ENTITY_NUM_DIM
        self.entity_cat_dim = ENTITY_CAT_DIM
        self.scalar_dim = SCALAR_DIM

        self.map_width: float = float(self.ai.game_info.map_size[0])
        self.map_height: float = float(self.ai.game_info.map_size[1])

        height_raw = np.asarray(
            self.ai.game_info.terrain_height.data_numpy, dtype=np.float32
        )
        height_np = np.asarray(
            _ensure_hw_grid(height_raw, self.map_width, self.map_height,
                            "terrain_height"),
            dtype=np.float32,
        )
        h_min = float(height_np.min())
        h_span = float(height_np.max() - height_np.min())
        if h_span < 1e-6:
            h_span = 1e-6
        self.height_np = (height_np - h_min) / h_span

        self.pathing_np = np.asarray(
            _ensure_hw_grid(
                np.asarray(self.ai.game_info.pathing_grid.data_numpy,
                           dtype=np.float32),
                self.map_width, self.map_height, "pathing_grid",
            ),
            dtype=np.float32,
        )
        self.pathing_np = np.clip(self.pathing_np, 0.0, 1.0)
        self.placement_np = np.asarray(
            _ensure_hw_grid(
                np.asarray(self.ai.game_info.placement_grid.data_numpy,
                           dtype=np.float32),
                self.map_width, self.map_height, "placement_grid",
            ),
            dtype=np.float32,
        )
        self.placement_np = np.clip(self.placement_np, 0.0, 1.0)
        self.playable_mask_np = self._build_playable_mask()
        # Per-game caches: per-type statics (speed, structure flag),
        # resized static planes per target size, and the fixed start.
        self._type_cache: dict[int, tuple[float, int]] = {}
        self._static_cache: dict[tuple[int, int], np.ndarray] = {}
        self._spawn: tuple[float, float] = self._spawn_xy()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_observation(
        self, target_spatial_size: tuple[int, int] | None = None
    ) -> Observation:
        """Encode entities, spatial stack and scalar vector in one call."""
        if target_spatial_size is None:
            target_spatial_size = TARGET_SPATIAL_SIZE
        ent, ent_cat, pos, mask, tags, aux = self._encode_entities(
            units=self.ai.all_units,
            max_units=MAX_ENTITIES,
            return_tags=True,
        )
        spatial, n_effects = self._encode_spatial(
            entity_positions=pos,
            entity_mask=mask,
            entity_aux=aux,
            target_spatial_size=target_spatial_size,
        )
        scalar = self._encode_scalar(n_effects=float(n_effects))
        return Observation(
            entity_features=np.expand_dims(ent, axis=0),
            entity_categorical=np.expand_dims(ent_cat, axis=0),
            entity_mask=np.expand_dims(mask, axis=0),
            entity_positions=np.expand_dims(pos, axis=0),
            spatial=np.expand_dims(spatial, axis=0),
            scalar=np.expand_dims(scalar, axis=0),
            unit_tags=tags,
        )

    # ------------------------------------------------------------------
    # Entities
    # ------------------------------------------------------------------

    def _encode_entities(
        self,
        units: Units,
        max_units: int,
        return_tags: bool = False,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Optional[List[int]], np.ndarray]:
        """Encode the visible entity set.

        Returns ``(features, categorical, positions, mask, tags, aux)`` where
        ``aux`` is a ``(n, 4)`` float32 helper of ``[hp_raw, alliance,
        selected, has_buff]`` reused by the spatial scatter so per-unit
        python state is only extracted once.
        """
        cdef double denom_x = self.map_width - 1.0
        cdef double denom_y = self.map_height - 1.0
        if denom_x < 1.0:
            denom_x = 1.0
        if denom_y < 1.0:
            denom_y = 1.0

        # One priming pass: tag map for order resolution plus per-type
        # statics. movement_speed chains two objects and is_structure scans
        # game data, so both are memoized per unit type across steps; the
        # sort key below then stays allocation-free of property work.
        # NOTE: movement_speed is a type static (excludes buffs/slow fields).
        cdef dict tag_to_type = {}
        cdef dict type_cache = self._type_cache
        cdef object u
        cdef set passenger_tags = set()
        for u in units:
            t = u._proto.unit_type
            tag_to_type[u.tag] = UNIT_TYPE_DICT.get(t, 0)
            if t not in type_cache:
                try:
                    type_speed = float(u.movement_speed)
                except Exception:
                    type_speed = 0.0
                try:
                    type_struct = 1 if u.is_structure else 0
                except Exception:
                    type_struct = 0
                type_cache[t] = (type_speed, type_struct)
            # Collect transported-unit tags so EC_IN_CARGO can be marked.
            # proto.passengers is empty for non-transports; guards keep
            # synthetic / partial protos cheap.
            try:
                passengers = u._proto.passengers
            except Exception:
                passengers = None
            if passengers:
                try:
                    for passenger in passengers:
                        try:
                            passenger_tags.add(passenger.tag)
                        except Exception:
                            continue
                except Exception:
                    pass

        # Deterministic priority order so truncation is stable: own units
        # first, then ally / neutral / enemy, buildings after armies.
        cdef list ordered = sorted(
            units,
            key=lambda u: (
                _alliance_idx(u.alliance),
                type_cache[u._proto.unit_type][1],
                u.tag,
            ),
        )
        cdef int n_total = len(ordered)
        cdef int n = n_total if n_total < max_units else max_units

        cdef cnp.ndarray[cnp.float32_t, ndim=2] feats = np.zeros(
            (max_units, ENTITY_NUM_DIM), dtype=np.float32
        )
        cdef cnp.ndarray[cnp.int64_t, ndim=2] cats = np.zeros(
            (max_units, ENTITY_CAT_DIM), dtype=np.int64
        )
        cdef cnp.ndarray[cnp.float32_t, ndim=2] pos = np.zeros(
            (max_units, 2), dtype=np.float32
        )
        cdef cnp.ndarray[cnp.float32_t, ndim=2] aux = np.zeros(
            (max_units, 4), dtype=np.float32
        )
        mask = _build_mask(n, max_units)
        cdef list tags = [] if return_tags else None

        cdef int i
        cdef object proto, ability, target
        cdef double x, y
        cdef list buff_ids
        cdef int n_buffs, order_ability, order_unit_type, raw_type
        cdef double order_x, order_y, hp_raw, buff_remain0, speed
        cdef int alliance
        cdef int order_length, on_screen, is_blip, in_cargo
        cdef int addon_tag, addon_type, engaged_tag, engaged_type, owner
        cdef double order_progress, facing, facing_sin, facing_cos
        cdef double pos_z, detect_range, mineral_c, vespene_c
        cdef double initial_res, mined

        for i in range(n):
            u = ordered[i]
            proto = u._proto
            x = proto.pos.x
            y = proto.pos.y

            alliance = _alliance_idx(u.alliance)

            hp_raw = proto.health + proto.shield

            # -- orders: queue length + first order (ability + target) --------
            # AlphaStar keeps 4x order_id + progress; we keep the first
            # ability/target plus queue length and first progress, which
            # distinguishes idle (0) from queued (n) without a 4x blowup.
            order_ability = 0
            order_unit_type = 0
            order_x = 0.0
            order_y = 0.0
            order_length = 0
            order_progress = 0.0
            try:
                orders = u.orders
            except Exception:
                orders = None
            if orders:
                try:
                    order_length = len(orders)
                except Exception:
                    order_length = 1
                if order_length > 8:
                    order_length = 8
                first = orders[0]
                try:
                    order_progress = float(getattr(first, "progress", 0.0))
                except Exception:
                    order_progress = 0.0
                if order_progress != order_progress:  # NaN guard
                    order_progress = 0.0
                try:
                    ability = first.ability
                    ability = getattr(ability, "id", ability)
                    ability = getattr(ability, "value", ability)
                    order_ability = ABILITY_DICT.get(int(ability), 0)
                except Exception:
                    order_ability = 0
                # Newer python-sc2 exposes a single `target` (tag int or
                # point); older versions expose `target_unit_tag`.
                target = getattr(first, "target_unit_tag", None)
                if target is None:
                    target = getattr(first, "target", None)
                if isinstance(target, bool):
                    pass
                elif isinstance(target, int):
                    order_unit_type = tag_to_type.get(target, 0)
                elif target is not None:
                    # Point target; missing coords fall through as 0.0.
                    try:
                        order_x = target.x / denom_x
                        order_y = target.y / denom_y
                    except Exception:
                        pass

            # -- buffs: keep the first two ids (DI-Star keeps two). Note the
            # raw API exposes buff_duration_remain as a single int scalar in
            # game loops (not per buff, not seconds), so only slot 0 carries
            # a duration; slot 1 is 0.0. Scaled by 60 loops (~2.7 s): 1.0
            # means longer-lived, values below 1.0 mean expiring soon.
            buff_ids = list(proto.buff_ids)
            buff_remain0 = proto.buff_duration_remain
            n_buffs = len(buff_ids)
            buff0 = 0
            buff1 = 0
            dur0 = 0.0
            dur1 = 0.0
            if n_buffs > 0:
                buff0 = BUFF_DICT.get(buff_ids[0], 0)
                dur0 = _clip01_c(buff_remain0 / SCALE_BUFF_DURATION)
            if n_buffs > 1:
                buff1 = BUFF_DICT.get(buff_ids[1], 0)

            # -- masks / attachments -----------------------------------------
            # is_on_screen + is_blip feed AlphaStar's SELECTABLE /
            # TARGETABLE_WITH_CAMERA masks; in_cargo marks transported units
            # (no proto flag — resolved via the passenger tag set above).
            try:
                on_screen = 1 if proto.is_on_screen else 0
            except Exception:
                on_screen = 0
            try:
                is_blip = 1 if proto.is_blip else 0
            except Exception:
                is_blip = 0
            try:
                in_cargo = 1 if proto.tag in passenger_tags else 0
            except Exception:
                in_cargo = 0
            try:
                addon_tag = int(proto.add_on_tag)
            except Exception:
                addon_tag = 0
            if addon_tag != 0:
                addon_type = tag_to_type.get(addon_tag, 1)
            else:
                addon_type = 0
            try:
                engaged_tag = int(proto.engaged_target_tag)
            except Exception:
                engaged_tag = 0
            if engaged_tag != 0:
                engaged_type = tag_to_type.get(engaged_tag, 0)
            else:
                engaged_type = 0
            try:
                owner = int(proto.owner)
            except Exception:
                owner = 0
            if owner < 0:
                owner = 0
            elif owner > 15:
                owner = 15

            # -- facing as a sin/cos pair (no wrap discontinuity) -------------
            facing = proto.facing % TWO_PI
            facing_sin = sin(facing) * 0.5 + 0.5
            facing_cos = cos(facing) * 0.5 + 0.5
            try:
                pos_z = float(proto.pos.z)
            except Exception:
                pos_z = 0.0
            try:
                detect_range = float(proto.detect_range)
            except Exception:
                detect_range = 0.0
            try:
                mineral_c = float(proto.mineral_contents)
            except Exception:
                mineral_c = 0.0
            try:
                vespene_c = float(proto.vespene_contents)
            except Exception:
                vespene_c = 0.0
            # Type statics were primed above for every unit in this call.
            raw_type = proto.unit_type
            speed = type_cache[raw_type][0]
            initial_res = _initial_resource_c(raw_type, mineral_c, vespene_c)
            if initial_res > 0.0:
                mined = initial_res - (mineral_c + vespene_c)
                if mined < 0.0:
                    mined = 0.0
            else:
                mined = 0.0
            ideal = proto.ideal_harvesters
            assigned = proto.assigned_harvesters

            # Clipped: units at the map edge can otherwise exceed 1.0.
            feats[i, EN_X] = _clip01_c(x / denom_x)
            feats[i, EN_Y] = _clip01_c(y / denom_y)
            # Optimistic proto reads: every field below always exists on a
            # Unit proto (protobuf returns defaults); fail fast otherwise.
            feats[i, EN_FACING_SIN] = _clip01_c(facing_sin)
            feats[i, EN_FACING_COS] = _clip01_c(facing_cos)
            feats[i, EN_HP] = _safe_ratio_c(proto.health, proto.health_max)
            feats[i, EN_SHIELD] = _safe_ratio_c(proto.shield, proto.shield_max)
            feats[i, EN_ENERGY] = _safe_ratio_c(proto.energy, proto.energy_max)
            feats[i, EN_RADIUS] = _log_norm_c(proto.radius, 4.0)
            feats[i, EN_CARGO_TAKEN] = _clip01_c(
                proto.cargo_space_taken / SCALE_CARGO)
            feats[i, EN_CARGO_MAX] = _clip01_c(
                proto.cargo_space_max / SCALE_CARGO)
            feats[i, EN_BUILD_PROGRESS] = _clip01_c(proto.build_progress)
            feats[i, EN_WEAPON_CD] = _clip01_c(
                proto.weapon_cooldown / SCALE_WEAPON_CD)
            feats[i, EN_SPEED] = _log_norm_c(speed, SCALE_SPEED)
            feats[i, EN_MINERALS] = _log_norm_c(
                proto.mineral_contents, SCALE_RESOURCE_CONTENTS)
            feats[i, EN_VESPENE] = _log_norm_c(
                proto.vespene_contents, SCALE_RESOURCE_CONTENTS)
            feats[i, EN_HARVESTERS] = _safe_ratio_c(assigned, ideal)
            feats[i, EN_BUFF_DUR0] = dur0
            feats[i, EN_BUFF_DUR1] = dur1
            feats[i, EN_ORDER_X] = _clip01_c(order_x)
            feats[i, EN_ORDER_Y] = _clip01_c(order_y)
            feats[i, EN_ENGAGED] = 1.0 if proto.engaged_target_tag != 0 else 0.0
            feats[i, EN_ORDER_PROGRESS] = _clip01_c(order_progress)
            feats[i, EN_MINED] = _log_norm_c(mined, SCALE_RESOURCE_CONTENTS)
            feats[i, EN_DETECT] = _log_norm_c(detect_range, SCALE_DETECT)
            feats[i, EN_POS_Z] = _clip01_c(pos_z / SCALE_POS_Z)

            cats[i, EC_TYPE] = UNIT_TYPE_DICT.get(raw_type, 0)
            cats[i, EC_ALLIANCE] = alliance
            cats[i, EC_DISPLAY] = proto.display_type
            cats[i, EC_CLOAK] = proto.cloak
            cats[i, EC_ORDER_ABILITY] = order_ability
            cats[i, EC_ORDER_TARGET_UNIT] = order_unit_type
            cats[i, EC_BUFF0] = buff0
            cats[i, EC_BUFF1] = buff1
            cats[i, EC_FLYING] = 1 if proto.is_flying else 0
            cats[i, EC_BURROWED] = 1 if proto.is_burrowed else 0
            cats[i, EC_HALLUC] = 1 if proto.is_hallucination else 0
            cats[i, EC_ACTIVE] = 1 if proto.is_active else 0
            cats[i, EC_POWERED] = 1 if proto.is_powered else 0
            cats[i, EC_SELECTED] = 1 if proto.is_selected else 0
            cats[i, EC_ATK_UP] = proto.attack_upgrade_level
            cats[i, EC_ARMOR_UP] = proto.armor_upgrade_level
            cats[i, EC_SHIELD_UP] = proto.shield_upgrade_level
            cats[i, EC_ORDER_LENGTH] = order_length
            cats[i, EC_ON_SCREEN] = on_screen
            cats[i, EC_BLIP] = is_blip
            cats[i, EC_IN_CARGO] = in_cargo
            cats[i, EC_ADDON] = addon_type
            cats[i, EC_ENGAGED_TYPE] = engaged_type
            cats[i, EC_OWNER] = owner

            pos[i, 0] = feats[i, EN_X]
            pos[i, 1] = feats[i, EN_Y]
            aux[i, 0] = hp_raw
            aux[i, 1] = alliance
            aux[i, 2] = cats[i, EC_SELECTED]
            aux[i, 3] = 1.0 if n_buffs > 0 else 0.0

            if return_tags:
                tags.append(proto.tag)

        return feats, cats, pos, mask, tags, aux

    # ------------------------------------------------------------------
    # Spatial
    # ------------------------------------------------------------------

    def _build_playable_mask(self) -> np.ndarray:
        h = int(self.map_height)
        w = int(self.map_width)
        mask = np.zeros((h, w), dtype=np.float32)
        area = self.ai.game_info.playable_area
        if (
            hasattr(area, "x")
            and hasattr(area, "y")
            and hasattr(area, "width")
            and hasattr(area, "height")
        ):
            x0 = int(area.x)
            y0 = int(area.y)
            x1 = int(area.x + area.width)
            y1 = int(area.y + area.height)
        elif (
            hasattr(area, "x1")
            and hasattr(area, "y1")
            and hasattr(area, "x2")
            and hasattr(area, "y2")
        ):
            x0 = int(area.x1)
            y0 = int(area.y1)
            x1 = int(area.x2)
            y1 = int(area.y2)
        else:
            x0, y0, x1, y1 = 0, 0, w, h
        x0 = max(0, min(w, x0))
        x1 = max(0, min(w, x1))
        y0 = max(0, min(h, y0))
        y1 = max(0, min(h, y1))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = 1.0
        return mask

    def _spawn_xy(self) -> tuple[float, float]:
        """Start location in map units (camera proxy — python-sc2 exposes
        no live camera). Falls back to map centre."""
        for candidate in (
            getattr(self.ai, "start_location", None),
            getattr(getattr(self.ai, "game_info", None),
                    "player_start_location", None),
        ):
            try:
                if candidate is not None and hasattr(candidate, "x"):
                    return float(candidate.x), float(candidate.y)
            except Exception:
                continue
        try:
            center = self.ai.game_info.map_center
            return float(center.x), float(center.y)
        except Exception:
            return self.map_width / 2.0, self.map_height / 2.0

    def _encode_spatial(
        self,
        entity_positions: np.ndarray,
        entity_mask: np.ndarray,
        entity_aux: np.ndarray,
        target_spatial_size: tuple[int, int] = TARGET_SPATIAL_SIZE,
    ) -> tuple:
        """Build the ``(C, H, W)`` map stack; see ``SPATIAL_CHANNEL_NAMES``.

        Dense static planes are resized; sparse unit planes are scattered
        directly at target resolution so no unit is lost to downsampling.

        Returns ``(stack, n_effects)`` where the count is the number of
        persistent-effect objects (storms, biles, nukes, ...) drawn onto
        the effect plane.
        """
        cdef int h = int(self.map_height)
        cdef int w = int(self.map_width)
        cdef int th = int(target_spatial_size[0])
        cdef int tw = int(target_spatial_size[1])
        cdef double sx = tw / float(w) if w > 0 else 1.0
        cdef double sy = th / float(h) if h > 0 else 1.0

        # -- dense static planes: height/pathing/placement/playable never
        # change mid-game, so resize once per target size and cache. Only
        # visibility/creep are rebuilt every step.
        cdef tuple static_key = (th, tw)
        static4 = self._static_cache.get(static_key)
        if static4 is None:
            native4 = np.zeros((4, h, w), dtype=np.float32)
            native4[0] = self.height_np
            native4[1] = self.pathing_np
            native4[2] = self.placement_np
            native4[3] = self.playable_mask_np
            if (h, w) != (th, tw):
                native4 = _resize_nearest(native4, (th, tw))
            static4 = np.ascontiguousarray(native4, dtype=np.float32)
            self._static_cache[static_key] = static4
        playable_t = np.ascontiguousarray(static4[3], dtype=np.float32)
        try:
            vis = np.asarray(
                _ensure_hw_grid(
                    np.asarray(self.ai.state.visibility.data_numpy,
                               dtype=np.float32),
                    self.map_width, self.map_height, "visibility",
                ),
                dtype=np.float32,
            )
            vis = np.nan_to_num(vis, nan=0.0, posinf=0.0, neginf=0.0) / 2.0
            # Visibility is a 0/1/2 enum in python-sc2; clip so a future
            # 0-255 change degrades to saturated instead of >1.0 planes.
            vis = np.clip(vis, 0.0, 1.0)
        except Exception:
            vis = np.zeros((h, w), dtype=np.float32)
        try:
            creep = np.asarray(
                _ensure_hw_grid(
                    np.asarray(self.ai.state.creep.data_numpy,
                               dtype=np.float32),
                    self.map_width, self.map_height, "creep",
                ),
                dtype=np.float32,
            )
            creep = np.clip(
                np.nan_to_num(creep, nan=0.0, posinf=0.0, neginf=0.0),
                0.0, 1.0,
            )
        except Exception:
            creep = np.zeros((h, w), dtype=np.float32)
        if (h, w) != (th, tw):
            dyn = _resize_nearest(
                np.stack([vis, creep]).astype(np.float32), (th, tw))
        else:
            dyn = np.stack([vis, creep]).astype(np.float32)

        # -- power: stamp discs at psionic-matrix sources (target res) ----------
        cdef cnp.ndarray[cnp.float32_t, ndim=2] power = np.zeros(
            (th, tw), dtype=np.float32
        )
        try:
            sources = list(
                getattr(getattr(self.ai, "state", None),
                        "psionic_matrix", None).sources or []
            )
        except Exception:
            sources = []
        for source in sources:
            pos = source.position
            pos_x, pos_y = float(pos.x), float(pos.y)
            _splat_disc(power, pos_x * sx, pos_y * sy,
                        float(source.radius) * (sx + sy) * 0.5)

        # -- summing scatter of entity mass, straight at target res -------------
        cdef cnp.ndarray[cnp.float32_t, ndim=3] scatter = np.zeros(
            (10, th, tw), dtype=np.float32
        )
        cdef cnp.ndarray[cnp.float32_t, ndim=2] pos_c = np.ascontiguousarray(
            entity_positions, dtype=np.float32
        )
        cdef cnp.ndarray[cnp.float32_t, ndim=1] mask_c = np.ascontiguousarray(
            entity_mask, dtype=np.float32
        )
        cdef cnp.ndarray[cnp.float32_t, ndim=2] aux_c = np.ascontiguousarray(
            entity_aux, dtype=np.float32
        )
        cdef cnp.ndarray[cnp.float32_t, ndim=1] hp_c = np.ascontiguousarray(
            aux_c[:, 0], dtype=np.float32
        )
        cdef cnp.ndarray[cnp.int64_t, ndim=1] al_c = np.ascontiguousarray(
            aux_c[:, 1], dtype=np.int64
        )
        cdef cnp.ndarray[cnp.float32_t, ndim=1] sel_c = np.ascontiguousarray(
            aux_c[:, 2], dtype=np.float32
        )
        cdef cnp.ndarray[cnp.float32_t, ndim=1] buf_c = np.ascontiguousarray(
            aux_c[:, 3], dtype=np.float32
        )
        _accumulate_unit_planes(
            scatter, pos_c, mask_c, hp_c, al_c, sel_c, buf_c,
            0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
        )

        # -- spawn marker (target res; start location is fixed per game) --------
        cdef cnp.ndarray[cnp.float32_t, ndim=2] spawn = np.zeros(
            (th, tw), dtype=np.float32
        )
        spawn_x, spawn_y = self._spawn
        _splat_disc(spawn, spawn_x * sx, spawn_y * sy,
                    SCALE_SPAWN_RADIUS * (sx + sy) * 0.5)

        # -- persistent effects (storms, biles, nukes, liberator zones) ---------
        # Radius-aware additive discs at target res. No alliance split:
        # nearly all such effects damage both sides, so this plane means
        # danger, whoever cast it.
        # Plain object: reassigned by the float64 log1p normalisation below.
        eff_plane = np.zeros((th, tw), dtype=np.float32)
        cdef int n_effects = 0
        cdef double eff_radius, r_t, px, py
        try:
            effects = list(
                getattr(getattr(self.ai, "state", None), "effects", None) or []
            )
        except Exception:
            effects = []
        for eff in effects:
            try:
                eff_radius = float(getattr(eff, "radius", 0.0))
            except Exception:
                eff_radius = 0.0
            if eff_radius <= 0.0:
                eff_radius = 1.5  # storm-like default when API omits it
            try:
                eff_positions = list(getattr(eff, "positions", None) or [])
            except Exception:
                eff_positions = []
            if not eff_positions:
                continue
            n_effects += 1
            r_t = eff_radius * (sx + sy) * 0.5
            if r_t < 1.0:
                r_t = 1.0  # guarantee at least the centre cell
            for p in eff_positions:
                try:
                    px = float(p.x) * sx
                    py = float(p.y) * sy
                except Exception:
                    continue
                _stamp_add_disc(eff_plane, px, py, r_t)
        eff_plane = np.log1p(eff_plane) / np.log1p(SCALE_DENSITY)

        # -- normalise count / mass planes into [0, 1] --------------------------
        scatter[4] = np.log1p(scatter[4]) / np.log1p(SCALE_DENSITY)
        scatter[5] = np.log1p(scatter[5]) / np.log1p(SCALE_DENSITY)
        scatter[6] = np.log1p(scatter[6]) / np.log1p(SCALE_CELL_HP)
        scatter[7] = np.log1p(scatter[7]) / np.log1p(SCALE_CELL_HP)
        scatter[8] = np.log1p(scatter[8]) / np.log1p(SCALE_DENSITY)
        scatter[9] = np.log1p(scatter[9]) / np.log1p(SCALE_DENSITY)

        stack = np.concatenate(
            [np.asarray(static4, dtype=np.float32),
             np.asarray(dyn, dtype=np.float32),
             power[None, :, :],
             np.asarray(scatter, dtype=np.float32),
             spawn[None, :, :],
             np.asarray(eff_plane, dtype=np.float32)[None, :, :]],
            axis=0,
        )
        stack *= playable_t[None, :, :]
        np.clip(stack, 0.0, 1.0, out=stack)
        return (np.ascontiguousarray(stack, dtype=np.float32), n_effects)

    # ------------------------------------------------------------------
    # Scalar / player state
    # ------------------------------------------------------------------

    def _encode_scalar(self, n_effects: float = 0.0) -> np.ndarray:
        """Global full-game vector; see ``SCALAR_FEATURE_NAMES``."""
        ai = self.ai
        cdef double loop = 0.0
        try:
            loop = float(ai.state.game_loop)
        except Exception:
            try:
                loop = float(ai.time) * 22.4
            except Exception:
                loop = 0.0

        def _f(name, default=0.0):
            try:
                return float(getattr(ai, name))
            except Exception:
                return float(default)

        minerals = _f("minerals")
        vespene = _f("vespene")
        supply_used = _f("supply_used")
        supply_cap = _f("supply_cap")
        supply_left = _f("supply_left")
        supply_army = _f("supply_army")
        supply_workers = _f("supply_workers")

        def _len(name):
            try:
                return float(len(getattr(ai, name)))
            except Exception:
                return 0.0

        n_workers = _len("workers")
        n_townhalls = _len("townhalls")
        n_gas = _len("gas_buildings")
        n_army = _len("army")
        n_enemy = _len("all_enemy_units")
        n_larva = _len("larva")
        idle_workers = _f("idle_worker_count")

        cdef double army_hp = 0.0
        cdef double enemy_hp = 0.0
        try:
            for u in ai.army:
                army_hp += float(u.health) + float(u.shield)
        except Exception:
            pass
        try:
            for u in ai.all_enemy_units:
                enemy_hp += float(u.health) + float(u.shield)
        except Exception:
            pass

        race_self = [0.0, 0.0, 0.0, 0.0]
        race_enemy = [0.0, 0.0, 0.0, 0.0]
        race_self[_race_slot(getattr(ai, "race", None))] = 1.0
        race_enemy[_race_slot(getattr(ai, "enemy_race", None))] = 1.0

        # Upgrades: count + hashed 8-bucket multi-hot (306 ids are too many
        # for a flat multi-hot; hashing preserves co-occurrence signal).
        upgrade_buckets = [0.0] * 8
        n_upgrades = 0.0
        try:
            upgrade_iter = list(ai.state.upgrades)
        except Exception:
            upgrade_iter = []
        for up in upgrade_iter:
            try:
                v = int(getattr(up, "value", up))
            except Exception:
                continue
            upgrade_buckets[v % 8] += 1.0
            n_upgrades += 1.0

        n_alerts = 0.0
        alert_severity = 0.0
        try:
            alerts = list(ai.state.alerts)
        except Exception:
            alerts = []
        for alert in alerts:
            n_alerts += 1.0
            try:
                alert_severity = max(alert_severity,
                                     float(getattr(alert, "value", alert)))
            except Exception:
                continue
        alert_severity = min(alert_severity / 25.0, 1.0)

        spawn_x, spawn_y = self._spawn
        denom_x = self.map_width - 1.0 if self.map_width > 1.0 else 1.0
        denom_y = self.map_height - 1.0 if self.map_height > 1.0 else 1.0

        def _score(name):
            try:
                return float(getattr(ai.state.score, name))
            except Exception:
                return 0.0

        score = ai.state.score if getattr(ai, "state", None) is not None else None
        if score is None:
            total_value = collected_min = collected_ves = 0.0
            rate_min = rate_ves = apm = 0.0
            killed_units = killed_structures = lost_value = spent_value = 0.0
        else:
            total_value = _score("total_value_units") + _score(
                "total_value_structures")
            killed_units = _score("killed_value_units")
            killed_structures = _score("killed_value_structures")
            collected_min = _score("collected_minerals")
            collected_ves = _score("collected_vespene")
            rate_min = _score("collection_rate_minerals")
            rate_ves = _score("collection_rate_vespene")
            apm = _score("current_apm")
            # Lost / spent have no single total field: sum the per-category
            # minerals + vespene buckets (none/army/economy/technology/
            # upgrade). Missing buckets fall back to 0.0 via _score.
            lost_value = 0.0
            for _cat in ("none", "army", "economy", "technology", "upgrade"):
                lost_value += _score(f"lost_minerals_{_cat}")
                lost_value += _score(f"lost_vespene_{_cat}")
            spent_value = _score("spent_minerals") + _score("spent_vespene")

        arr = np.empty((SCALAR_DIM,), dtype=np.float32)
        arr[0] = min(loop / SCALE_GAME_LOOP, 1.0)
        arr[1] = min(_f("time") / SCALE_GAME_TIME, 1.0)
        arr[2] = _log_norm_c(minerals, SCALE_MINERALS)
        arr[3] = _log_norm_c(vespene, SCALE_MINERALS)
        arr[4] = min(supply_used / SCALE_SUPPLY, 1.0)
        arr[5] = min(supply_cap / SCALE_SUPPLY, 1.0)
        arr[6] = min(max(supply_left, 0.0) / SCALE_SUPPLY, 1.0)
        arr[7] = min(supply_army / SCALE_SUPPLY, 1.0)
        arr[8] = min(supply_workers / SCALE_SUPPLY, 1.0)
        arr[9] = min(n_larva / 20.0, 1.0)
        arr[10] = min(n_workers / 100.0, 1.0)
        arr[11] = min(n_townhalls / 10.0, 1.0)
        arr[12] = min(n_gas / 20.0, 1.0)
        arr[13] = min(idle_workers / 50.0, 1.0)
        arr[14] = min(n_army / 200.0, 1.0)
        arr[15] = min(n_enemy / 200.0, 1.0)
        arr[16] = _log_norm_c(army_hp, SCALE_HP_MASS)
        arr[17] = _log_norm_c(enemy_hp, SCALE_HP_MASS)
        arr[18] = race_self[0]
        arr[19] = race_self[1]
        arr[20] = race_self[2]
        arr[21] = race_self[3]
        arr[22] = race_enemy[0]
        arr[23] = race_enemy[1]
        arr[24] = race_enemy[2]
        arr[25] = race_enemy[3]
        arr[26] = float(np.log1p(n_upgrades) / np.log1p(64.0))
        for b in range(8):
            arr[27 + b] = float(np.log1p(upgrade_buckets[b]) / np.log1p(16.0))
        arr[35] = float(np.log1p(n_alerts) / np.log1p(8.0))
        arr[36] = alert_severity
        arr[37] = min(max(spawn_x / denom_x, 0.0), 1.0)
        arr[38] = min(max(spawn_y / denom_y, 0.0), 1.0)
        arr[39] = _log_norm_c(total_value, SCALE_MINERALS)
        arr[40] = _log_norm_c(killed_units, SCALE_KILLED)
        arr[41] = _log_norm_c(killed_structures, SCALE_KILLED)
        arr[42] = _log_norm_c(collected_min, SCALE_VALUE_WIDE)
        arr[43] = _log_norm_c(collected_ves, SCALE_VALUE_WIDE)
        arr[44] = _log_norm_c(rate_min, 5000.0)
        arr[45] = _log_norm_c(rate_ves, 5000.0)
        arr[46] = _log_norm_c(apm, 1000.0)
        arr[47] = float(np.log1p(max(n_effects, 0.0)) / np.log1p(8.0))
        arr[48] = _log_norm_c(lost_value, SCALE_VALUE_WIDE)
        arr[49] = _log_norm_c(spent_value, SCALE_VALUE_WIDE)
        return arr
