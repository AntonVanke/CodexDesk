import asyncio
from contextlib import suppress
import threading
import time
import struct

from bleak import BleakClient, BleakScanner
from send_usage import read_usage, PACKET, CHARACTERISTIC
from upgrade import upload_firmware, REVISION
from pathlib import Path
from codex_tasks import CodexTasks
from task_screen import TaskCarousel, pack_bitmap
from account import read_account
from pair_device import pair_with_pin, unpair

TASK_CHARACTERISTIC = 'cdc00003-7a2b-4f3d-9a10-145850000001'


class DesktopBridge:
    def __init__(self, events, address, interval, profile):
        self.events = events
        self.address = address
        self.interval = interval
        self.sequence = int(time.time()) & 0xffff
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.firmware_path = None
        self.expected_revision = None
        self.upgrading = False
        self.profile = profile
        self.client = None
        self.tasks = CodexTasks()
        self.last_frame = None
        self.account = None
        self.snapshot = {'tasks': [], 'running': 0, 'waiting': 0, 'unread': 0}
        self.manual_requested = False

    def set_profile(self, profile):
        def update():
            self.profile = profile
            self.last_frame = None
            if self.client and self.client.is_connected:
                self.loop.create_task(self.apply_profile(self.client))
        self.loop.call_soon_threadsafe(update)

    async def apply_profile(self, client):
        theme, accent, name, layout = self.profile
        try:
            async with self.io:
                await client.write_gatt_char(CHARACTERISTIC, b'CS'+bytes((theme,accent)), response=True)
                for offset in range(0,len(name),16):
                    await client.write_gatt_char(CHARACTERISTIC,b'CN'+struct.pack('<H',offset)+name[offset:offset+16],response=True)
                await client.write_gatt_char(CHARACTERISTIC,b'CA',response=True)
                await client.write_gatt_char(CHARACTERISTIC,b'CL'+bytes((layout,)),response=True)
            self.events.profile_applied.emit()
        except Exception as error:
            self.events.error.emit('屏幕样式未发送',str(error))

    def upgrade(self, path):
        def start():
            self.firmware_path = path
            self.wake.set()
        self.loop.call_soon_threadsafe(start)

    def start(self):
        self.thread.start()

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.wake = asyncio.Event()
        self.io = asyncio.Lock()
        self.task = self.loop.create_task(self.monitor())
        self.observer = self.loop.create_task(self.observe())
        self.events.ready.emit()
        self.loop.run_forever()

    def refresh(self):
        def request():
            self.manual_requested=True
            self.wake.set()
        self.loop.call_soon_threadsafe(request)

    def connect_code(self, code):
        asyncio.run_coroutine_threadsafe(self.pair_code(code), self.loop)

    async def pair_code(self, code):
        self.task.cancel()
        with suppress(asyncio.CancelledError): await self.task
        self.address=''
        self.events.connection.emit('配对中', '')
        try:
            identifier, pin = code[:6], code[6:]
            device = await BleakScanner.find_device_by_filter(
                lambda _, adv: adv.manufacturer_data.get(0xffff, b'')[:3].hex().upper()==identifier,
                timeout=15)
            if device is None:
                raise RuntimeError('未找到对应屏幕')
            await pair_with_pin(device.address, pin)
            self.address=device.address
            self.events.paired.emit(device.address,identifier)
        except Exception as error:
            self.events.error.emit('配对未完成',str(error))
            self.events.connection.emit('未配对','')
        self.task=self.loop.create_task(self.monitor())

    def forget(self):
        asyncio.run_coroutine_threadsafe(self.forget_current(),self.loop)

    async def forget_current(self):
        try:
            address=self.address
            if self.client and self.client.is_connected:
                async with self.io:
                    await self.client.write_gatt_char(CHARACTERISTIC,b'CF',response=True)
            self.task.cancel()
            with suppress(asyncio.CancelledError):await self.task
            await unpair(address)
            self.address=''
            self.events.paired.emit('','')
            self.task=self.loop.create_task(self.monitor())
        except Exception as error:
            self.events.error.emit('解除配对未完成',str(error))

    async def observe(self):
        while True:
            account = await asyncio.to_thread(read_account)
            if account != self.account:
                self.account = account
                self.tasks = CodexTasks()
                self.snapshot = {'tasks': [], 'running': 0, 'waiting': 0, 'unread': 0}
                self.last_frame = None
                self.events.tasks.emit(self.snapshot)
                self.events.account.emit(account)
                if self.client and self.client.is_connected and not self.upgrading:
                    async with self.io:
                        await self.client.write_gatt_char(CHARACTERISTIC,b'CC',response=True)
                self.wake.set()
            self.snapshot = await asyncio.to_thread(self.tasks.snapshot, account)
            self.events.tasks.emit(self.snapshot)
            await asyncio.sleep(1)

    def set_interval(self, seconds):
        def update():
            self.interval = seconds
            self.wake.set()
        self.loop.call_soon_threadsafe(update)

    def set_device(self, address):
        asyncio.run_coroutine_threadsafe(self.switch_device(address), self.loop)

    async def switch_device(self, address):
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.task
        self.address = address
        self.task = self.loop.create_task(self.monitor())

    def scan(self):
        asyncio.run_coroutine_threadsafe(self.scan_devices(), self.loop)

    async def scan_devices(self):
        try:
            found = await BleakScanner.discover(timeout=6, return_adv=True)
            devices = [{'name': adv.local_name, 'address': device.address, 'rssi': adv.rssi}
                       for device, adv in found.values() if adv.local_name]
            devices.sort(key=lambda d: (not d['name'].startswith('CodexDesk'), -d['rssi']))
            self.events.devices.emit(devices)
        except Exception as error:
            self.events.error.emit('蓝牙搜索失败', str(error))
        finally:
            self.events.scanned.emit()

    async def wait(self, seconds):
        self.events.scheduled.emit(time.time() + seconds)
        try:
            await asyncio.wait_for(self.wake.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass
        self.wake.clear()

    async def sync(self, client, manual=False):
        if not self.account:
            if manual:self.events.busy.emit(False)
            return
        if manual: self.events.busy.emit(True)
        try:
            account = read_account()
            window, resets = await asyncio.to_thread(read_usage)
            if account != read_account():
                self.wake.set()
                return
            self.sequence = (self.sequence + 1) & 0xffff
            sequence = self.sequence
            remaining = round(window['remainingPercent'])
            packet = PACKET.pack(b'CD', 1, remaining, 255 if resets is None else min(254, resets), 1,
                                 int(time.time()), int(window['resetsAt']),
                                 int(window['windowDurationMins']), sequence)
            async with self.io:
                await client.write_gatt_char(CHARACTERISTIC, packet, response=True)
                async with asyncio.timeout(15):
                    while True:
                        await asyncio.sleep(0.2)
                        ack = PACKET.unpack(bytes(await client.read_gatt_char(CHARACTERISTIC)))
                        if ack[-1] == sequence and ack[4] & 0x80:
                            break
            self.events.updated.emit({
                'remaining': remaining, 'reset': int(window['resetsAt']),
                'window_minutes': window['windowDurationMins'], 'resets': resets,
                'plan': window['plan'], 'synced_at': time.time(), 'address': self.address,
            })
        finally:
            if manual: self.events.busy.emit(False)

    async def send_frame(self, client, frame):
        bitmap, kind, waiting, choices = frame
        packed = pack_bitmap(bitmap)
        self.sequence = (self.sequence+1) & 0xffff
        sequence = self.sequence
        async with self.io:
            await client.write_gatt_char(TASK_CHARACTERISTIC, struct.pack('<cHHBBB', b'B', sequence, len(packed), kind, waiting, choices), response=True)
            chunk = min(244, client.mtu_size-3)-3
            for offset in range(0, len(packed), chunk):
                await client.write_gatt_char(TASK_CHARACTERISTIC, b'D'+struct.pack('<H', offset)+packed[offset:offset+chunk], response=True)
            await client.write_gatt_char(TASK_CHARACTERISTIC, b'E', response=True)
            async with asyncio.timeout(15):
                while True:
                    ack_sequence, ready, _ = struct.unpack('<HBB', bytes(await client.read_gatt_char(TASK_CHARACTERISTIC)))
                    if ack_sequence == sequence and ready:
                        if ready != 1:
                            raise RuntimeError('屏幕任务帧传输不完整')
                        return
                    await asyncio.sleep(0.1)

    async def task_updates(self, client):
        carousel = TaskCarousel()
        self.last_frame = None
        try:
            while client.is_connected:
                snapshot = self.snapshot
                if self.profile[3]:
                    deadline = carousel.deadline
                    frame = carousel.frame(snapshot, time.monotonic())
                    if frame != self.last_frame:
                        started = time.monotonic()
                        await self.send_frame(client, frame)
                        if carousel.deadline != deadline:
                            carousel.deadline += time.monotonic()-started
                        self.last_frame = frame
                await asyncio.sleep(1)
        except Exception as error:
            self.events.error.emit('任务同步失败', str(error))
            raise

    async def monitor(self):
        while True:
            try:
                if not self.address:
                    self.events.connection.emit('未配对','')
                    await self.wait(3600)
                    continue
                self.events.connection.emit('正在连接', self.address)
                async with BleakClient(self.address, timeout=20, winrt={'use_cached_services': False},
                                       disconnected_callback=lambda _: self.loop.call_soon_threadsafe(self.wake.set)) as client:
                    self.client=client
                    self.events.connection.emit('已连接', self.address)
                    revision=bytes(await client.read_gatt_char(REVISION)).decode().rstrip('\0')
                    self.events.firmware.emit(revision)
                    await self.apply_profile(client)
                    if self.expected_revision:
                        if revision!=self.expected_revision:
                            raise RuntimeError(f'重启后固件版本为 {revision}')
                        self.expected_revision=None
                        self.upgrading=False
                        self.events.upgrade_done.emit(True,revision)
                    panel = self.loop.create_task(self.task_updates(client)) if client.services.get_characteristic(TASK_CHARACTERISTIC) else None
                    try:
                        while client.is_connected:
                            self.wake.clear()
                            if self.firmware_path:
                                if panel:
                                    panel.cancel()
                                    with suppress(asyncio.CancelledError): await panel
                                    panel=None
                                path,self.firmware_path=self.firmware_path,None
                                self.upgrading=True
                                self.expected_revision=Path(path).read_bytes()[12:28].split(b'\0')[0].decode()
                                async with self.io:
                                    await upload_firmware(client,path,self.events.upgrade_progress.emit)
                                break
                            if panel and panel.done():
                                panel.result()
                            manual,self.manual_requested=self.manual_requested,False
                            await self.sync(client,manual)
                            if self.firmware_path is None:
                                await self.wait(self.interval)
                    finally:
                        if panel:
                            panel.cancel()
                            with suppress(asyncio.CancelledError): await panel
                        self.client=None
            except Exception as error:
                if self.upgrading and self.expected_revision:
                    self.upgrading=False
                    self.expected_revision=None
                    self.events.upgrade_done.emit(False,str(error))
                self.events.connection.emit('连接待恢复', self.address)
                self.events.error.emit('同步未完成，稍后重试', str(error))
                await self.wait(10)

    async def close(self):
        self.observer.cancel()
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.observer
        with suppress(asyncio.CancelledError):
            await self.task

    def stop(self):
        asyncio.run_coroutine_threadsafe(self.close(), self.loop).result()
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join()
