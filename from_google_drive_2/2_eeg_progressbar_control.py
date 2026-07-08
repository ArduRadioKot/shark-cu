"""
EEG (2ch split) + PSD (2ch) + Alpha power + Threshold slider + Progress bar - NEON STYLE
- bipolarChannels=True
- subplot 0: EEG Ch0 | Ch1 (split horizontally)
- subplot 1: PSD Ch0, Ch1 (same axis)
- subplot 2: Alpha power (enlarged)
- subplot 3: Progress bar
- threshold slider standalone between alpha and progress
"""


import atexit
from pathlib import Path
import signal
import sys
import threading

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
for import_path in (SCRIPT_DIR, PROJECT_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from CapsuleSDK.Capsule import Capsule
from CapsuleSDK.DeviceLocator import DeviceLocator
from CapsuleSDK.DeviceType import DeviceType
from CapsuleSDK.Device import Device, Device_Connection_Status
from CapsuleSDK.EEGTimedData import EEGTimedData
from CapsuleSDK.Resistances import Resistances
from CapsuleSDK.PSDData import PSDData, PSDData_Band
from CapsuleSDK.MEMS import MEMS, MEMSTimedData
from CapsuleSDK.PPGTimedData import PPGTimedData
from CapsuleSDK.Emotions import Emotions, Emotions_States
from CapsuleSDK.Cardio import Cardio, Cardio_Data


import numpy as np
import time
from collections import deque


import os
os.environ.setdefault("MPLCONFIGDIR", str(SCRIPT_DIR / ".matplotlib-cache"))
os.environ.setdefault("TK_SILENCE_DEPRECATION", "1")
import matplotlib
PLATFORM = 'mac'
if PLATFORM == 'win':
    matplotlib.use("TkAgg")
else:
    matplotlib.use("MacOSX")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.widgets import Slider
from matplotlib.patheffects import withStroke


from scipy.signal import butter, sosfilt, sosfilt_zi


# NEON STYLE
plt.style.use('dark_background')

TARGET_SERIAL = '822580' # Серийник нейроинтерфейса для подключения, например "821619"
PROGRESS_DEBUG = True

# GLOBAL LIMITS (for EEG, PSD, Alpha)
EEG_MIN = -1e-1   # пример для ЭЭГ (µV)
EEG_MAX = 1e-1
PSD_MIN = 1e-15    # µV²/Hz
PSD_MAX = 1e-9
ALPHA_MIN = 1e-12  # α‑power
ALPHA_MAX = 1e-9
THRESHOLD_ALPHA_MAX = 5e-9


# Config
EEG_WINDOW_SECONDS = 10
MAX_EEG_CHANNELS_TO_PLOT = 2
PSD_CHANNEL_INDEX = 0  # для alpha power
THRESHOLD_ALPHA_INIT = 1.5e-11
ACCUM_STEP_SEC = 0.1
ACCUM_STEP = 1
ACCUM_MIN, ACCUM_MAX = 0, 100
USE_BANDPASS = True
BP_LO, BP_HI = 7.0, 30.0
BP_ORDER = 4


_progress_direction = None



# CUSTOM NEON COLORS
COLORS = {
    'orange': '#E63F07',
    'green':  '#009B40',      # 0 вместо O
    'cyan': '#2CB9FF',
    'blue':   '#3044FF',       # 0 вместо O
    'purple': '#FE68B9',
    'yellow': '#FFDD2D'
}


# NEON GLOW EFFECTS
def neon_glow(color):
    return [
        withStroke(linewidth=8, foreground=color, alpha=0.4),
        withStroke(linewidth=5, foreground=COLORS['purple'], alpha=0.7),
        withStroke(linewidth=3, foreground=COLORS['yellow'], alpha=0.9),
        withStroke(linewidth=2, foreground='white')
    ]


LINE_WIDTH = 2.5


# State
device_locator = None
device = None
animation = None
_cleanup_done = False


class EventFiredState:
    def __init__(self): self._awake = False
    def is_awake(self): return self._awake
    def set_awake(self): self._awake = True
    def sleep(self): self._awake = False


def cleanup():
    global _cleanup_done
    if _cleanup_done:
        return
    _cleanup_done = True

    try:
        if device is not None:
            device.stop()   
    except Exception as exc:
        print("[cleanup] device stop failed:", exc)


def handle_stop_signal(_signum, _frame):
    cleanup()
    raise SystemExit(0)


atexit.register(cleanup)
signal.signal(signal.SIGINT, handle_stop_signal)
signal.signal(signal.SIGTERM, handle_stop_signal)


def non_blocking_cond_wait(wake_event: EventFiredState, name: str, total_sleep_time: int):
    print(f"Waiting {name} for {total_sleep_time} seconds...")
    steps = int(total_sleep_time * 50)
    for _ in range(steps):
        if device_locator is not None:
            device_locator.update()
        if wake_event.is_awake():
            print(f"Event {name} occurred!")
            return True
        time.sleep(0.02)
    print(f"Waiting for {name} timeout")
    return False


device_list_event_fired = EventFiredState()
device_list_event = EventFiredState()
device_connection_state_fired = EventFiredState()
device_eeg_fired = EventFiredState()


sr_lock = threading.Lock()


# Buffers
sample_rate = None
sample_counter = 0
times = []
values = []
channel_names = []
bp_sos = None
bp_zi_per_chan = None


def init_eeg_buffers(n_channels: int, sr: float):
    global times, values, sample_rate
    with sr_lock:
        sample_rate = sr
    maxlen = int(sr * EEG_WINDOW_SECONDS)
    use = min(n_channels, MAX_EEG_CHANNELS_TO_PLOT)
    times[:]  = [deque(maxlen=maxlen) for _ in range(use)]
    values[:] = [deque(maxlen=maxlen) for _ in range(use)]


# PSD + Alpha
psd_freqs = None
psd_vals_all = {}  # для всех каналов
alpha_lower = None
alpha_upper = None


band_time = deque(maxlen=10_000)
alpha_power = deque(maxlen=10_000)
band_start_time = None


accum_value = 0
last_accum_ts = None
last_alpha_val = 0.0


def integrate_band(freqs, psd, f_low, f_high):
    if freqs is None or psd is None:
        return 0.0
    mask = (freqs >= f_low) & (freqs <= f_high)
    if not np.any(mask):
        return 0.0
    return float(np.trapezoid(psd[mask], freqs[mask]))


# Callbacks
# def on_device_list(locator: DeviceLocator, info: DeviceLocator.DeviceInfoList, fail_reason):
#     global device
#     if len(info) == 0:
#         return
#     print(f"Found {len(info)} devices")
#     device = Device(locator, info[0].get_serial(), locator.get_lib())
#     device_list_event_fired.set_awake()

def on_device_list(locator: DeviceLocator, info: DeviceLocator.DeviceInfoList, fail_reason):
    global device
    if device is not None:
        return

    if len(info) == 0:
        print("No devices found.")
        return
    print(f"Found {len(info)} devices")
    
    chosen = None
    for dev in info:
        serial = dev.get_serial()
        print("Found device serial:", serial)
        if serial == TARGET_SERIAL:
            chosen = dev
            break

    if chosen is None:
        print(f"Target serial {TARGET_SERIAL!r} not found. Refusing to connect to another device.")
        return
    
    print("Connecting to:")
    print("Serial:", chosen.get_serial())
    print("Name:  ", chosen.get_name())
    print("FW:    ", chosen.get_firmware())
    
    try:
        device = Device(locator, chosen.get_serial(), locator.get_lib())
    except Exception as exc:
        print("Failed to create target device:", exc)
        return

    device_list_event_fired.set_awake() 


def on_connection_status_changed(d: Device, status: Device_Connection_Status):
    print('Device connection status changed:', status)
    device_connection_state_fired.set_awake()


def on_eeg(d: Device, eeg: EEGTimedData):
    global sample_counter, sample_rate, channel_names, times, values, bp_sos, bp_zi_per_chan
    chn = eeg.get_channels_count()

    if sample_rate is None:
        try:
            sr = float(d.get_eeg_sample_rate())
        except Exception:
            sr = 250.0
        init_eeg_buffers(chn, sr)

        if USE_BANDPASS:
            nyq = 0.5 * sr
            lo = BP_LO / nyq
            hi = BP_HI / nyq
            sos = butter(BP_ORDER, [lo, hi], btype='bandpass', output='sos')
            zi = [sosfilt_zi(sos) for _ in range(min(chn, MAX_EEG_CHANNELS_TO_PLOT))]
            bp_sos = sos
            bp_zi_per_chan = zi

        try:
            ch_obj = d.get_channel_names()
            channel_names = [ch_obj.get_name_by_index(i) for i in range(len(ch_obj))][:MAX_EEG_CHANNELS_TO_PLOT]
        except Exception:
            channel_names = [f"Ch{i}" for i in range(min(chn, MAX_EEG_CHANNELS_TO_PLOT))]
        print("EEG sample rate:", sr)
        print("Plotting EEG channels:", channel_names)

    limit = min(chn, MAX_EEG_CHANNELS_TO_PLOT)
    for idx in range(eeg.get_samples_count()):
        for c in range(limit):
            v = eeg.get_processed_value(c, idx)
            if USE_BANDPASS and bp_sos is not None and bp_zi_per_chan is not None:
                y, bp_zi_per_chan[c] = sosfilt(bp_sos, [v], zi=bp_zi_per_chan[c])
                v = float(y[0])
            values[c].append(v)
            times[c].append(sample_counter)
        sample_counter += 1

    if not device_eeg_fired.is_awake():
        device_eeg_fired.set_awake()


def on_psd(d: Device, psd: PSDData):
    global psd_freqs, psd_vals_all, alpha_lower, alpha_upper, band_time, alpha_power, band_start_time, last_alpha_val

    if psd_freqs is None:
        freqs = [psd.get_frequency(i) for i in range(psd.get_frequencies_count())]
        psd_freqs = np.asarray(freqs, dtype=float)

    if alpha_lower is None or alpha_upper is None:
        try:
            if psd.has_individual_alpha():
                alpha_lower = float(psd.get_alpha_lower())
                alpha_upper = float(psd.get_alpha_upper())
            else:
                alpha_lower, alpha_upper = 9.0, 11.0
        except Exception:
            alpha_lower, alpha_upper = 9.0, 11.0
        if alpha_lower > alpha_upper:
            alpha_lower, alpha_upper = alpha_upper, alpha_lower

    ch_count = psd.get_channels_count()
    for ch in range(min(2, ch_count)):  # 2 канала PSD
        vals = [psd.get_psd(ch, i) for i in range(psd.get_frequencies_count())]
        psd_vals_all[ch] = np.asarray(vals, dtype=float)

    # Alpha по PSD_CHANNEL_INDEX
    if PSD_CHANNEL_INDEX in psd_vals_all:
        a_pow = integrate_band(psd_freqs, psd_vals_all[PSD_CHANNEL_INDEX], alpha_lower, alpha_upper)
        last_alpha_val = a_pow

    if band_start_time is None:
        band_start_time = time.time()
    t_rel = time.time() - band_start_time
    band_time.append(t_rel)
    alpha_power.append(last_alpha_val if last_alpha_val is not None else 0.0)


def on_resistances(d: Device, res: Resistances): pass
def on_ppg(cardio: Cardio, ppg: PPGTimedData): pass
def on_cardio_indexes(cardio: Cardio, idx: Cardio_Data): pass
def on_mems(mems: MEMS, md: MEMSTimedData): pass
def on_emotions_states(em: Emotions, st: Emotions_States): pass


# -------------------------
# LAYOUT: 4 rows + 1 slider
# 0: EEG Ch0 | Ch1 (split horizontally)
# 1: PSD Ch0 + Ch1 (same axis)
# 2: Alpha power (enlarged)
# 3: Progress bar
# slider: между alpha и progress
# -------------------------
fig, axes = plt.subplots(
    4, 1,
    figsize=(16, 16),
    height_ratios=[2, 2, 3, 1],
    sharex=False,
    facecolor='black'
)
fig.set_tight_layout(False)
fig.canvas.manager.set_window_title("CU_ProgressBar")  # название окна


# общая стилизация
def setup_ax(ax, ylabel=None, title=None):
    ax.set_facecolor('black')
    ax.grid(True, linestyle='--', alpha=0.3, color=COLORS['blue'])
    ax.tick_params(colors='white')
    ax.xaxis.label.set_color('white')
    ax.yaxis.label.set_color('white')
    ax.title.set_color('white')
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=12, color='white')
    if title:
        ax.set_title(title, fontsize=12, color=COLORS['yellow'])


