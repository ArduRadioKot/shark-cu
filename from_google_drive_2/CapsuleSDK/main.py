from CapsuleSDK.Capsule import Capsule
from CapsuleSDK.DeviceLocator import DeviceLocator
from CapsuleSDK.DeviceType import DeviceType
from CapsuleSDK.DeviceInfo import DeviceInfo
from CapsuleSDK.Error import Error
from CapsuleSDK.Error import Error_Code
from CapsuleSDK.Device import Device, Device_Connection_Status, Device_Mode
from CapsuleSDK.Resistances import Resistances
from CapsuleSDK.PSDData import PSDData, PSDData_Band
from CapsuleSDK.MEMS import MEMS, MEMSTimedData
from CapsuleSDK.EEGTimedData import EEGTimedData
from CapsuleSDK.PPGTimedData import PPGTimedData
from CapsuleSDK.Calibrator import *
from time import sleep
from CapsuleSDK.Emotions import Emotions, Emotions_States
from CapsuleSDK.Cardio import Cardio, Cardio_Data
from CapsuleSDK.PhysiologicalStates import PhysiologicalStates, PhysiologicalStates_Value, PhysiologicalStates_Baselines
from CapsuleSDK.Productivity import Productivity, Productivity_Baselines, Productivity_Metrics
import numpy as np
import os
import time

device_locator = None
buffer_size_limit = 10000
buffers = {}

class EventFiredState:
    """
    A class for tracking the status of the occurrence of a custom event.

    Used as a flag indicating whether a certain event has occurred,
    with the ability to reset and reactivate.

    Used for non_blocking_cond_wait to provide non-blocking behavior when waiting for asynchronous events
    like device connection, data retrieval, etc.

    Methods:
        - is_awake() -> bool: Checks if the event is active.
        - set_awake(): Sets the event to the active state.
        - sleep(): Resets the state of the event (makes it inactive).

    Example usage:
        event = EventFiredState()
        ...
        if device_connected:
            event.set_awake()
        while not event.is_awake():
            update_something()
    """
    def __init__(self):
        self._awake = False
    
    def is_awake(self):
        return self._awake

    def set_awake(self):
        self._awake = True
    
    def sleep(self):
        self._awake = False


def non_blocking_cond_wait(wake_event : EventFiredState, event_name: str, total_sleep_time: int):
    """
    Non-blocking waiting for an event to occur.

    This function implements a wait loop for an event represented by an `EventFiredState` object.
    During the wait, if `device_locator` is present, the device state is updated regularly
    (via a call to `device_locator.update()`).

    Suitable for scenarios where you need to wait for the result of an asynchronous action (e.g. device connection),
    without blocking the main thread completely.

    Arguments:
        - wake_event (EventFiredState): Flag object signaling the occurrence of an event.
        - event_name (str): The custom name of the event.
        - total_sleep_time (int): The total wait time in seconds.

    Behavior:
        - The cycle is broken into steps with an interval of 0.02 seconds.
        - Each iteration checks the `wake_event.is_awake()` state.
        - If the event occurs, a message is printed and the function terminates execution.
        - If the event has not occurred at the end of the loop, a timeout message is printed.

    Example usage:
        calibrator_done = EventFiredState()
        ...
        non_blocking_cond_wait(calibrator_done, "calibration", 30)
 """
    print("Waiting {name} for {time} seconds...".format(name = event_name, time = total_sleep_time))
    global device_locator
    total_sleep_time *= 50
    for _ in range(total_sleep_time):
        if device_locator is not None:
            device_locator.update()
        if wake_event.is_awake():
            print("Event {name} occurred!".format(name = event_name))
            return
        
        sleep(.02)
    
    print("Waiting for {event} timeout".format(event = event_name))

def flush_buffers():
    for name, buffer in buffers.items():
        if buffer:
            file_name = f"{name}.npy"
            if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
                existing_data = np.load(file_name, allow_pickle=True).tolist()
                existing_data.extend(buffer)
                np.save(file_name, existing_data)
            else:
                np.save(file_name, buffer)
            buffers[name] = []

