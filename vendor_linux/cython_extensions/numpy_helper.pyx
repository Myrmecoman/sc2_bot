import numpy as np

cimport numpy as cnp
from libc.math cimport floor

from cython import boundscheck, wraparound


cpdef int cy_last_index_with_value(
    const unsigned char[:, :] grid,
    const unsigned char value,
    points
):
    cdef:
        int x
        int y
        int last_valid_idx = 0
        int stop_val = len(points)

    if stop_val == 0:
        return -1

    for last_valid_idx in range(stop_val):
        x = points[last_valid_idx][0]
        y = points[last_valid_idx][1]
        if grid[y][x] != value:
            return last_valid_idx - 1
    return last_valid_idx

@boundscheck(False)
@wraparound(False)
cpdef bint cy_point_below_value(
        cnp.ndarray[cnp.npy_float32, ndim=2] grid,
        (double, double) position,
        double weight_safety_limit = 1.0
):
    cdef double weight = 0.0
    cdef unsigned int x = <unsigned int> floor(position[0])
    cdef unsigned int y = <unsigned int> floor(position[1])

    weight = grid[x, y]
    # np.inf check if drone is pathing near a spore crawler
    return weight == np.inf or weight <= weight_safety_limit

cpdef cy_points_with_value(
    const unsigned char[:, :] grid,
    const unsigned char value,
    points,
):
    cdef:
        int i, x, y
        int idx = 0
        (int, int) [2000] valid_points

    for i in range(len(points)):
        x = points[i][0]
        y = points[i][1]
        if grid[y][x] == value:
            valid_points[idx] = (x, y)
            idx += 1
            if idx >= 2000:
                break
    return list(valid_points)[:idx]

cpdef bint cy_all_points_below_max_value(
    const cnp.float32_t[:, :] grid,
    cnp.float32_t max_value,
    points_to_check
):
    cdef:
        int x
        int y

    for p in points_to_check:
        x = p[0]
        y = p[1]
        if np.inf > grid[x][y] > max_value:
            return False

    return True


cpdef bint cy_all_points_have_value(
    const unsigned char[:, :] grid,
    const unsigned char value,
    points
):
    cdef:
        int x
        int y

    if len(points) == 0:
        return False

    for p in points:
        x = p[0]
        y = p[1]
        if grid[y][x] != value:
            return False
    return True
