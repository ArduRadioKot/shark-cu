import asyncio
import bluetooth
import aiobleчй
from machine import Pin,PWM
from MX1508 import *

# UUID стандартного сервиса Nordic UART (NUS)
_UART_SERVICE_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_RX_CHAR_UUID = bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX_CHAR_UUID = bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")

# Настройка сервисов и характеристик
uart_service = aioble.Service(_UART_SERVICE_UUID)
# Характеристика RX (прием для ESP32) должна иметь флаг write
rx_characteristic = aioble.Characteristic(uart_service, _UART_RX_CHAR_UUID, write=True, capture=True)
# Характеристика TX (передача от ESP32)
tx_characteristic = aioble.Characteristic(uart_service, _UART_TX_CHAR_UUID, read=True, notify=True)

motor_L = MX1508(4, 3)
motor_R = MX1508(1, 0)
sp=800
on=0
command=''

aioble.register_services(uart_service)

async def handle_connection(connection):
    global command
    print("Новое подключение:", connection.device)
    while connection.is_connected():
        try:
            # Ожидаем запись в характеристику RX
            conn, data = await rx_characteristic.written()
            # Преобразование байтов в текст
            command = data.decode("utf-8").strip()
            command=command[2:]
            #print(f"Получена команда: {command}")
            await do_it(20)
            # Логика обработки команд
            if command == "ping":
                tx_characteristic.write(b"pong")
        except Exception as e:
            print("Ошибка приема:", e)
            break
    print("Устройство отключено")

async def main():
    print("BLE сервер запущен. Ожидание команд...")
    while True:
        await asyncio.sleep_ms(50)
        # устройство под именем "airship_one"
        async with await aioble.advertise(
            250000,
            name="airship_one",
            services=[_UART_SERVICE_UUID],
        ) as connection:
            await handle_connection(connection)   
            
async def do_it(int_ms):
    global command
    print(command)
    if command=='516':
        motor_R.forward(sp)
        motor_L.forward(sp)
    if command=='615':
        motor_L.reverse(sp)
        motor_R.reverse(sp)
    if (command=='507')or(command=='606')or(command=='705')or(command=='804'):
        motor_L.stop()
        motor_R.stop()
    if command=='813':
        motor_R.forward(sp)
        motor_L.reverse(sp)
    if command=='714':
        motor_L.forward(sp)
        motor_R.reverse(sp)    

# # Запуск основного цикла
# try:
#     asyncio.run(main())
# except KeyboardInterrupt:
#     print("Остановлено")
    
# define loop
loop = asyncio.get_event_loop()

#create looped tasks
#loop.create_task(do_it(50))
loop.create_task(main())

# loop run forever
loop.run_forever()    
