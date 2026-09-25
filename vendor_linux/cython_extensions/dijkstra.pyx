# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: cdivision=True
# cython: initializedcheck=False
# cython: nonecheck=False

import numpy as np
cimport numpy as cnp
from cpython.mem cimport PyMem_Malloc, PyMem_Realloc, PyMem_Free
from numpy.math cimport INFINITY
from libc.math cimport sqrt, round, M_SQRT2
from libc.stdint cimport int8_t

# -----------------------------------------------------------------------------
# Types & Constants
# -----------------------------------------------------------------------------

ctypedef cnp.float32_t DTYPE_t
ctypedef cnp.int32_t INDEX_t
ctypedef int8_t DIR_t

cdef INDEX_t MIN_CAPACITY = 1024
cdef DIR_t NO_DIRECTION = -1
cdef INDEX_t NO_INDEX = -1
cdef INDEX_t[8] OFFSET_X = [-1, 1, 0, 0, -1, -1, 1, 1]
cdef INDEX_t[8] OFFSET_Y = [0, 0, -1, 1, -1, 1, -1, 1]
cdef DTYPE_t[8] COST_DIRECTION = [1.0, 1.0, 1.0, 1.0, M_SQRT2, M_SQRT2, M_SQRT2, M_SQRT2]

# -----------------------------------------------------------------------------
# Heap Operations
# -----------------------------------------------------------------------------

cdef inline void bubble_up(
    INDEX_t* index,
    DTYPE_t* priority,
    INDEX_t* indirection,
    INDEX_t i
):
    cdef INDEX_t parent
    cdef INDEX_t move_index = index[i]
    cdef DTYPE_t move_priority = priority[i]
    while i > 0:
        parent = (i - 1) >> 1
        if move_priority < priority[parent]:
            index[i] = index[parent]
            priority[i] = priority[parent]
            indirection[index[i]] = i
            i = parent
        else:
            break
    index[i] = move_index
    priority[i] = move_priority
    indirection[move_index] = i

cdef inline void bubble_down(
    INDEX_t* index,
    DTYPE_t* priority,
    INDEX_t* indirection,
    INDEX_t i,
    INDEX_t size,
):
    cdef INDEX_t child
    cdef INDEX_t move_index = index[i]
    cdef DTYPE_t move_priority = priority[i]
    cdef INDEX_t half_size = size >> 1
    while i < half_size:
        child = (i << 1) + 1
        if child + 1 < size and priority[child + 1] < priority[child]:
            child += 1
        if move_priority <= priority[child]:
            break
        index[i] = index[child]
        priority[i] = priority[child]
        indirection[index[i]] = i
        i = child
    index[i] = move_index
    priority[i] = move_priority
    indirection[move_index] = i

cdef inline void grow_heap(
    INDEX_t** index_ptr,
    DTYPE_t** priority_ptr,
    INDEX_t* capacity_ptr
) except *:
    cdef INDEX_t new_capacity = capacity_ptr[0] * 2
    cdef INDEX_t* new_index = <INDEX_t*>PyMem_Realloc(index_ptr[0], new_capacity * sizeof(INDEX_t))
    if not new_index:
        raise MemoryError("Heap allocation failed in cy_dijkstra.")
    index_ptr[0] = new_index
    cdef DTYPE_t* new_priority = <DTYPE_t*>PyMem_Realloc(priority_ptr[0], new_capacity * sizeof(DTYPE_t))
    if not new_priority:
        raise MemoryError("Heap allocation failed in cy_dijkstra.")
    priority_ptr[0] = new_priority
    capacity_ptr[0] = new_capacity

# -----------------------------------------------------------------------------
# Core Algorithm
# -----------------------------------------------------------------------------

