import numpy as np
from cython cimport boundscheck, wraparound
from libc.math cimport INFINITY

from sc2.data import Race
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from cython_extensions.geometry import cy_distance_to_squared
from cython_extensions.ability_mapping cimport map_unit_value, RESEARCH_BUILDING_ARRAY, map_upgrade_value
from cython_extensions.ability_order_tracker import cy_abilities_count_structures
cimport numpy as cnp

DOES_NOT_USE_LARVA: dict[UnitTypeId, UnitTypeId] = {
    UnitTypeId.BANELING: UnitTypeId.ZERGLING,
    UnitTypeId.BROODLORD: UnitTypeId.CORRUPTOR,
    UnitTypeId.LURKERMP: UnitTypeId.HYDRALISK,
    UnitTypeId.OVERSEER: UnitTypeId.OVERLORD,
    UnitTypeId.OVERLORDTRANSPORT: UnitTypeId.OVERLORD,
    UnitTypeId.RAVAGER: UnitTypeId.ROACH,
}

SPECIAL_TERRAN_BUILDINGS = {
    UnitTypeId.ORBITALCOMMAND,
    UnitTypeId.PLANETARYFORTRESS,
    UnitTypeId.BARRACKSREACTOR,
    UnitTypeId.BARRACKSTECHLAB,
    UnitTypeId.FACTORYREACTOR,
    UnitTypeId.FACTORYTECHLAB,
    UnitTypeId.STARPORTREACTOR,
    UnitTypeId.STARPORTTECHLAB,
}   


@boundscheck(False)
@wraparound(False)
cpdef bint cy_has_creep(
    cnp.ndarray[cnp.npy_bool, ndim=2] creep_numpy_grid,
    (double, double) position,
):
    """Optimized creep checking function with internal rounding"""
    cdef unsigned int x = int(position[0])
    cdef unsigned int y = int(position[1])
    return creep_numpy_grid[y, x] == 1

@boundscheck(False)
@wraparound(False)
cpdef bint cy_in_pathing_grid_ma(
    cnp.ndarray[cnp.float32_t, ndim=2] pathing_numpy_grid,
    (double, double) position,
):
    cdef unsigned int x = int(position[0])
    cdef unsigned int y = int(position[1])
    cdef double weight = pathing_numpy_grid[x, y]
    return weight >= 1.0 and weight != INFINITY

@boundscheck(False)
@wraparound(False)
cpdef bint cy_in_pathing_grid_burny(
    cnp.ndarray[cnp.npy_bool, ndim=2] pathing_numpy_grid,
    (double, double) position,
):
    cdef unsigned int x = int(position[0])
    cdef unsigned int y = int(position[1])
    return pathing_numpy_grid[y, x] == 1

@boundscheck(False)
@wraparound(False)
cpdef bint cy_pylon_matrix_covers(
        (double, double) position,
        object pylons,
        const unsigned char[:, :] height_grid,
        double pylon_build_progress = 1.0
    ):

    cdef:
        unsigned int x = int(position[0])
        unsigned int y = int(position[1])
        Py_ssize_t len_pylons = len(pylons)
        unsigned int position_height = height_grid[y, x]
        (double, double) pylon_position
        unsigned int pylon_height, i, _x, _y
        # range + pylon radius
        # squared distance
        double pylon_powered_distance = 42.25 #  + 1.125


    for i in range(len_pylons):
        pylon = pylons[i]
        pylon_position = pylon.position
        _x = int(pylon_position[0])
        _y = int(pylon_position[1])
        pylon_height = height_grid[_y, _x]
        if (
          pylon.build_progress >= pylon_build_progress
          and pylon_height >= position_height
          and cy_distance_to_squared(position, pylon_position) < pylon_powered_distance
        ):
          return True

    return False