device_list_event_fired = EventFiredState()
device = None
def on_device_list(locator: DeviceLocator, info: DeviceLocator.DeviceInfoList, fail_reason: DeviceLocator.FailReason) -> None:
    """
    Callback called after receiving the list of available devices.

    The function outputs information about all detected devices:
        - serial number
        - name
        - firmware version
        - device type.
    If devices are found, the first (index 0) is selected and the `Device` object associated with it is created.

    Used as a handler in `DeviceLocator.set_on_devices_list()`.

    Arguments:
        - locator: the `DeviceLocator` object that initiated the device request.
        - info (List[DeviceInfo]): A list of objects with information about the devices found.
        - fail_reason: The reason for the failure (if defined) if the list is empty.

    Behavior:
        - If no devices are found, the function terminates execution.
        - If devices are found, displays information about each and selects the first one.
        - Initializes the `device` global object and activates the `device_list_event_fired` event.

    Example usage:
        device_locator.set_on_devices_list(on_device_list)
    """
    print("Found {count} devices".format(count = len(info)))
    print('-' * 30)
    if len(info) == 0:
        return
    
    for i in range(len(info)):
        print("{i} device:".format(i = i))
        err = Error()
        device_info = info[i]
        print("Serial:     {s}".format(s = device_info.get_serial()))
        print("Name:       {n}".format(n = device_info.get_name()))
        print("Firmware:   {f}".format(f = device_info.get_firmware()))
        print("Type:       {t}".format(t = device_info.get_type()))
        print('-' * 30)

    print("For this example we'll stick with 0 device")

    global device
    device = Device(locator, info[0].get_serial(), locator.get_lib())
    device_list_event_fired.set_awake()


device_connection_state_fired = EventFiredState()
def on_connection_status_changed(device: Device, status: Device_Connection_Status):
    """
    A callback called when the connection status of a device changes.

    Outputs the updated connection status and activates the `device_connection_state_fired` flag,
    allowing the main thread to continue execution (e.g. after a successful connection or disconnection).

    Arguments:
        - device: The `Device` object to which the status change applies.
        - status: The updated connection status of the device. `Device_Connection_Status` object.

    Behavior:
        - Outputs the current connection status to the console.
        - Sets the `device_connection_state_fired` flag to the active state.

    Example usage:
        device.set_on_connection_status_changed(on_connection_status_changed)
    """
    print('Device connection status changed: {s}!'.format(s = status))
    device_connection_state_fired.set_awake()



buffers['resistances'] = []
device_resistances_fired = EventFiredState()
def on_resistances(device: Device, res: Resistances):
    """
    Callback called when electrode resistance data is received.

    Saves resistance measurements to a buffer, including timestamp, channel name and value.
    When enough data is accumulated (`buffer_size_limit`), saves it to the `resistances.npy` file.
    If the file already exists, the data is appended to the existing data.

    Resistances are specified in ohms.

    Arguments:
        - device: The `Device` object from which the data came.
        - res: The `Resistances` object containing the resistances for each channel and their names.

    Behavior:
        - Retrieves the data for each channel: name and resistance value.
        - Buffers the data with the current time (`time.time()`).
        - When the buffer limit is reached, saves the data to a NumPy format file (`.npy`), adding to existing data.

    Format of saved data:
        List[Tuple[timestamp: float, channel_name: str, resistance_value: float]]

    Example usage:
        device.set_on_resistances(on_resistances)
    """

    for r in range(len(res)):
        buffers['resistances'].append((time.time(), res.get_channel_name(r), res.get_value(r)))

    file_name = 'resistances.npy'
    if len(buffers['resistances']) >= buffer_size_limit:
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['resistances'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['resistances'])

        buffers['resistances'] = []


device_battery_charge_fired = EventFiredState()
def on_battery_charge(device: Device, charge: int):
    """
    A callback called when the battery level of a device is updated.

    Displays the current charge level to the console and triggers the `device_battery_charge_fired` event.
    The first few values ​​after the session starts may show an incorrect battery charge.
    Arguments:
        - device: The `Device` object from which the update was received.
        - charge (int): Current battery charge level (percent).

    Behavior:
        - Outputs the battery level to the console.
        - Sets the `device_battery_charge_fired` flag to active.

    Example usage:
        device.set_on_battery_charge_changed(on_battery_charge)
    """
    print('-' * 30)
    print("Device battery: {b}".format(b = charge))
    print('-' * 30)
    device_battery_charge_fired.set_awake()


device_mode_change_fired = EventFiredState()
def on_mode_changed(device: Device,  mode: Device_Mode):
    print("Device mode changed to {m}".format(m = mode.value))
    device_mode_change_fired.set_awake()