cdef void dijkstra_core(
    INDEX_t** index_ptr,
    DTYPE_t** priority_ptr,
    INDEX_t* capacity_ptr,
    INDEX_t* indirection,
    INDEX_t* size_ptr,
    INDEX_t start,
    DTYPE_t* distance,
    DTYPE_t* cost,
    DIR_t* direction,
    INDEX_t stride
):

    cdef:
        INDEX_t i, neighbour, k
        DTYPE_t d, alternative, cost_i
        INDEX_t* index = index_ptr[0]
        DTYPE_t* priority = priority_ptr[0]
        INDEX_t size = size_ptr[0]
        INDEX_t[8] offsets = [-stride, stride, -1, 1, -stride - 1, -stride + 1, stride - 1, stride + 1]

    while size > 0:
        if start != NO_INDEX and priority[0] >= distance[start]:
            break

        # pop minimum
        i = index[0]
        d = priority[0]
        cost_i = cost[i]
        indirection[i] = NO_INDEX
        size -= 1
        if size > 0:
            index[0] = index[size]
            priority[0] = priority[size]
            indirection[index[0]] = 0
            bubble_down(index, priority, indirection, 0, size)

        # iterate neighbours
        for k in range(8):
            neighbour = i + offsets[k]
            alternative = d + 0.5 * COST_DIRECTION[k] * (cost_i + cost[neighbour])
            if alternative < distance[neighbour]:
                distance[neighbour] = alternative
                direction[neighbour] = <DIR_t>k

                if indirection[neighbour] != NO_INDEX:
                    # node already in heap, decrease key
                    priority[indirection[neighbour]] = alternative
                    bubble_up(index, priority, indirection, indirection[neighbour])

                else:
                    # dynamic resize
                    if size >= capacity_ptr[0]:
                        grow_heap(index_ptr, priority_ptr, capacity_ptr)
                        index = index_ptr[0]
                        priority = priority_ptr[0]
                    # enqueue
                    index[size] = neighbour
                    priority[size] = alternative
                    indirection[neighbour] = size
                    bubble_up(index, priority, indirection, size)
                    size += 1

    size_ptr[0] = size

# -----------------------------------------------------------------------------
# Python Interface
# -----------------------------------------------------------------------------

cdef class DijkstraPathing:
    cdef DIR_t[:, ::1] direction
    cdef DTYPE_t[:, ::1] distance

    cdef INDEX_t* index
    cdef DTYPE_t* priority
    cdef INDEX_t capacity
    cdef DTYPE_t[:, ::1] cost
    cdef INDEX_t[:, ::1] indirection
    cdef INDEX_t size
    cdef INDEX_t stride

    def __cinit__(self,
                  const DTYPE_t[:, ::1] cost,
                  const INDEX_t[:, ::1] targets,
                  const DTYPE_t[::1] priorities):
        cdef INDEX_t num_targets = targets.shape[0]
        self.cost = np.pad(cost, 1, "constant", constant_values=INFINITY)
        self.stride = self.cost.shape[1]
        self.direction = np.full_like(self.cost, NO_DIRECTION, dtype=np.int8)
        self.indirection = np.full_like(self.cost, NO_INDEX, dtype=np.int32)
        self.distance = np.full_like(self.cost, INFINITY)
        self.capacity = max(MIN_CAPACITY, 2 * num_targets)
        self.size = 0
        self.index = <INDEX_t*>PyMem_Malloc(self.capacity * sizeof(INDEX_t))
        self.priority = <DTYPE_t*>PyMem_Malloc(self.capacity * sizeof(DTYPE_t))
        if not self.index or not self.priority:
            raise MemoryError("Could not allocate heap memory")
        for k in range(num_targets):
            self._add_target(
                self.stride * (targets[k, 0] + 1) + (targets[k, 1] + 1),
                -priorities[k],
            )

    cdef void _add_target(self, INDEX_t i, DTYPE_t seed):
        cdef INDEX_t* indirection = &self.indirection[0,0]
        cdef DTYPE_t* distance = &self.distance[0,0]
        self.index[self.size] = i
        self.priority[self.size] = seed
        indirection[i] = self.size
        distance[i] = seed
        bubble_up(self.index, self.priority, indirection, self.size)
        self.size += 1

    def __dealloc__(self):
        PyMem_Free(self.index)
        PyMem_Free(self.priority)

    cdef void _advance_heap(self, INDEX_t start):
        dijkstra_core(
            &self.index,
            &self.priority,
            &self.capacity,
            &self.indirection[0, 0],
            &self.size,
            start,
            &self.distance[0, 0],
            &self.cost[0, 0],
            &self.direction[0, 0],
            self.stride
        )

    cpdef get_path(self, object source, int limit=0, int max_distance=1):
        """

        Follow the path from a given source using the forward pointer grids.

        Parameters
        ----------
        source :
            Start point.
        limit :
            Maximum length of the returned path. Defaults to 0 indicating no limit.
        max_distance :
            Size of the search region for a valid starting point. Defaults to 1.

        Returns
        -------
        list[tuple[int, int]] :
            The lowest cost path from source to any of the targets.

        """
        cdef INDEX_t x0, y0
        x0, y0 = self._find_starting_point(np.asarray(source, dtype=np.float32), max_distance=max_distance)
        if x0 < 0 or y0 < 0 or x0 >= self.cost.shape[0] or y0 >= self.cost.shape[1] or self.cost[x0, y0] == INFINITY:
            return [(x0 - 1, y0 - 1)]
        self._advance_heap(x0 * self.stride + y0)
        return self._follow_directions(x0, y0, limit)

    cpdef DTYPE_t get_distance(self, object source, bint upper_bound=False):
        """

        Get the pathing distance from a given source to the nearest target.

        Parameters
        ----------
        source :
            Start point.
        upper_bound :
            If False (default), compute exact distance by advancing the heap.
            If True, return current distance estimate without advancing.

        Returns
        -------
        float :
            The lowest cost from source to any of the targets.

        """
        cdef INDEX_t x0, y0
        x0, y0 = self._find_starting_point(np.asarray(source, dtype=np.float32), max_distance=1)
        if x0 < 0 or y0 < 0 or x0 >= self.cost.shape[0] or y0 >= self.cost.shape[1] or self.cost[x0, y0] == INFINITY:
            return INFINITY
        if not upper_bound:
            self._advance_heap(x0 * self.stride + y0)
        return self.distance[x0, y0]

    cpdef object get_distance_grid(self, bint upper_bound=False):
        """

        Get the full pathing distance grid.

        Parameters
        ----------
        upper_bound :
            If False (default), fully evaluate the distance grid by advancing the heap.
            If True, return the current distance estimates without advancing.

        Returns
        -------
        np.ndarray :
            Readonly distance grid with the same shape as the input cost grid.

        """
        cdef object distance_grid
        if not upper_bound:
            self._advance_heap(NO_INDEX)
        distance_grid = np.asarray(self.distance)[
            1:self.distance.shape[0] - 1,
            1:self.distance.shape[1] - 1,
        ]
        distance_grid.setflags(write=False)
        return distance_grid

    cdef _follow_directions(self, INDEX_t x, INDEX_t y, INDEX_t limit):
        if limit == 0:
            limit = self.distance.size
        path = []
        while len(path) < limit:
            path.append((x - 1, y - 1))
            k = self.direction[x, y]
            if k == NO_DIRECTION:
                break
            x -= OFFSET_X[k]
            y -= OFFSET_Y[k]
        return path

    cdef (INDEX_t, INDEX_t) _find_starting_point(self, DTYPE_t[:] source, int max_distance):
        # +1 for padding
        cdef DTYPE_t fx0 = source[0] + 1
        cdef DTYPE_t fy0 = source[1] + 1
        cdef INDEX_t x0 = <INDEX_t>round(fx0)
        cdef INDEX_t y0 = <INDEX_t>round(fy0)
        cdef INDEX_t x_min = x0
        cdef INDEX_t y_min = y0
        cdef DTYPE_t min_d2 = INFINITY
        cdef DTYPE_t d2
        cdef INDEX_t x, y
        cdef INDEX_t x_start = max(1, x0 - max_distance)
        cdef INDEX_t x_end = min(self.distance.shape[0] - 1, x0 + max_distance + 1)
        cdef INDEX_t y_start = max(1, y0 - max_distance)
        cdef INDEX_t y_end = min(self.distance.shape[1] - 1, y0 + max_distance + 1)
        for x in range(x_start, x_end):
            for y in range(y_start, y_end):
                if self.cost[x, y] != INFINITY:
                    d2 = (x - fx0)**2 + (y - fy0)**2
                    if d2 < min_d2:
                        min_d2 = d2
                        x_min = x
                        y_min = y
        return x_min, y_min

