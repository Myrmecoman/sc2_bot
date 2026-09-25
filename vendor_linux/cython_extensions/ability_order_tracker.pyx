# cython: boundscheck=False, wraparound=False, cdivision=True
"""
Optimized Cython implementation for tracking ability counts and build progress.
Replaces the Python _abilities_count_and_build_progress method for maximum speed.
"""

from sc2.data import Race

from cython_extensions.ability_mapping cimport map_unit_value
from cython_extensions.ability_mapping cimport STRUCT_ABILITIES
from sc2.data import Race
from cython cimport boundscheck, wraparound
from libc.string cimport memset
from cpython.mem cimport PyMem_Malloc, PyMem_Free




#TEMPORARRY placing it here until we cythonize the tracker file, does not work yet
cdef struct AbilityCount:
    int ability_id
    int count

# Disable Python checks for speed
@boundscheck(False)
@wraparound(False)
cpdef AbilityCount[:] abilities_count_structures(object bot):
    """
    Build a C array indexed by ability_id that stores counts.
    Returns: memoryview of AbilityCount (size = 2200)
    """
    cdef:
        unsigned int MIN_ABILITIES = 0
        unsigned int MAX_ABILITIES = 2200
        AbilityBuffer buf = AbilityBuffer(MAX_ABILITIES)
        AbilityCount* arr = buf.ptr
        object unit, order, orders
        int ability_id



        object structures = bot.structures
        object workers = bot.workers
        bint is_protoss = bot.race == Race.Protoss

        bint is_zerg = bot.race == Race.Zerg

        unsigned int len_structures = len(structures)
        unsigned int len_workers = len(workers)
        unsigned int len_orders, i, j, struct_ability_int, unit_id_int

        double completed_build_progress = 1.0


    #FUTURE exclude this for ares?
    for i in range(len_workers):
        unit = workers[i]
        orders = unit.orders
        len_orders = len(orders)
        for j in range(len_orders):
            order = orders[j]
            ability_id = <int> order.ability._proto.ability_id 
            if 0 <= ability_id < MAX_ABILITIES:
                arr[ability_id].count += 1


    # Structures → build progress < 1.0 → increment creation ability
    if is_protoss:
        for i in range(len_structures):
            unit = structures[i]
            if <double> unit._proto.build_progress < completed_build_progress:
                unit_id_int = <int> unit._proto.unit_type
                ability_id = <int> map_unit_value(unit_id_int)
                if ability_id!=-1:
                    arr[ability_id].count += 1

    elif is_zerg:
        #Zerg
        for i in range(len_structures):
            unit = structures[i]
            unit_id_int = <int> unit._proto.unit_type
            ability_id = <int> map_unit_value(unit_id_int)
            if <double> unit._proto.build_progress < 1.0:    
                if ability_id!=-1:
                    arr[ability_id].count += 1
            elif STRUCT_ABILITIES[ability_id]==2:  #identify Lair, Hive and Command Center
                # Lair and Hive
                orders = unit.orders
                len_orders = len(orders)
                for j in range(len_orders):
                    order = orders[j]
                    ability_id = <int> order.ability._proto.ability_id
                    if STRUCT_ABILITIES[ability_id]:
                        arr[ability_id].count += 1

    else:
        for i in range(len_structures):
            unit = structures[i]
            unit_id_int = <int> unit._proto.unit_type
            ability_id = <int> map_unit_value(unit_id_int)
            if <double> unit._proto.build_progress < 1.0:
                
                
                if STRUCT_ABILITIES[ability_id]:
                    arr[ability_id].count += 1

            elif STRUCT_ABILITIES[ability_id]==2:  #identify Commandcenter, but in the same way as others to save time
             # Command Center for OC and PF
                orders = unit.orders
                len_orders = len(orders)
                for j in range(len_orders):
                    order = orders[j]
                    ability_id = <int> order.ability._proto.ability_id
                    if STRUCT_ABILITIES[ability_id]:
                        arr[ability_id].count += 1


        
    # Return as Python-usable memoryview
    return buf.mv


def cache_per_game_loop(func):
    cache_name = f"_{func.__name__}_cache"
    loop_name = f"_{func.__name__}_loop"
    def wrapper(bot, *args, **kwargs):
        current_loop = bot.state.game_loop
        if getattr(bot, loop_name, None) == current_loop:
            return getattr(bot, cache_name)
        result = func(bot, *args, **kwargs)
        setattr(bot, cache_name, result)
        setattr(bot, loop_name, current_loop)
        return result
    return wrapper

@cache_per_game_loop
def cy_abilities_count_structures(bot):
    return abilities_count_structures(bot)



cdef class AbilityBuffer:
    cdef AbilityCount* ptr
    cdef int size

    def __cinit__(self, int size):
        self.size = size
        self.ptr = <AbilityCount*> PyMem_Malloc(size * sizeof(AbilityCount))
        memset(self.ptr, 0, size * sizeof(AbilityCount))

    def __dealloc__(self):
        if self.ptr != NULL:
            PyMem_Free(self.ptr)
            self.ptr = NULL

    property mv:
        def __get__(self):
            # Return a Python memoryview
            return <AbilityCount[:self.size]> self.ptr