device_eeg_fired = EventFiredState()
buffers['raw_eeg'] = []
buffers['eeg'] = []
def on_eeg(device: Device, eeg: EEGTimedData):
    """
    Callback called when EEG data is acquired.

    Saves both raw and processed EEG values on all channels with time stamps.
    Data is buffered and saved to separate files when the limit is reached:
        - `raw_eeg.npy` for raw values
        - `eeg.npy` for processed values.

    Arguments:
        - device: `Device` object that sent the EEG data.
        - eeg: Object `EEGTimedData` containing the EEG time series, including raw and processed values.

    Behavior:
        - Extracts timestamps and EEG data and saves to buffers.
        - Saves the contents of the buffers to `.npy` files.
        - Activates the `device_eeg_fired` flag.

    Format of saved data:
        List[List[List[float]]: each line is `[timestamp, ch1, ch2, ..., chN]`.

    Usage example:
        device.set_on_eeg(on_eeg)
    """

    for idx in range(eeg.get_samples_count()):
        timestamp = eeg.get_timestamp(idx) * 100
        buffers['raw_eeg'].append([timestamp,] + [eeg.get_raw_value(i, idx) for i in range(eeg.get_channels_count())])
        buffers['eeg'].append([timestamp,] + [eeg.get_processed_value(i, idx) for i in range(eeg.get_channels_count())])

    file_name = 'raw_eeg.npy'
    if len(buffers['raw_eeg']) >= buffer_size_limit:
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['raw_eeg'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['raw_eeg'])

        buffers['raw_eeg'] = []

    file_name = 'eeg.npy'
    if len(buffers['eeg']) >= buffer_size_limit:
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['eeg'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['eeg'])

        buffers['eeg'] = []

    device_eeg_fired.set_awake()


buffers['psd'] = []
device_psd_fired = EventFiredState()
def on_psd(device: Device, psd: PSDData):
    """
    Callback called when power spectral density (PSD) data is retrieved.

    Extracts PSD data for all channels and frequencies, adds them to the `buffers['psd']` buffer,
    and, when the limit is reached, saves the accumulated data to the `psd.npy` file.

    The dimensionality of the returned powers is V^2.

    Arguments:
        - device: The `Device` object from which the PSD data came.
        - psd: The `PSDData` object containing the power spectral density values by channel and frequency.

    Behavior:
        - On first retrieval, outputs to the console a list of frequencies for which PSDs are output.
        - For each channel retrieves an array of PSD values for all frequencies.
        - Collects a two-dimensional array: `List[List[List[float]]`, where each inner list is a PSD over frequencies for one channel.
        - Adds the result to the global buffer `buffers['psd']`.
        - When the buffer overflows (`buffer_size_limit`), saves all data to the `psd.npy` file, adding to existing data.
        - Activates the `device_psd_fired` flag.

    Data format:
        List[channels] -> List[frequencies] -> float (PSD value)

    Usage example:
        device.set_on_psd(on_psd)
    """
    psd_row = []
    freqs_indicies = range(psd.get_frequencies_count())
    if not device_psd_fired.is_awake():
        psd_freqs = [psd.get_frequency(freqIdx) for freqIdx in freqs_indicies]
        print('PSD FREQS:', psd_freqs)
        device_psd_fired.set_awake()
    for idx in range(psd.get_channels_count()):
        psd_channel = []
        for freqIdx in freqs_indicies:
            val = psd.get_psd(idx, freqIdx)
            psd_channel.append(val)
        psd_row.append(psd_channel)
    buffers['psd'].append(psd_row)

    file_name = 'psd.npy'
    if len(buffers['psd']) >= buffer_size_limit:
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['psd'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['psd'])

        buffers['psd'] = []