cpdef DijkstraPathing cy_dijkstra(
    object cost,
    object targets,
    object priorities = None,
    bint checks_enabled = True,
):
    """

    Run Dijkstras algorithm on a grid, yielding many-target-shortest paths for each position.

    Parameters
    ----------
    cost :
        Cost grid. Entries must be positive. Set unpathable cells to infinity.
    targets :
        Target array of shape (*, 2) containing x and y coordinates of the target points.
    priorities :
        Optional vector of target priorities. Higher priority values make a target more
        attractive by lowering its initial heap seed.
    checks_enabled :
        Pass False to deactivate grid value and target coordinates checks. Defaults to True.

    Returns
    -------
    DijkstraPathing :
        Pathfinding object containing containing distance and forward pointer grids.

    """
    cdef const DTYPE_t[:, ::1] cost_array = np.ascontiguousarray(cost, dtype=np.float32)
    cdef const INDEX_t[:, ::1] target_array = np.ascontiguousarray(targets, dtype=np.int32)
    cdef const DTYPE_t[::1] priority_array
    if priorities is None:
        priorities = np.zeros(target_array.shape[0], dtype=np.float32)
    priority_array = np.ascontiguousarray(priorities, dtype=np.float32)
    if checks_enabled:
        if not np.greater(cost_array, 0.0).all():
            raise Exception("invalid cost: values must be positive")
        if (
            not np.greater_equal(targets, 0).all()
            or not np.less(targets[:, 0], cost.shape[0]).all()
            or not np.less(targets[:, 1], cost.shape[1]).all()
        ):
            raise Exception(f"invalid target: coordinates out of bounds")
    return DijkstraPathing(cost_array, target_array, priority_array)