# ROW 0: EEG split (Ch0 left | Ch1 right in one axis)
eeg_ax = axes[0]
eeg_line_left,  = eeg_ax.plot([], [], linewidth=LINE_WIDTH, color=COLORS['orange'])
eeg_line_right, = eeg_ax.plot([], [], linewidth=LINE_WIDTH, color=COLORS['cyan'])
eeg_line_left.set_path_effects(neon_glow(COLORS['orange']))
eeg_line_right.set_path_effects(neon_glow(COLORS['cyan']))

setup_ax(eeg_ax, ylabel="EEG (µV)", title="EEG Ch0 | Ch1")
eeg_ax.set_xlim(-EEG_WINDOW_SECONDS, 0)
eeg_ax.set_ylim(EEG_MIN, EEG_MAX)


# ROW 1: PSD (2 channels on one axis)
psd_ax = axes[1]
ln_psd0, = psd_ax.plot([], [], linewidth=LINE_WIDTH, color=COLORS['orange'])
ln_psd1, = psd_ax.plot([], [], linewidth=LINE_WIDTH, color=COLORS['blue'])

setup_ax(psd_ax, ylabel="PSD [µV²/Hz]", title="PSD Ch0 + Ch1")
psd_ax.set_xlim(0, 40)
psd_ax.set_ylim(PSD_MIN, PSD_MAX)
psd_ax.set_yscale("log")
psd_ax.grid(True, linestyle='--', alpha=0.3, color=COLORS['blue'])