cpdef unsigned int cy_unit_pending(object bot, object unit_type):
    cdef:
        unsigned int num_pending = 0
        Py_ssize_t len_units, len_orders, x, y
        object units_collection, unit

    if unit_type == UnitTypeId.ARCHON:
        trained_from = {UnitTypeId.DARKTEMPLAR, UnitTypeId.HIGHTEMPLAR}
    else:
        trained_from = UNIT_TRAINED_FROM[unit_type]

    if bot.race == Race.Zerg and unit_type != UnitTypeId.QUEEN:
        if unit_type in DOES_NOT_USE_LARVA:
            units_collection = bot.units
            len_units = len(bot.units)

            if unit_type == UnitTypeId.LURKERMP:
                trained_from = {UnitTypeId.LURKERMPEGG}
            elif unit_type == UnitTypeId.OVERSEER:
                trained_from = {UnitTypeId.OVERLORDCOCOON}
            else:
                trained_from = {UnitTypeId[f"{unit_type.name}COCOON"]}

            for x in range(len_units):
                unit = units_collection[x]
                if unit.type_id in trained_from:
                    num_pending += 1
            return num_pending
        # unit will be pending in eggs
        else:
            units_collection = bot.units
            len_units = len(units_collection)
            for x in range(len_units):
                unit = units_collection[x]
                if unit.type_id != UnitTypeId.EGG:
                    continue
                if unit.orders and unit.orders[0].ability.button_name.upper() == unit_type.name:
                    num_pending += 1
            return num_pending

    # all other units, check the structures they are built from
    else:
        units_collection = bot.structures
        len_units = len(units_collection)
        for x in range(len_units):
            structure = units_collection[x]
            len_orders = len(structure.orders)
            for y in range(len_orders):
                if structure.orders[y].ability.button_name.upper() == unit_type.name:
                    num_pending += 1

        return num_pending



cdef struct AbilityCount:
    int ability_id
    int count


@boundscheck(False)
@wraparound(False)
cpdef unsigned int cy_structure_pending(
        object bot,
        object structure_type,
    ):
    cdef:
        unsigned int num_pending = 0
        AbilityCount[:] counts_and_progress
        int target = <int> structure_type.value
        AbilityCount item
        Py_ssize_t arr_len
        int target_created_ability

    # Use optimized Cython function to get ability counts
    counts_and_progress = cy_abilities_count_structures(bot) #returns a c array memoryview

    arr_len = counts_and_progress.shape[0]
    target_created_ability = <int> map_unit_value(target)
    
    if 0 <= target_created_ability < arr_len:
        item = counts_and_progress[target_created_ability]
        num_pending += item.count
    return num_pending


@boundscheck(False)
@wraparound(False)
cpdef unsigned int cy_structure_pending_ares(
        object bot,
        object unit_type,
        bint include_planned=True
    ):
    cdef:
        unsigned int num_pending = 0
        object building_tracker
        object structure_collection = bot.mediator.get_own_structures_dict[unit_type]
        object tag
        object info
        int target = <int> unit_type.value
        AbilityCount item
        Py_ssize_t arr_len
        int target_created_ability
        AbilityCount[:] counts_and_progress

    # Add Ares planned buildings/units
    if include_planned:
        building_tracker = bot.mediator.get_building_tracker_dict
        for tag, info in building_tracker.items():
            if info["id"] == unit_type:
                num_pending += 1

    if (
        not include_planned or 
        (bot.race != Race.Terran or unit_type in SPECIAL_TERRAN_BUILDINGS)
    ):
        #Attention:
        # If a Include planned is true, buildings under construction for terran works only for special buildings

        # IT DOES NOT INCLUDE ANY STRUCTURES WHICH ARE CURRENTLY BUILD OUTSIDE OF ARES KNOWLEDGE
        #For that, use the normal pending structure function or disable include planned

        #if include planned is false, it checks every structure under construction, for terran too

        counts_and_progress = cy_abilities_count_structures(bot) #returns a c array memoryview


        arr_len = counts_and_progress.shape[0]
        target_created_ability = <int> map_unit_value(target)

        if 0 <= target_created_ability < arr_len:
            item = counts_and_progress[target_created_ability]
            num_pending += item.count
    
    return num_pending


cpdef float  cy_upgrade_pending(object bot, object upgrade_type):
    cdef:
        object researched_upgrades= bot.state.upgrades

        object structure_collection = bot.structures
        Py_ssize_t len_structures = len(structure_collection)

        int target = <int> upgrade_type.value
        int target_upgrade_ability = <int> map_upgrade_value(target)
        unsigned int i


    if upgrade_type in researched_upgrades:
        return 1.0

    for i in range(len_structures):
        structure = structure_collection[i]
        structure_id_int = <int> structure._proto.unit_type #retrieve the structure type as an integer
        if RESEARCH_BUILDING_ARRAY[structure_id_int] == 1: #check if the structure is a research building
            if structure.orders:
                order = structure.orders[0]
                ability_id = <int> order.ability._proto.ability_id #get the ability id of the current order
                if ability_id == target_upgrade_ability:
                    #get the build progress of the upgrade, which is the same as the build progress of the structure
                    return order.progress

    return 0.0 

    

    # Check if upgrade is currently being researched

