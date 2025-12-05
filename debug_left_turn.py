import time
from drivers.motor.arduino_driver import ArduinoDriver

# Kết nối
driver = ArduinoDriver()
time.sleep(2) # Chờ kết nối

print("TEST 1: Quay TRÁI tại chỗ (Left=-150, Right=150)")
driver.set_motors(-220, 220)
time.sleep(5)
driver.stop()

# print("TEST 2: Chỉ quay bánh TRÁI lùi (Left=-150, Right=0)")
# driver.set_motors(-150, 0)
# time.sleep(2)
# driver.stop()

# print("TEST 3: Chỉ quay bánh TRÁI tiến (Left=150, Right=0)")
# driver.set_motors(150, 0)
# time.sleep(2)
# driver.stop()