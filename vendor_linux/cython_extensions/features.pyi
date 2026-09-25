from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units

ABILITY_IDS: list[int]
BUFF_IDS: list[int]
UNIT_TYPE_IDS: list[int]
UPGRADE_IDS: list[int]
ABILITY_DICT: dict[int, int]
BUFF_DICT: dict[int, int]
UNIT_TYPE_DICT: dict[int, int]
UPGRADE_DICT: dict[int, int]
NUM_ABILITIES: int
NUM_BUFFS: int
NUM_UNIT_TYPES: int
NUM_UPGRADES: int
MAX_ENTITIES: int
TARGET_SPATIAL_SIZE: tuple[int, int]
ENTITY_NUM_DIM: int
ENTITY_CAT_DIM: int
SPATIAL_CHANNEL_NAMES: list[str]
NUM_SPATIAL_CHANNELS: int
SCALAR_FEATURE_NAMES: list[str]
SCALAR_DIM: int

def _safe_ratio(num: float, den: float) -> float:
    """Clipped ``num / den`` in ``[0, 1]`` (``0.0`` when ``den <= 0``)."""
    ...

def _log_norm(value: float, scale: float) -> float:
    """``log1p(value) / log1p(scale)`` clipped to ``[0, 1]``."""
    ...

def _np_one_hot(targets: np.ndarray, nb_classes: int) -> np.ndarray:
    """One-hot encode integer ``targets`` into ``(*shape, nb_classes)``."""
    ...

def _unit_pos_2d(u: Unit) -> tuple[float, float]:
    ...

def _normalize_pos(
    x: float, y: float, map_width: float, map_height: float
) -> tuple[float, float]:
    """Normalise map coordinates to ``[0, 1]``."""
    ...

def _pad_to_length(arr: np.ndarray, target_len: int) -> np.ndarray:
    """Pad ``arr`` along axis 0 with zeros up to ``target_len``."""
    ...

def _build_mask(n: int, max_n: int) -> np.ndarray:
    """``1.0`` for the first ``min(n, max_n)`` rows, else ``0.0``."""
    ...

def _ensure_hw_grid(
    grid: np.ndarray, map_width: float, map_height: float, name: str
) -> np.ndarray:
    """Return ``grid`` as ``(H, W)`` with y as rows and x as columns."""
    ...

def _resize_nearest(stack: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbour resize of a ``(C, H, W)`` stack.

    Nearest (not bilinear) is deliberate: binary masks, presence planes and
    density counts must not bleed fractional ghosts into neighbours.
    """
    ...

@dataclass(slots=True)
class Observation:
    """Batched (``1 x ...``) full-game observation.

    Example:
    ```py
    from cython_extensions.features import Features

    async def on_step(self, iteration: int):
        obs = Features(self).build_observation()
        print(obs.entity_features.shape)  # (1, 512, 25)
        print(obs.spatial.shape)  # (1, 19, 128, 128)
        print(obs.scalar.shape)  # (1, 50)
    ```

    Attributes:
        entity_features: ``(1, MAX_ENTITIES, ENTITY_NUM_DIM)`` float32,
            continuous per-unit state in ``[0, 1]``.
        entity_categorical: ``(1, MAX_ENTITIES, ENTITY_CAT_DIM)`` int64,
            discrete per-unit state as embedding indices (``0`` = unknown).
        entity_mask: ``(1, MAX_ENTITIES)`` float32, ``1.0`` for real rows.
        entity_positions: ``(1, MAX_ENTITIES, 2)`` float32, normalised x, y.
        spatial: ``(1, NUM_SPATIAL_CHANNELS, 128, 128)`` float32, see
            ``SPATIAL_CHANNEL_NAMES``.
        scalar: ``(1, SCALAR_DIM)`` float32, see ``SCALAR_FEATURE_NAMES``.
        unit_tags: Game tag per entity row, ``len <= MAX_ENTITIES``.
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

    Example:
    ```py
    from cython_extensions.features import Features

    class MyBot(BotAI):
        async def on_start(self):
            self.features = Features(self)

        async def on_step(self, iteration: int):
            obs = self.features.build_observation()
    ```
    """

    ai: BotAI
    entity_num_dim: int
    entity_cat_dim: int
    scalar_dim: int
    map_width: float
    map_height: float
    height_np: np.ndarray
    pathing_np: np.ndarray
    placement_np: np.ndarray
    playable_mask_np: np.ndarray
    def __init__(self, ai: BotAI) -> None: ...
    def build_observation(
        self, target_spatial_size: tuple[int, int] | None = None
    ) -> Observation:
        """Encode entities, spatial stack and scalar vector in one call.

        Args:
            ai: Bot object that will be running the game.
            target_spatial_size: ``(H, W)`` of the spatial stack.
                Defaults to ``TARGET_SPATIAL_SIZE`` (128, 128).

        Returns:
            Batched full-game observation.
        """
        ...
    def _encode_entities(
        self, units: Units, max_units: int, return_tags: bool = False
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Optional[List[int]], np.ndarray]:
        """Encode the visible entity set.

        Returns:
            ``(features, categorical, positions, mask, tags, aux)`` where
            ``aux`` is a ``(n, 4)`` float32 helper of ``[hp_raw, alliance,
            selected, has_buff]`` reused by the spatial scatter.
        """
        ...
    def _build_playable_mask(self) -> np.ndarray: ...
    def _spawn_xy(self) -> tuple[float, float]:
        """Start location in map units (camera proxy)."""
        ...
    def _encode_spatial(
        self,
        entity_positions: np.ndarray,
        entity_mask: np.ndarray,
        entity_aux: np.ndarray,
        target_spatial_size: tuple[int, int] = TARGET_SPATIAL_SIZE,
    ) -> Tuple[np.ndarray, int]:
        """Build the ``(C, H, W)`` map stack; see ``SPATIAL_CHANNEL_NAMES``.

        Returns:
            ``(stack, n_effects)`` with the count of persistent-effect
            objects drawn onto the effect plane.
        """
        ...
    def _encode_scalar(self, n_effects: float = ...) -> np.ndarray:
        """Global full-game vector; see ``SCALAR_FEATURE_NAMES``."""
        ...