calibrator_calibrated_fired = EventFiredState()
def on_calibrated(calibrator: Calibrator, data: IndividualNFBData):
    """
    Callback called when closed eye calibration is completed.

    Reports a successful calibration and activates the `calibrator_calibrated_fired` event.

    Arguments:
        - calibrator: The `Calibrator` object that initiated the calibration process.
        - data: the `IndividualNFBData` object The results of the calibration.

    Behavior:
        - Outputs a message indicating a successful calibration.
        - Activates the `calibrator_calibrated_fired` flag.

    Example usage:
        calibrator.set_on_calibration_finished(on_calibrated)
    """
    print('ALPHA WAS CALIBRATED')
    for metric_name in ['individualBandwidth', 'individualFrequency', 'individualNormalizedPower',
                        'individualPeakFrequency', 'individualPeakFrequencyPower', 'individualPeakFrequencySuppression',
                        'lowerFrequency', 'timestampMilli','upperFrequency']:
        print(metric_name, getattr(data, metric_name))
    print('-----------------------------------')



    calibrator_calibrated_fired.set_awake()


buffers['emotions'] = []
def on_emotions_states(emotion: Emotions, emotion_states: Emotions_States):
    """
    Callback called when receiving data from the emotional states classifier.

    The received values are added to the `buffers['emotions']` buffer and saved to the `emotions.npy` file.
    The file is used for accumulative storage of metrics.

    Arguments:
        - emotion (Emotions): The source object (emotion analysis module) from which the data came.
        - emotion_states (Emotions_States): The structure containing the values of the emotion metrics.

    Stored parameters:
        - `timestampMilli` (int): timestamp in milliseconds
        - `focus` (float): level of focus
        - `chill` (float): level of relaxation
        - `stress` (float): stress level
        - `anger` (float): anger level
        - `selfControl` (float): level of self-control

    Behavior:
        - Adds a tuple of metrics to the buffer.
        - Saves the accumulated data to an `emotions.npy` file.

    Example data format:
        List[Tuple[timestamp, focus, chill, stress, anger, selfControl],
        ...]

    Example usage:
        emotions.set_on_states_update(on_emotions_states)
    """
    buffers['emotions'].append((emotion_states.timestampMilli,
                       emotion_states.focus,
                       emotion_states.chill,
                       emotion_states.stress,
                       emotion_states.anger,
                       emotion_states.selfControl))

    file_name = 'emotions.npy'
    if len(buffers['emotions']) >= int(buffer_size_limit*0.1):
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['emotions'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['emotions'])

        buffers['emotions'] = []


buffers['cardio'] = []
def on_cardio_indexes(cardio: Cardio, indexes: Cardio_Data):
    """
    Callback called when getting the cardiometrics.

    Saves cardiometrics values to the `buffers['cardio']` buffer and then to the `cardio.npy` file.
    The data includes both physiological parameters and indicators of signal quality and artifacts.

    Arguments:
        - cardio: The `Cardio` object that initiated the data update.
        - Indexes: the `Cardio_Data` object that contains the metrics.

    Stored parameters:
        - `timestampMilli` (int): timestamp in milliseconds
        - `heartRate` (float): heart rate (beats/min)
        - `stressIndex` (float): stress level score
        - `kaplanIndex` (float): heart rate variability index
        - `hasArtifacts` (bool): presence of artifacts
        - `skinContact` (bool): presence of skin contact
        - `motionArtifacts` (bool): presence of motion artifacts
        - `metricsAvailable` (bool): flag of metrics availability

    Behavior:
        - Adds a tuple of values to the `buffers['cardio']` buffer.
        - Saves all accumulated data to a `cardio.npy` file.

    Format of saved data:
        List[Tuple[timestamp, heartRate, stressIndex, kaplanIndex, hasArtifacts, skinContact, motionArtifacts, metricsAvailable],
        ...]

    Example usage:
        cardio.set_on_indexes_update(on_cardio_indexes)
    """

    buffers['cardio'].append((
        indexes.timestampMilli,
        indexes.heartRate,
        indexes.stressIndex,
        indexes.kaplanIndex,
        indexes.hasArtifacts,
        indexes.skinContact,
        indexes.motionArtifacts,
        indexes.metricsAvailable
    ))

    file_name = 'cardio.npy'
    if len(buffers['cardio']) >= int(buffer_size_limit*0.1):
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['cardio'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['cardio'])
        buffers['cardio'] = []