# glow эффект после задания лимитов
for ln in [ln_psd0, ln_psd1]:
    ln.set_path_effects(neon_glow(ln.get_color()))


# ROW 2: Alpha power (ENLARGED)
alpha_ax = axes[2]
alpha_line, = alpha_ax.plot([], [], linewidth=LINE_WIDTH*1.5, color=COLORS['yellow'])
alpha_line.set_path_effects(neon_glow(COLORS['yellow']))

setup_ax(alpha_ax, ylabel="Alpha Power", title="Alpha Power (Channel 0)")
alpha_ax.set_ylim(ALPHA_MIN, ALPHA_MAX)
alpha_ax.set_yscale("log")
alpha_ax.grid(True, linestyle='--', alpha=0.3, color=COLORS['blue'])


# ROW 3: Progress bar
bar_ax = axes[3]
bar_ax.set_xlim(ACCUM_MIN, ACCUM_MAX)
bar_ax.set_ylim(0, 1)
bar_rects = bar_ax.barh([0.5], [0], height=0.8, color=COLORS['orange'])  # Orange вместо красного
bar_ax.set_yticks([])
bar_ax.set_xlabel("Progress (0-100)", fontsize=12, color='white')
bar_ax.set_title("Alpha > threshold → +1 / 0.1s ; else −1", fontsize=12, color=COLORS['yellow'])
bar_ax.set_facecolor('black')
bar_ax.grid(True, linestyle='--', alpha=0.3, color=COLORS['blue'])
bar_ax.tick_params(colors='white')


