"""Matplotlib visualisation for feature observations.

Quick in-game / post-game debugging of what the encoder actually sees::

    from cython_extensions.features import Features
    from cython_extensions.plots import plot_observation

    async def on_step(self, iteration: int):
        if iteration % 100 == 0:
            obs = Features(self).build_observation()
            plot_observation(obs, save_path=f"obs_{iteration}.png")

All helpers accept either an :class:`Observation`
(:mod:`cython_extensions.features`) or the underlying raw arrays, and work
headless (``save_path``) as well as interactively (``show=True``).

``matplotlib`` is an optional (dev-only) dependency: every helper lazily
imports ``pyplot`` on first use, and degrades to a ``UserWarning`` + ``None``
return when it is not installed, so importing this module never fails.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, List, Optional, Sequence, Tuple, Union

import numpy as np

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

    from cython_extensions.features import Observation

ObsLike = Union["Observation", np.ndarray, tuple]

_ALLIANCE_COLORS = ("tab:blue", "tab:cyan", "tab:gray", "tab:red")
_ALLIANCE_NAMES = ("self", "ally", "neutral", "enemy")

# Entity layout mirrors cython_extensions/features.pyx (EN_X/Y/HP, EC_*).
# Literals are used because the layout constants are C-level (cdef) there.
_EN_X, _EN_Y, _EN_HP = 0, 1, 3
_EC_TYPE, _EC_ALLIANCE = 0, 1


_MPL_MISSING_MSG = (
    "cython_extensions.plots needs matplotlib, which is a dev-only "
    "dependency (`pip install matplotlib` or `poetry install --with dev`). "
    "Skipping plot."
)


def _require_pyplot():
    """Return ``pyplot``, or warn + ``None`` when matplotlib is missing."""
    try:
        import matplotlib.pyplot as plt

        return plt
    except ImportError:
        warnings.warn(_MPL_MISSING_MSG, UserWarning, stacklevel=3)
        return None


def _unwrap_spatial(spatial) -> np.ndarray:
    """Accept ``Observation`` or array, return ``(C, H, W)`` float32."""
    arr = getattr(spatial, "spatial", spatial)
    arr = np.asarray(arr, dtype=np.float32)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.ndim != 3:
        raise ValueError(f"expected (C, H, W) spatial, got {arr.shape}")
    return arr


def _unwrap_entities(obs) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Accept ``Observation`` or a 4-tuple, return batched-removed arrays."""
    if hasattr(obs, "entity_features"):
        feats, cats, mask, pos = (
            obs.entity_features,
            obs.entity_categorical,
            obs.entity_mask,
            obs.entity_positions,
        )
    else:
        feats, cats, mask, pos = obs
    feats = np.asarray(feats, dtype=np.float32)
    cats = np.asarray(cats, dtype=np.int64)
    mask = np.asarray(mask, dtype=np.float32)
    pos = np.asarray(pos, dtype=np.float32)
    if feats.ndim == 3:
        feats, cats, mask, pos = feats[0], cats[0], mask[0], pos[0]
    return feats, cats, mask, pos


def _unwrap_scalar(scalar) -> tuple[np.ndarray, List[str]]:
    from cython_extensions.features import SCALAR_FEATURE_NAMES

    arr = getattr(scalar, "scalar", scalar)
    arr = np.asarray(arr, dtype=np.float32).ravel()
    return arr, list(SCALAR_FEATURE_NAMES)


def _finish(fig, save_path: Optional[str], show: bool):
    plt = _require_pyplot()
    if plt is None:  # warned already; nothing was drawn without pyplot
        return fig
    if save_path:
        fig.savefig(save_path, dpi=110, bbox_inches="tight")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return fig


