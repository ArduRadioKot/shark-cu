import ctypes

class Point3d(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("z", ctypes.c_float)
    ]

class MEMSTimedData:
    def __init__(self, pointer, lib):
        self._lib = lib
        self._pointer = pointer
        self._lib.clCMEMSTimedData_GetCount.restype = ctypes.c_int
        self._len = self._lib.clCMEMSTimedData_GetCount(self._pointer)
        
        self._lib.clCMEMSTimedData_GetAccelerometer.restype = Point3d
        self._lib.clCMEMSTimedData_GetAccelerometer.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        self._lib.clCMEMSTimedData_GetGyroscope.restype = Point3d
        self._lib.clCMEMSTimedData_GetGyroscope.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]
        self._lib.clCMEMSTimedData_GetTimestampMilli.restype = ctypes.c_uint64
        self._lib.clCMEMSTimedData_GetTimestampMilli.argtypes = [ctypes.POINTER(ctypes.c_int), ctypes.c_int]

    def __len__(self):
        return self._len
    
    def get_accelerometer(self, idx):
        return self._lib.clCMEMSTimedData_GetAccelerometer(self._pointer, idx)

    def get_gyroscope(self, idx):
        return self._lib.clCMEMSTimedData_GetGyroscope(self._pointer, idx)

    def get_timestamp(self, idx):
        return self._lib.clCMEMSTimedData_GetTimestampMilli(self._pointer, idx)