buffers['ppg'] = []
def on_ppg(cardio: Cardio, ppg: PPGTimedData):
    """
    Callback called when photoplethysmogram data is acquired.

    Saves the RAW PPG signal with timestamps to the `buffers['ppg']` buffer and then to the `ppg.npy` file.

    Arguments:
        - cardio: The object of the `Cardio` module from which the data came.
        - ppg: The `PPGTimedData` object containing the PPG signal values and timestamps.

    Behavior:
        - Goes through each `ppg` sample, extracting the timestamp and signal value.
        - Adds `(timestamp, value)` pairs to the `buffers['ppg']` buffer.
        - Saves all data to an `ppg.npy` file.

    The format of the saved data is:
        List[Tuple[timestamp: float, value: float],
        ...].

    Example usage:
        cardio.set_on_ppg(on_ppg)
    """

    for idx in range(len(ppg)):
        buffers['ppg'].append((ppg.get_timestamp(idx), ppg.get_value(idx)))

    file_name = 'ppg.npy'
    if len(buffers['ppg']) >= int(buffer_size_limit * 0.1):
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['ppg'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['ppg'])

        buffers['ppg'] = []


buffers['phy_states'] = []
def on_phy_states(phy: PhysiologicalStates, states: PhysiologicalStates_Value):
    """
    Callback called when receiving data from the physiologicalStates classifier.

    Saves the values to the `buffers['phy_states']` buffer and then saves them to the `phy_states.npy` file.
    This data reflects the user's current psychophysiological state (fatigue, stress, concentration, etc.).


    Important:
    This classifier is updated relatively rarely (approximately every few minutes).
        It requires:
        - Successfully passed calibration with eyes closed (`IndividualNFBData`)
        - Collected baselines (`Productivity_Baselines` and `PhysiologicalStates_Baselines`)
     Without these conditions being met, the metrics will not be calculated.

    Arguments:
        - phy: The `PhysiologicalStates` classifier object that produced the values
        - states: The `PhysiologicalStates_Value` object containing the probabilities that the user is currently in the corresponding state (relaxation, fatigue, none, concentration, involvement, stress).
            The sum of all probabilities is 100%, e.g. if relaxation 60%, fatigue 10%, then the remaining 30% is distributed over the remaining states.


    Stored parameters:
        - `timestampMilli` (int): timestamp
        - `relaxation` (float): level of relaxation (probability)
        - `fatigue` (float): level of fatigue (probability)
        - `none` (float): uncertain state (probability)
        - `concentration` (float): level of concentration (probability)
        - `involvement` (float): level of involvement (probability)
        - `stress` (float): level of stress (probability)
        - `nfbArtifacts` (bool): presence of NFB artifacts
        - `cardioArtifacts` (bool): presence of artifacts in the NFB signal

    Behavior:
        - Adds a tuple of values to the `buffers['phy_states']` buffer.
        - Combines with previously saved data and saves to `phy_states.npy` file.

    Format of saved data:
        List[Tuple[timestamp, relaxation, fatigue, none, concentration, involvement, stress, nfbArtifacts, cardioArtifacts], ...].

    Example usage:
        phy.set_on_states(on_phy_states)
    """

    buffers['phy_states'].append((states.timestampMilli,
    states.relaxation,
    states.fatigue,
    states.none,
    states.concentration,
    states.involvement,
    states.stress,
    states.nfbArtifacts,
    states.cardioArtifacts))

    file_name = 'phy_states.npy'
    if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
        existing_data = np.load(file_name, allow_pickle=True).tolist()
        existing_data.extend(buffers['phy_states'])
        np.save(file_name, existing_data)
    else:
        np.save(file_name, buffers['phy_states'])

    buffers['phy_states'] = []


def on_phy_calibrated(phy: PhysiologicalStates, phy_states_baselines: PhysiologicalStates_Baselines):
    print('PHYSIOLOGICAL STATES WAS CALIBRATED')
    for metric_name in ['alpha', 'alphaGravity', 'beta', 'betaGravity', 'concentration', 'timestampMilli']:
        print(metric_name, getattr(phy_states_baselines, metric_name))
    print('-----------------------------------')


prod_calibrated_event = EventFiredState()
def on_prod_calibration_progress(prod: Productivity, progress: float):
    """
    A callback displaying the progress of calibration of the productivity classifier (`Productivity`).

    Called periodically during the calibration data collection process. When progress reaches 1.0
    (i.e., calibration is complete), it activates the `prod_calibrated_event` event, signaling
    that the system is ready for further productivity metrics.

    Arguments:
        - prod: `Productivity` classifier object.
        - progress: (float) current calibration progress from 0.0 to 1.0.

    Behavior:
        - Prints the current progress to the console.
        - When `progress >= 1.0` is reached, activates the `prod_calibrated_event` flag.

    Example usage:
        prod.set_on_calibration_progress(on_prod_calibration_progress)
    """
    if progress >= 1.0:
        prod_calibrated_event.set_awake()
    print(f'Calibrating productivity {progress}')