# THRESHOLD SLIDER (standalone между alpha и progress)
ax_threshold = plt.axes([0.15, 0.04, 0.7, 0.04], facecolor='black')
threshold_slider = Slider(
    ax_threshold,
    'Alpha Threshold',
    0.0,
    THRESHOLD_ALPHA_MAX,
    valinit=THRESHOLD_ALPHA_INIT,
    valfmt='%.2e',
    color=COLORS['purple']
)

thr_line = None


def update_progress_bar(current_threshold):
    global accum_value, last_accum_ts, last_alpha_val, _progress_direction
    now = time.time()
    if last_accum_ts is None:
        last_accum_ts = now
        return

    if now - last_accum_ts >= ACCUM_STEP_SEC:
        step = ACCUM_STEP if (last_alpha_val > current_threshold) else -ACCUM_STEP
        accum_value = max(ACCUM_MIN, min(ACCUM_MAX, accum_value + step))
        _progress_direction = "up" if step > 0 else "down"
        if PROGRESS_DEBUG:
            print(
                "[progress]",
                "alpha=", f"{last_alpha_val:.3e}",
                "threshold=", f"{current_threshold:.3e}",
                "direction=", _progress_direction,
                "value=", accum_value,
            )
        last_accum_ts = now

    bar_rects[0].set_width(accum_value)
    # Оранжевый цвет при alpha < threshold, зелёный при alpha >= threshold
    bar_rects[0].set_color(COLORS['green'] if last_alpha_val > current_threshold else COLORS['orange'])
    bar_rects[0].set_alpha(0.9)


