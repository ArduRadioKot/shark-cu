import ctypes
from CapsuleSDK.Error import *
from typing import Callable
from CapsuleSDK.CapsulePointersImpl import capsule_pointers

class Emotions_States(ctypes.Structure):
    _fields_ = [
        ("timestampMilli", ctypes.c_int64),
        ("focus", ctypes.c_float),
        ("chill", ctypes.c_float),
        ("stress", ctypes.c_float),
        ("anger", ctypes.c_float),
        ("selfControl", ctypes.c_float),
    ]

class Emotions:
    _name_in_pointers_map = "Emotions"
    def __init__(self, device, lib):
        self._lib = lib
        self._lib.clCEmotions_Create.restype = ctypes.POINTER(ctypes.c_int)
        self._lib.clCEmotions_Create.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(Error)]
        error = Error()
        self._pointer = self._lib.clCEmotions_Create(device.get_c_pointer(), ctypes.byref(error))
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def set_on_states_update(self, callback: Callable[['Emotions', Emotions_States], None]):
        global _emotions_lib_impl, _emotions_states_callback
        _emotions_lib_impl = self._lib
        _emotions_states_callback = callback
        self.__save_obj()
        self._lib.clCEmotions_SetOnEmotionalStatesUpdateEvent(self._pointer, states_impl)

    def set_on_error(self, callback: Callable[['Emotions', str], None]):
        global _emotions_lib_impl, _emotions_error_callback
        _emotions_lib_impl = self._lib
        _emotions_error_callback = callback
        self.__save_obj()
        self._lib.clCEmotions_SetOnErrorEvent(self._pointer, error_impl)

    def __save_obj(self):
        global capsule_pointers
        capsule_pointers[self._name_in_pointers_map] = self


# impl details
_emotions_lib_impl = None

_emotions_states_callback = None
@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(Emotions_States))
def states_impl(_emotions, states):
    global _emotions_lib_impl, _emotions_states_callback
    _emotions_states_callback(capsule_pointers['Emotions'], states.contents)

_emotions_error_callback = None
@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int), ctypes.c_char_p)
def error_impl(_emotions, error):
    global _emotions_lib_impl, _emotions_error_callback
    _emotions_error_callback(capsule_pointers['Emotions'], str(error))