buffers['prod_metrics_states'] = []
def on_prod_metrics(prod: Productivity, metrics: Productivity_Metrics):
    """
    Callback called when getting metrics from the `Productivity` classifier.

    Saves the values to the `buffers['prod_metrics_states']` buffer and then to the `prod_metrics_states.npy` file.
    These metrics allow you to evaluate the user's current productivity, fatigue level, relaxation, concentration, and so on.

    Arguments:
        - prod (Productivity): The productivity module object that initiated the data update.
        - metrics (Productivity_Metrics): The structure with the current values of the metrics.

    Stored metrics:
        - `timestampMilli` (int): timestamp
        - `fatigueScore` (float): fatigue level
        - `reverseFatigueScore` (float): inverse fatigue level. Anti-fatigue.
        - `gravityScore` (float): cognitive load
        - `relaxationScore` (float): degree of relaxation
        - `concentrationScore` (float): concentration
        - `productivityScore` (float): productivity score (not normalized).
        - `currentValue` (float): normalized productivitySocre score and in the range from 0 to 1.
        - `alpha` (float): normalized alpha power in the range from 0 to 1.
        - `productivityBaseline` (float): baseline productivityScore
        - `accumulatedFatigue` (float): accumulated fatigue
        - `fatigueGrowthRate` (float): growth rate of accumulated fatigue

    Behavior:
        - Adds a tuple of all the above parameters to `buffers['prod_metrics_states']`.
        - Saves the data to the `prod_metrics_states.npy` file.

    Format of saved data:
        List[Tuple[timestamp, fatigueScore, reverseFatigueScore, ..., fatigueGrowthRate]]

    Usage example:
        prod.set_on_metrics_update(on_prod_metrics)
    """
    buffers['prod_metrics_states'].append((metrics.timestampMilli,
        metrics.fatigueScore,
        metrics.reverseFatigueScore,
        metrics.gravityScore,
        metrics.relaxationScore,
        metrics.concentrationScore,
        metrics.productivityScore,
        metrics.currentValue,
        metrics.alpha,
        metrics.productivityBaseline,
        metrics.accumulatedFatigue,
        metrics.fatigueGrowthRate.value))

    file_name = 'prod_metrics_states.npy'
    if len(buffers['prod_metrics_states']) >= int(buffer_size_limit*0.1):
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['prod_metrics_states'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['prod_metrics_states'])
        buffers['prod_metrics_states'] = []


buffers['acc'] = []
buffers['gyroscope'] = []
def on_mems(mems: MEMS, mems_data: MEMSTimedData):
    """
    Callback called when receiving data from accelerometer and gyroscope.

    Receives signals, buffers them, and saves them to separate `.npy` files:
        - `acc.npy` for accelerometer data
        - `gyroscope.npy` for gyroscope data.

    Important:
        Not all devices represented in DeviceType have MEMS data available!

    Arguments:
        - mems: The `MEMS` object from which the data was received.
        - mems_data: The `MEMSTimedData` object containing the gyroscope and accelerometer sample sequences.

    Stored parameters:
        For each sample:
        - `timestamp` (float): timestamp
        - `accelerometer.x` (float): X-axis acceleration
        - `accelerometer.y` (float): acceleration in the Y axis
        - `accelerometer.z` (float): acceleration in Z axis
        - `gyroscope.x` (float): angular velocity in X axis
        - `gyroscope.y` (float): angular velocity in the Y axis
        - `gyroscope.z` (float): angular velocity in Z axis

    Behavior:
        - Traverses each `mems_data` sample:
        - Extracts accelerometer and gyroscope data and adds to the appropriate buffers (`buffers['acc']`, `buffers['gyroscope']`).
        - Saves the data to `.npy` files.

    Example of use:
        mems.set_on_update(on_mems)
    """
    
    for idx in range(len(mems_data)):
        acc = mems_data.get_accelerometer(idx)
        buffers['acc'].append((mems_data.get_timestamp(idx), acc.x, acc.y, acc.z))

    file_name = 'acc.npy'
    if len(buffers['acc']) >= buffer_size_limit:
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['acc'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['acc'])

        buffers['acc'] = []

    for idx in range(len(mems_data)):
        gyro = mems_data.get_gyroscope(idx)
        buffers['gyroscope'].append((mems_data.get_timestamp(idx), gyro.x, gyro.y, gyro.z))

    file_name = 'gyroscope.npy'
    if len(buffers['gyroscope']) >= buffer_size_limit:
        if os.path.exists(file_name) and os.stat(file_name).st_size != 0:
            existing_data = np.load(file_name, allow_pickle=True).tolist()
            existing_data.extend(buffers['gyroscope'])
            np.save(file_name, existing_data)
        else:
            np.save(file_name, buffers['gyroscope'])

        buffers['gyroscope'] = []