def plot_spatial(
    obs: ObsLike,
    channels: Optional[Sequence[Union[int, str]]] = None,
    ncols: int = 6,
    figsize: Optional[Tuple[float, float]] = None,
    cmap: str = "viridis",
    save_path: Optional[str] = None,
    show: bool = False,
) -> Optional[Figure]:
    """Plot spatial planes on a labelled grid.

    Args:
        obs: Observation or ``(C, H, W)`` / ``(1, C, H, W)`` array.
        channels: Subset to draw, as indices or names from
            ``SPATIAL_CHANNEL_NAMES``. Defaults to all channels.
        ncols: Grid columns.
        figsize: Passed to ``plt.subplots``.
        cmap: Matplotlib colormap.
        save_path: If given, write a PNG here (headless friendly).
        show: Call ``plt.show()`` (needs a display / GUI backend).

    Returns:
        The matplotlib figure, or ``None`` (with a warning) when matplotlib
        is not installed.
    """
    from cython_extensions.features import SPATIAL_CHANNEL_NAMES

    plt = _require_pyplot()
    if plt is None:
        return None
    stack = _unwrap_spatial(obs)
    names = list(SPATIAL_CHANNEL_NAMES)
    if channels is None:
        idx = list(range(stack.shape[0]))
    else:
        idx = [names.index(c) if isinstance(c, str) else int(c) for c in channels]
    n = len(idx)
    ncols = max(1, min(ncols, n))
    nrows = (n + ncols - 1) // ncols
    if figsize is None:
        figsize = (2.6 * ncols, 2.8 * nrows)
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, squeeze=False)
    for k, ch in enumerate(idx):
        ax = axes[k // ncols][k % ncols]
        im = ax.imshow(stack[ch], cmap=cmap, vmin=0.0, vmax=1.0, origin="upper")
        ax.set_title(names[ch] if ch < len(names) else f"ch{ch}", fontsize=9)
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    for k in range(n, nrows * ncols):
        axes[k // ncols][k % ncols].axis("off")
    fig.suptitle(f"spatial {tuple(stack.shape)}", fontsize=11)
    fig.tight_layout()
    return _finish(fig, save_path, show)


def plot_entities(
    obs: ObsLike,
    ax: Optional[Axes] = None,
    background: Optional[str] = "height",
    save_path: Optional[str] = None,
    show: bool = False,
) -> Optional[Axes]:
    """Scatter entity positions coloured by alliance, sized by hp ratio.

    Args:
        obs: Observation or ``(features, categorical, mask, positions)``.
        ax: Axes to draw on (created if None).
        background: Spatial plane to draw underneath (name from
            ``SPATIAL_CHANNEL_NAMES``), or None for a plain scatter.
        save_path: If given, write a PNG here.
        show: Call ``plt.show()``.

    Returns:
        The axes drawn on, or ``None`` (with a warning) when matplotlib
        is not installed.
    """
    from cython_extensions.features import SPATIAL_CHANNEL_NAMES

    plt = _require_pyplot()
    if plt is None:
        return None
    feats, cats, mask, pos = _unwrap_entities(obs)
    valid = mask > 0.5
    fig = None
    if ax is None:
        fig, ax = plt.subplots(figsize=(7, 7))
    if background is not None and hasattr(obs, "spatial"):
        names = list(SPATIAL_CHANNEL_NAMES)
        if background in names:
            plane = _unwrap_spatial(obs.spatial)[names.index(background)]
            h, w = plane.shape
            ax.imshow(
                plane,
                cmap="terrain",
                alpha=0.55,
                origin="upper",
                extent=(0, 1, 1, 0),
            )
            ax.set_xlim(0, 1)
            ax.set_ylim(1, 0)
    for alliance in range(4):
        sel = valid & (cats[:, _EC_ALLIANCE] == alliance)
        if not sel.any():
            continue
        sizes = 12.0 + 90.0 * feats[sel, _EN_HP]
        ax.scatter(
            pos[sel, 0],
            pos[sel, 1],
            s=sizes,
            c=[_ALLIANCE_COLORS[alliance]],
            label=f"{_ALLIANCE_NAMES[alliance]} ({int(sel.sum())})",
            alpha=0.75,
            edgecolors="k",
            linewidths=0.4,
        )
    ax.set_xlabel("x (normalised)")
    ax.set_ylabel("y (normalised)")
    ax.set_title(f"entities ({int(valid.sum())})")
    ax.legend(loc="upper right", fontsize=8)
    ax.set_aspect("equal", adjustable="box")
    if fig is not None:
        fig.tight_layout()
        _finish(fig, save_path, show)
    elif save_path:
        fig = ax.get_figure()
        fig.savefig(save_path, dpi=110, bbox_inches="tight")
        if show:
            plt.show()
    return ax


def plot_scalar(
    obs: ObsLike,
    ax: Optional[Axes] = None,
    save_path: Optional[str] = None,
    show: bool = False,
) -> Optional[Axes]:
    """Horizontal bar chart of the scalar vector with feature names.

    Args:
        obs: Observation or ``(D,)`` / ``(1, D)`` array.
        ax: Axes to draw on (created if None).
        save_path: If given, write a PNG here.
        show: Call ``plt.show()``.

    Returns:
        The axes drawn on, or ``None`` (with a warning) when matplotlib
        is not installed.
    """
    plt = _require_pyplot()
    if plt is None:
        return None
    values, names = _unwrap_scalar(obs)
    names = names[: len(values)]
    fig = None
    if ax is None:
        fig, ax = plt.subplots(figsize=(7, max(3.0, 0.28 * len(values))))
    y = np.arange(len(values))
    ax.barh(y, values, color="tab:blue")
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=7)
    ax.set_xlim(0, 1)
    ax.set_xlabel("value")
    ax.set_title("scalar")
    ax.invert_yaxis()
    if fig is not None:
        fig.tight_layout()
        _finish(fig, save_path, show)
    elif save_path:
        fig = ax.get_figure()
        fig.savefig(save_path, dpi=110, bbox_inches="tight")
        if show:
            plt.show()
    return ax


def plot_observation(
    obs: ObsLike,
    save_path: Optional[str] = None,
    show: bool = False,
    figsize: Tuple[float, float] = (14, 7),
) -> Optional[Figure]:
    """One-figure summary: entity map over terrain plus scalar bars.

    Args:
        obs: Observation from ``Features.build_observation()``.
        save_path: If given, write a PNG here (headless friendly).
        show: Call ``plt.show()``.
        figsize: Figure size.

    Returns:
        The matplotlib figure, or ``None`` (with a warning) when matplotlib
        is not installed.
    """
    plt = _require_pyplot()
    if plt is None:
        return None
    fig, (ax_map, ax_scalar) = plt.subplots(1, 2, figsize=figsize)
    plot_entities(obs, ax=ax_map, background="height")
    plot_scalar(obs, ax=ax_scalar)
    fig.tight_layout()
    return _finish(fig, save_path, show)
