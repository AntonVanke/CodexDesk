import asyncio
from contextlib import suppress
import threading
import time
import struct

from bleak import BleakClient, BleakScanner
from send_usage import read_usage_async, PACKET, CHARACTERISTIC
from upgrade import upload_firmware, REVISION
from pathlib import Path
from datetime import datetime
from codex_tasks import CodexTasks
from task_screen import TaskCarousel, pack_bitmap, render_model
from account import read_account
from pair_device import pair_with_pin, unpair
from source_watch import SourceWatch
from version import version_tuple

TASK_CHARACTERISTIC = 'cdc00003-7a2b-4f3d-9a10-145850000001'


class DesktopBridge:
    def __init__(self, events, address, profile):
        self.events = events
        self.address = address
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
        self.quota = None
        self.quota_refresh = True
        self.quota_checked = 0
        self.sent_quota = None
        self.sent_profile = None
        self.sent_model = None
        self.sent_alerts = None

    def set_profile(self, profile):
        def update():
            self.profile = profile
            if self.client and self.client.is_connected and not self.upgrading:
                self.loop.create_task(self.apply_profile(self.client))
        self.loop.call_soon_threadsafe(update)

    async def apply_profile(self, client):
        profile = self.profile
        theme, accent, name, layout, brightness = profile
        try:
            async with self.io:
                previous = self.sent_profile
                if previous is None or profile[:3] != previous[:3]:
                    if previous is None or profile[:2] != previous[:2]:
                        await client.write_gatt_char(CHARACTERISTIC, b'CS'+bytes((theme,accent)), response=True)
                    if previous is None or name != previous[2]:
                        for offset in range(0,len(name),16):
                            await client.write_gatt_char(CHARACTERISTIC,b'CN'+struct.pack('<H',offset)+name[offset:offset+16],response=True)
                    await client.write_gatt_char(CHARACTERISTIC,b'CA',response=True)
                if previous is None or layout != previous[3]:
                    await client.write_gatt_char(CHARACTERISTIC,b'CL'+bytes((layout,)),response=True)
                if previous is None or brightness != previous[4]:
                    await client.write_gatt_char(CHARACTERISTIC,b'CB'+bytes((brightness,)),response=True)
                self.sent_profile = profile
            self.panel_wake.set()
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
        self.source_dirty = asyncio.Event()
        self.panel_wake = asyncio.Event()
        self.io = asyncio.Lock()
        self.watcher = SourceWatch(lambda: self.loop.call_soon_threadsafe(self.source_dirty.set))
        self.source_dirty.set()
        self.task = self.loop.create_task(self.monitor())
        self.observer = self.loop.create_task(self.observe())
        self.events.ready.emit()
        self.loop.run_forever()

    def refresh(self):
        def request():
            self.manual_requested=True
            self.quota_refresh=True
            self.source_dirty.set()
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
            await self.source_dirty.wait()
            self.source_dirty.clear()
            await asyncio.sleep(0.2)
            account = await asyncio.to_thread(read_account)
            if account != self.account:
                self.account = account
                self.tasks = CodexTasks()
                self.snapshot = {'tasks': [], 'running': 0, 'waiting': 0, 'unread': 0}
                self.last_frame = None
                self.quota = None
                self.sent_quota = None
                self.quota_refresh = True
                self.quota_checked = 0
                self.events.tasks.emit(self.snapshot)
                self.events.account.emit(account)
                if self.client and self.client.is_connected and not self.upgrading:
                    async with self.io:
                        await self.client.write_gatt_char(CHARACTERISTIC,b'CC',response=True)
                self.wake.set()
            snapshot = await asyncio.to_thread(self.tasks.snapshot, account)
            if snapshot != self.snapshot:
                before = {t['id'] for t in self.snapshot['tasks'] if t['active']}
                after = {t['id'] for t in snapshot['tasks'] if t['active']}
                if before - after:
                    self.quota_refresh = True
                self.snapshot = snapshot
                self.events.tasks.emit(snapshot)
                self.panel_wake.set()
                self.wake.set()
            usage = self.tasks.latest_usage()
            if usage and datetime.fromisoformat(usage[0]).timestamp() > self.quota_checked:
                stamp, bucket = usage
                windows = [w for w in (bucket.get('primary'),bucket.get('secondary')) if w]
                if bucket.get('limit_id') == 'codex' and windows:
                    window = max(windows,key=lambda w:w['window_minutes'])
                    self.quota = {'remaining': round(100-window['used_percent']), 'reset': window['resets_at'],
                        'window_minutes': window['window_minutes'], 'resets': self.quota['resets'] if self.quota else None,
                        'plan': bucket.get('plan_type') or '', 'synced_at': time.time(), 'address': self.address}
                    self.quota_checked = datetime.fromisoformat(stamp).timestamp()
                    self.events.updated.emit(self.quota)
                    self.wake.set()

    def source_changed(self):
        self.loop.call_soon_threadsafe(self.source_dirty.set)

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
            if self.quota_refresh:
                self.quota_refresh = False
                account = read_account()
                window, resets = await read_usage_async()
                if account != read_account():
                    self.quota_refresh = True
                    self.wake.set()
                    return
                self.quota_checked = time.time()
                self.quota = {'remaining': round(window['remainingPercent']), 'reset': int(window['resetsAt']),
                    'window_minutes': window['windowDurationMins'], 'resets': resets, 'plan': window['plan'],
                    'synced_at': time.time(), 'address': self.address}
                self.events.updated.emit(self.quota)
            data = self.quota
            if data is None:
                return
            quota = (data['remaining'], 255 if data['resets'] is None else min(254,data['resets']),
                     data['reset'], data['window_minutes'])
            if quota == self.sent_quota:
                return
            self.sequence = (self.sequence + 1) & 0xffff
            sequence = self.sequence
            packet = struct.pack('<2sBBIIH',b'CQ',*quota,sequence)
            async with self.io:
                await client.write_gatt_char(CHARACTERISTIC, packet, response=True)
                async with asyncio.timeout(15):
                    while True:
                        await asyncio.sleep(0.2)
                        ack = PACKET.unpack(bytes(await client.read_gatt_char(CHARACTERISTIC)))
                        if ack[-1] == sequence and ack[4] & 0x80:
                            break
            self.sent_quota = quota
        except Exception:
            self.quota_refresh = True
            raise
        finally:
            if manual: self.events.busy.emit(False)

    async def send_frame(self, client, frame):
        bitmap, kind, waiting, choices = frame
        if self.last_frame is not None:
            bitmap = bytes(a^b for a,b in zip(bitmap,self.last_frame[0]))
            kind |= 0x80
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
                self.panel_wake.clear()
                snapshot = self.snapshot
                alerts = int(any(t['completed_unread'] for t in snapshot['tasks'])) | (2 if snapshot['waiting'] else 0)
                deadline = carousel.deadline
                frame = carousel.frame(snapshot, time.monotonic())
                selected = carousel.selected if self.profile[3] else snapshot['tasks'][int(time.monotonic()/5)%len(snapshot['tasks'])] if snapshot['tasks'] else None
                model = render_model(selected)
                async with self.io:
                    if alerts != self.sent_alerts:
                        await client.write_gatt_char(CHARACTERISTIC,b'CE'+bytes((alerts,)),response=True)
                        self.sent_alerts = alerts
                    if model != self.sent_model:
                        for offset in range(0,len(model),16):
                            if self.sent_model is None or model[offset:offset+16] != self.sent_model[offset:offset+16]:
                                await client.write_gatt_char(CHARACTERISTIC,b'CM'+struct.pack('<H',offset)+model[offset:offset+16],response=True)
                        await client.write_gatt_char(CHARACTERISTIC,b'CZ',response=True)
                        self.sent_model = model
                if self.profile[3]:
                    if frame != self.last_frame:
                        started = time.monotonic()
                        await self.send_frame(client, frame)
                        if carousel.deadline != deadline:
                            carousel.deadline += time.monotonic()-started
                        self.last_frame = frame
                timeout = max(0.1,min(5,carousel.deadline-time.monotonic())) if self.profile[3] else 5
                try:
                    await asyncio.wait_for(self.panel_wake.wait(), timeout)
                except asyncio.TimeoutError:
                    pass
        except Exception as error:
            self.wake.set()
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
                    self.sent_profile = self.sent_quota = self.sent_model = self.sent_alerts = None
                    self.events.connection.emit('已连接', self.address)
                    revision=bytes(await client.read_gatt_char(REVISION)).decode().rstrip('\0')
                    self.events.firmware.emit(revision)
                    if self.expected_revision:
                        if revision!=self.expected_revision:
                            raise RuntimeError(f'重启后固件版本为 {revision}')
                        self.expected_revision=None
                        self.upgrading=False
                        self.events.upgrade_done.emit(True,revision)
                    if self.firmware_path is None and version_tuple(revision)<(1,6,0):
                        self.events.connection.emit('请升级固件', self.address)
                        while client.is_connected and self.firmware_path is None:
                            await self.wait(3600)
                    await self.apply_profile(client)
                    clock_at = heartbeat_at = 0
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
                            if self.observer.done():
                                self.observer.result()
                            manual,self.manual_requested=self.manual_requested,False
                            now = time.monotonic()
                            async with self.io:
                                if now >= clock_at:
                                    await client.write_gatt_char(CHARACTERISTIC,b'CT'+struct.pack('<I',int(time.time())),response=True)
                                    clock_at = now+3600
                                if now >= heartbeat_at:
                                    await client.write_gatt_char(CHARACTERISTIC,b'CH',response=True)
                                    heartbeat_at = now+60
                                    self.events.contact.emit(time.time())
                            await self.sync(client,manual)
                            if self.firmware_path is None:
                                delay = min(heartbeat_at,clock_at)-time.monotonic()
                                if self.quota and self.quota['reset']>time.time():
                                    delay = min(delay,self.quota['reset']-time.time())
                                elif self.quota and self.quota_checked<self.quota['reset']:
                                    self.quota_refresh=True
                                    continue
                                await self.wait(max(0.1,delay))
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
                self.events.connection.emit('离线', self.address)
                self.events.error.emit('同步未完成，稍后重试', str(error))
                await self.wait(10)

    async def close(self):
        self.watcher.close()
        self.observer.cancel()
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            await self.observer
        with suppress(asyncio.CancelledError):
            await self.task
        pending=[task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)

    def stop(self):
        async def shutdown():
            try:
                await self.close()
            finally:
                self.loop.call_soon(self.loop.stop)
                self.events.stopped.emit()
        asyncio.run_coroutine_threadsafe(shutdown(),self.loop)