def update_plot(_frame):
    current_threshold = threshold_slider.val

    # EEG split (Ch0 left, Ch1 right в одном axis) - ДИНАМИЧЕСКИЙ МАСШТАБ!
    if sample_rate is not None and len(values) > 0:
        with sr_lock:
            sr = sample_rate
        use = min(len(values), 2)
        
        all_data = []
        
        # Собираем данные обоих каналов
        if len(times) > 0 and len(values[0]) > 0:
            t0 = times[0][-1]
            ts0 = [(k - t0) / sr for k in times[0]]
            eeg_line_left.set_data(ts0, list(values[0]))
            all_data.extend(values[0])
            
        if use > 1 and len(values) > 1 and len(values[1]) > 0:
            t1 = times[1][-1]
            ts1 = [(k - t1) / sr for k in times[1]]
            eeg_line_right.set_data(ts1, list(values[1]))
            all_data.extend(values[1])
        
        # ДИНАМИЧЕСКИЙ МАСШТАБ ПО ОБОИМ КАНАЛАМ
        if all_data:
            data_min, data_max = min(all_data), max(all_data)
            if data_min == data_max:
                data_min -= 1e-6
                data_max += 1e-6
            pad = 0.1 * (data_max - data_min)
            eeg_ax.set_ylim(data_min - pad, data_max + pad)
            
        eeg_ax.set_xlim(-EEG_WINDOW_SECONDS, 0)

    # PSD (остальное без изменений)
    PSD_XMAX = 40
    if psd_freqs is not None:
        mask = psd_freqs <= PSD_XMAX
        if 0 in psd_vals_all:
            psd0 = psd_vals_all[0][mask]
            ln_psd0.set_data(psd_freqs[mask], psd0)
        else:
            ln_psd0.set_data([], [])
        if 1 in psd_vals_all:
            psd1 = psd_vals_all[1][mask]
            ln_psd1.set_data(psd_freqs[mask], psd1)
        else:
            ln_psd1.set_data([], [])
        psd_ax.set_xlim(0, PSD_XMAX)

    # Alpha power (остальное без изменений)
    if len(band_time) > 1:
        t_arr = np.asarray(band_time)
        a_arr = np.asarray(alpha_power)
        alpha_line.set_data(t_arr, a_arr)
        alpha_ax.set_xlim(t_arr[0], t_arr[-1])
        
        global thr_line
        if thr_line is None:
            thr_line, = alpha_ax.plot([], [], color=COLORS['purple'], linewidth=4, linestyle='--')
            thr_line.set_path_effects(neon_glow(COLORS['purple']))
        x_lim = alpha_ax.get_xlim()
        thr_line.set_data([x_lim[0], x_lim[1]], [current_threshold, current_threshold])
        alpha_ax.set_ylim(ALPHA_MIN, max(ALPHA_MAX, 4 * current_threshold))

    # Progress bar
    update_progress_bar(current_threshold)

    fig.canvas.draw_idle()

    artists = [eeg_line_left, eeg_line_right, ln_psd0, ln_psd1, alpha_line, bar_rects[0]]
    if thr_line is not None:
        artists.append(thr_line)
    return artists


# MAIN
def main():
    global animation

    if PLATFORM == 'win':
        capsuleLib = Capsule(str(SCRIPT_DIR / 'CapsuleSDK' / 'CapsuleClient.dll'))
    else:
        capsuleLib = Capsule(str(SCRIPT_DIR / 'CapsuleSDK' / 'libCapsuleClient.dylib'))

    global device_locator, device
    device_locator = DeviceLocator(capsuleLib.get_lib())
    device_locator.set_on_devices_list(on_device_list)

    device_locator.request_devices(DeviceType.Band, 20)
    if not non_blocking_cond_wait(device_list_event_fired, 'device list', 25):
        print("No device discovered.")
        return
    if device is None:
        print("Target device was not selected.")
        return

    device.set_on_connection_status_changed(on_connection_status_changed)
    device.set_on_eeg(on_eeg)
    device.set_on_psd(on_psd)

    try:
        emotions = Emotions(device, capsuleLib.get_lib())
        emotions.set_on_states_update(on_emotions_states)
    except: pass
    try:
        cardio = Cardio(device, capsuleLib.get_lib())
        cardio.set_on_indexes_update(on_cardio_indexes)
        cardio.set_on_ppg(on_ppg)
    except: pass
    try:
        mems = MEMS(device, capsuleLib.get_lib())
        mems.set_on_update(on_mems)
    except: pass

    device.connect(bipolarChannels=True)
    non_blocking_cond_wait(device_connection_state_fired, 'device connected', 40)

    device.start()
    print("CU_ProgressBar Dashboard запущен!")

    animation = FuncAnimation(
        fig,
        update_plot,
        interval=int(ACCUM_STEP_SEC * 1000),
        blit=False,
        cache_frame_data=False,
    )

    running = True
    def updater():
        while running:
            if device_locator:
                device_locator.update()
            time.sleep(0.01)

    t = threading.Thread(target=updater, daemon=True)
    t.start()

    try:
        plt.subplots_adjust(bottom=0.12, top=0.95, hspace=0.45)  # побольше отступы между графами
        fig.canvas.mpl_connect('close_event', lambda _event: cleanup())
        plt.show()
    except KeyboardInterrupt:
        pass
    finally:
        running = False
        cleanup()
        print("CU_ProgressBar остановлен.")


if __name__ == '__main__':
    main()
