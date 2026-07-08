import ctypes
from CapsuleSDK.Error import *
from typing import Callable
from CapsuleSDK.CapsulePointersImpl import capsule_pointers

class PhysiologicalStates_Value(ctypes.Structure):
    _fields_ = [
        ("timestampMilli", ctypes.c_int64),
        ("relaxation", ctypes.c_float),
        ("fatigue", ctypes.c_float),
        ("none", ctypes.c_float),
        ("concentration", ctypes.c_float),
        ("involvement", ctypes.c_float),
        ("stress", ctypes.c_float),
        ("nfbArtifacts", ctypes.c_bool),
        ("cardioArtifacts", ctypes.c_bool),
    ]

    def __init__(self):
        self.timestampMilli = -1
        self.relaxation = -1.0
        self.fatigue = -1.0
        self.none = -1.0
        self.concentration = -1.0
        self.involvement = -1.0
        self.stress = -1.0
        self.nfbArtifacts = False
        self.cardioArtifacts = False


class PhysiologicalStates_Baselines(ctypes.Structure):
    _fields_ = [
        ("timestampMilli", ctypes.c_int64),
        ("alpha", ctypes.c_float),
        ("beta", ctypes.c_float),
        ("alphaGravity", ctypes.c_float),
        ("betaGravity", ctypes.c_float),
        ("concentration", ctypes.c_float),
    ]

    def __init__(self, timestamp_milli=-1,
                    alpha = -1.0,
                    beta = -1.0,
                    alpha_gravity = -1.0,
                    beta_gravity = -1.0,
                    concentration = -1.0):
        
        self.timestampMilli = timestamp_milli
        self.alpha = alpha
        self.beta = beta
        self.alphaGravity = alpha_gravity
        self.betaGravity = beta_gravity
        self.concentration = concentration


class PhysiologicalStates:
    _name_in_pointers_map = "PhysiologicalStates"
    def __init__(self, device, lib):
        self._lib = lib
        self._lib.clCPhysiologicalStates_Create.restype = ctypes.POINTER(ctypes.c_int)
        self._lib.clCPhysiologicalStates_Create.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(Error)]
        error = Error()
        self._pointer = self._lib.clCPhysiologicalStates_Create(device.get_c_pointer(), ctypes.byref(error))
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)
        
    def import_baselines(self, baselines : PhysiologicalStates_Baselines):
        self._lib.clCPhysiologicalStates_ImportBaselines.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.POINTER(PhysiologicalStates_Baselines)]
        self._lib.clCPhysiologicalStates_ImportBaselines(self._pointer, ctypes.byref(baselines))

    def calibrate_baselines(self):
        self._lib.clCPhysiologicalStates_StartBaselineCalibration.argtypes = [ctypes.POINTER(ctypes.c_int)]
        self._lib.clCPhysiologicalStates_StartBaselineCalibration(self._pointer)

    def set_on_states(self, callback: Callable[['PhysiologicalStates', PhysiologicalStates_Value], None]):
        global _ps_lib_impl, _ps_states_callback
        _ps_lib_impl = self._lib
        _ps_states_callback = callback
        self.__save_obj()
        error = Error()
        self._lib.clCPhysiologicalStates_SetOnStatesUpdateEvent(self._pointer, states_impl, ctypes.byref(error))
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def set_on_calibrated(self, callback: Callable[['PhysiologicalStates', PhysiologicalStates_Baselines], None]):
        global _ps_lib_impl, _ps_calibrated_callback
        _ps_lib_impl = self._lib
        _ps_calibrated_callback = callback
        self.__save_obj()
        error = Error()
        self._lib.clCPhysiologicalStates_SetOnCalibratedEvent(self._pointer, calibrated_impl, ctypes.byref(error))
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def set_on_calibration_progress(self, callback: Callable[['PhysiologicalStates', float], None]):
        global _ps_lib_impl, _ps_calibration_progress_callback
        _ps_lib_impl = self._lib
        _ps_calibration_progress_callback = callback
        self.__save_obj()
        error = Error()
        self._lib.clCPhysiologicalStates_SetOnCalibrationProgressUpdateEvent(self._pointer, calibration_progress_impl, ctypes.byref(error))
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def set_on_individual_nfb(self, callback: Callable[['PhysiologicalStates'], None]):
        global _ps_lib_impl, _ps_individual_nfb_callback
        _ps_lib_impl = self._lib
        _ps_individual_nfb_callback = callback
        self.__save_obj()
        error = Error()
        self._lib.clCPhysiologicalStates_SetOnIndividualNFBUpdateEvent(self._pointer, individual_nfb_impl, ctypes.byref(error))
        if error.code is not Error_Code.OK:
            raise CapsuleException(error)

    def __save_obj(self):
        global capsule_pointers
        capsule_pointers[self._name_in_pointers_map] = self


# impl details
_ps_lib_impl = None

_ps_states_callback = None
@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(PhysiologicalStates_Value))
def states_impl(_ps, value):
    global _ps_lib_impl, _ps_states_callback, capsule_pointers
    _ps_states_callback(capsule_pointers['PhysiologicalStates'], value.contents)

_ps_calibrated_callback = None
@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(PhysiologicalStates_Baselines))
def calibrated_impl(_ps, baselines):
    global _ps_lib_impl, _ps_calibrated_callback, capsule_pointers
    _ps_calibrated_callback(capsule_pointers['PhysiologicalStates'], baselines.contents)

_ps_calibration_progress_callback = None
@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int), ctypes.c_float)
def calibration_progress_impl(_ps, progress):
    global _ps_lib_impl, _ps_calibration_progress_callback, capsule_pointers
    _ps_calibration_progress_callback(capsule_pointers['PhysiologicalStates'], progress)

_ps_individual_nfb_callback = None
@ctypes.CFUNCTYPE(None, ctypes.POINTER(ctypes.c_int))
def individual_nfb_impl(_ps):
    global _ps_lib_impl, _ps_individual_nfb_callback, capsule_pointers
    _ps_individual_nfb_callback(capsule_pointers['PhysiologicalStates'])