def on_productivity_baseline_update(prod: Productivity, baselines: Productivity_Baselines):
    """
    A callback called when the Productivity classifier's metrics baselines are finished collecting.

    Outputs to the console the values of baseline metrics, which will be used in the future for evaluating current user states.

    Arguments:
        prod: The `Productivity` object of the Productivity module that initiated the update.
        baselines: The `Productivity_Baselines` structure containing the calculated baselines values.

    Stored parameters:
        - `concentration` (float): baseline concentration level
        - `fatigue` (float)
        - `gravity` (float)
        - `productivity` (float)
        - `relaxation` (float)
        - `reverseFatigue` (float)
        - `timestampMilli` (int)

    Behavior:
        - Gets the structure of the baselines.
        - Outputs each of the metrics by name and value in a readable form.

    Example usage:
        prod.set_on_baselines_update(on_productivity_baseline_update)
    """
    print('----PRODUCTIVITY BASELINES----')
    for metric_name in ['concentration', 'fatigue', 'gravity', 'productivity', 'relaxation', 'reverseFatigue', 'timestampMilli']:
        print(metric_name, getattr(baselines, metric_name))
    print('------------------------------')



def main():
    capsuleLib = Capsule('./libCapsuleClient.dylib')
    #capsuleLib = Capsule('.\\CapsuleClient.dll')    # Connect the library. (For macOS use .\\libCapsuleClient.dylib)
    global device_locator
    device_locator = DeviceLocator(capsuleLib.get_lib())    # Create an object to search for devices
    device_locator.set_on_devices_list(on_device_list)      # Subscribe to receive the device list

    while not device_list_event_fired.is_awake():   # Try to find and connect to a device of the selected type until it succeeds
        device_locator.request_devices(DeviceType.Band, 10)
        non_blocking_cond_wait(device_list_event_fired, 'device list to fire', 10)

    global device
    device.set_on_battery_charge_changed(on_battery_charge)     # Subscribe to receive a change in battery percentage
    device.set_on_connection_status_changed(on_connection_status_changed)   # Sign up to be notified when the connection status changes
    device.set_on_eeg(on_eeg)   # Subscribe to receive raw and filtered EEG data
    device.set_on_resistances(on_resistances)     # Subscribe to get resistances for each of the electrodes
    device.set_on_psd(on_psd)       # Subscribe to receive Power Spectral Density for each of the EEG channels
    device.set_on_mode_changed(on_mode_changed)     # Subscribe to receive notification of device mode changes
    device.connect(bipolarChannels=False)    # Connecting to the device in bipolar (True) or monopolar (False) mode
    non_blocking_cond_wait(device_connection_state_fired, 'device connected', 40)   # Wait for the device to connect

    channel_names_obj = device.get_channel_names()      # Get an object with the names of the electrodes
    print('EEG channel names:', [channel_names_obj.get_name_by_index(i) for i in range(len(channel_names_obj))])    # Output the electrode names to the console

    calibrator = Calibrator(device, capsuleLib.get_lib())  # Create a Calibrator object with the help of which we will perform calibration with closed eyes
    calibrator.set_on_calibration_finished(on_calibrated)   # Subscribe to complete the calibration with eyes closed
    
    emotions = Emotions(device, capsuleLib.get_lib())   # Create an Emotions classifier
    emotions.set_on_states_update(on_emotions_states)   # Subscribe to receive data from the Emotions classifier

    cardio = Cardio(device, capsuleLib.get_lib())       # Create a Cardio classifier
    cardio.set_on_indexes_update(on_cardio_indexes)     # Subscribe to receive cardiometrics
    cardio.set_on_ppg(on_ppg)   # Subscribe to receive raw PPG signal

    phy = PhysiologicalStates(device, capsuleLib.get_lib())     # Create a Physiological States classifier
    phy.set_on_states(on_phy_states)    # Subscribe to receive data from the Physiological States classifier
    phy.set_on_calibrated(on_phy_calibrated)    # Subscribe to finish the calibration required for the Physiological States classifier

    prod = Productivity(device, capsuleLib.get_lib())   # Create a Producitivty classifier
    prod.set_on_calibration_progress(on_prod_calibration_progress)  # Subscribe to the progress of the baseline calibration
    prod.set_on_metrics_update(on_prod_metrics)     # Subscribe to Productivity metrics updates
    prod.set_on_baseline_update(on_productivity_baseline_update)    # Subscribe to complete the baseline calibration.
    
    try:
        mems = MEMS(device, capsuleLib.get_lib())
        mems.set_on_update(on_mems)
    except CapsuleException as e:
        print('MEMS creation error: {err}'.format(err = e.message))

    device.start()      # Start receiving data from the device
    print("Device start initialized")
    print('Mode: {mode}'.format(mode = device.get_mode().value))

    info = device.get_info()
    print('Got info from the device:')
    print('name: {n}'.format(n = info.get_name()))
    print('firmware: {f}'.format(f = info.get_firmware()))
    print('serial: {s}'.format(s = info.get_serial()))
    print('type: {t}'.format(t = info.get_type()))
    print('EEG sample rate: {sr}'.format(sr = device.get_eeg_sample_rate()))

    calibrator.calibrate_quick()    # Start quick closed-eyes calibration
    # Individual_nfb_data = IndividualNFBData(timestamp_milli=1,
    #                                         individual_frequency=10,
    #                                         individual_peak_frequency=10,
    #                                         individual_peak_frequency_power=10,
    #                                         individual_peak_frequency_suppression=2,
    #                                         individual_bandwidth=6,
    #                                         individual_normalized_power=6,
    #                                         lower_frequency=7,
    #                                         upper_frequency=13
    #                                         )  # Import the IndividualNFBData instead of going through the calibration again
    # calibrator.import_alpha(individual_nfb_data=Individual_nfb_data)
    non_blocking_cond_wait(calibrator_calibrated_fired, "calibration", 40)  # Set a non-blocking wait to wait for the closed-eyes calibration to complete

    prod.calibrate_baselines()  # Start calibration Productivity baselines
    # productivity_baselines = Productivity_Baselines(concentration=0.4303644895553589,
    #                                                 fatigue=3.231703281402588,
    #                                                 gravity=0.6188167333602905,
    #                                                 productivity=0.6188167333602905,
    #                                                 relax=2.3246757984161377,
    #                                                 reverse_fatigue=0.3094368875026703,
    #                                                 timestamp=0)
    # prod.import_baselines(productivity_baselines)     # Import the baselines instead of going through the calibration again

    phy.calibrate_baselines()   # Start calibration Physiological States baselines
    # phy_baselines = PhysiologicalStates_Baselines(timestamp_milli=0,
    #                                               alpha=0.2845260500907898,
    #                                               beta=0.5158727169036865,
    #                                               alpha_gravity=4.821654319763184,
    #                                               beta_gravity=0.13223537802696228,
    #                                               concentration=1.837107539176941)
    # phy.import_baselines(baselines=phy_baselines)

    print('Is calibrated: {c}'.format(c = calibrator.is_calibrated()))
    if not calibrator.is_calibrated():      # Handler for the case where closed-eye calibration failed
        print('Calibration failed. Exiting...')
        device.stop()
        device.disconnect()
        return
    
    non_blocking_cond_wait(prod_calibrated_event, "productivity baselines", 30)    # Set a non-blocking wait to wait for the baseline calibration to complete
    non_blocking_cond_wait(EventFiredState(), event_name='data collection', total_sleep_time=60)

    device.stop()  # Stop receiving data from the device
    device_connection_state_fired.sleep()
    device.disconnect()     # Send a command to disconnect from the device
    non_blocking_cond_wait(device_connection_state_fired, 'device disconnected', 10)    # Wait disconnection with device.
    # Save remaining samples
    flush_buffers()

if __name__ == "__main__":
    main()
