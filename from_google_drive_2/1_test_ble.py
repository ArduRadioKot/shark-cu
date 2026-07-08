import asyncio

from bleak import BleakClient, BleakScanner


DEVICE_NAME = "airship_2"
UART_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

COMMANDS = {
    "f": "516",     # forward
    "b": "615",     # backward
    "s": "507",     # stop
    "l": "813",     # turn left/right depends on motor wiring
    "r": "714",     # turn left/right depends on motor wiring
}

def build_payload(raw_command):
    normalized = raw_command.replace(" ", "")
    parts = normalized.split(",", 1)
    direction = parts[0].lower()
    if direction not in COMMANDS:
        return None

    if len(parts) > 1 and parts[1]:
        print("Speed is ignored by this ESP32 firmware. Sending command without speed.")

    return f"AA{COMMANDS[direction]}".encode("utf-8")


async def find_device():
    print(f"Searching for BLE device {DEVICE_NAME!r}...")
    name_matches = {}
    seen_uart_devices = {}

    def on_detected(device, advertisement_data):
        name = advertisement_data.local_name or device.name or ""
        service_uuids = [uuid.upper() for uuid in advertisement_data.service_uuids]
        # print(f"  {device.address}  name={name!r}  services={service_uuids}")
        if UART_SERVICE_UUID in service_uuids:
            seen_uart_devices[device.address] = (name, device)
        if name == DEVICE_NAME:
            name_matches[device.address] = device

    scanner = BleakScanner(on_detected)
    await scanner.start()
    await asyncio.sleep(20.0)
    await scanner.stop()

    if len(name_matches) == 1:
        return next(iter(name_matches.values()))

    if len(name_matches) > 1:
        devices = ", ".join(f"{device.name!r} [{device.address}]" for device in name_matches.values())
        raise RuntimeError(f"Multiple BLE devices named {DEVICE_NAME!r} found: {devices}")

    candidates = ", ".join(f"{name!r} [{device.address}]" for name, device in seen_uart_devices.values())
    if candidates:
        raise RuntimeError(
            f"Device {DEVICE_NAME!r} not found by name. UART devices nearby: {candidates}"
        )
    raise RuntimeError(f"Device {DEVICE_NAME!r} not found")


async def main():
    device = await find_device()
    print(f"Found: {device.name} [{device.address}]")

    async with BleakClient(device) as client:
        print("Connected.")
        print("Commands: f=forward, b=backward, l=left, r=right, s=stop, q=quit")
        print("This ESP32 firmware expects commands without speed: AA516, AA615, AA507")

        while True:
            key = input("> ").strip().lower()
            if key == "q":
                await client.write_gatt_char(UART_RX_CHAR_UUID, b"AA507")
                break

            payload = build_payload(key)
            if payload is None:
                print("Unknown command")
                continue

            # ESP32 code removes the first two characters: command = command[2:]
            await client.write_gatt_char(UART_RX_CHAR_UUID, payload)
            print(f"Sent {payload.decode()}")


if __name__ == "__main__":
    asyncio.run(main())
