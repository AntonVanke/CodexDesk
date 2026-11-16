import argparse
import asyncio
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

from bleak import BleakClient, BleakScanner

ROOT = Path(__file__).resolve().parent
USAGE_SCRIPT = Path(sys._MEIPASS) / 'Get-CodexUsage.ps1' if getattr(sys, 'frozen', False) else ROOT.parent / 'Get-CodexUsage.ps1'
CHARACTERISTIC = 'cdc00002-7a2b-4f3d-9a10-145850000001'
DEFAULT_ADDRESS = 'C0:DE:14:85:02:40'
PACKET = struct.Struct('<2sBBBBIIIH')

def read_usage():
    process = subprocess.run(
        ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
         str(USAGE_SCRIPT),'-Json'],
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode:
        raise RuntimeError(process.stderr.strip() or process.stdout.strip())
    result = json.loads(process.stdout)
    windows = [w for w in result['windows'] if w['limitId']=='codex'
               and w['remainingPercent'] is not None and w['resetsAt'] is not None]
    if not windows: raise RuntimeError('Codex did not return a usable quota window')
    window = max(windows,key=lambda w:w.get('windowDurationMins') or 0)
    return window,result.get('availableResets')

async def deliver(client, sequence):
    window,resets = await asyncio.to_thread(read_usage)
    remaining = round(window['remainingPercent'])
    packet = PACKET.pack(b'CD',1,remaining,255 if resets is None else min(254,resets),1,
                         int(time.time()),int(window['resetsAt']),
                         int(window['windowDurationMins']),sequence)
    await client.write_gatt_char(CHARACTERISTIC,packet,response=True)
    deadline = time.monotonic()+15
    while time.monotonic()<deadline:
        await asyncio.sleep(0.25)
        ack = bytes(await client.read_gatt_char(CHARACTERISTIC))
        if len(ack)==20 and ack[:5]==packet[:5] and ack[6:]==packet[6:] and ack[5]&0x80:
            record={'sentAt':datetime.now(timezone.utc).isoformat(),
                    'device':client.address,'remainingPercent':remaining,
                    'windowDurationMins':window['windowDurationMins'],
                    'resetBeijing':datetime.fromtimestamp(window['resetsAt'],timezone(timedelta(hours=8))).isoformat(),
                    'sequence':sequence,'displayConfirmed':True}
            (ROOT/'last_delivery.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
            print(json.dumps(record),flush=True)
            return
    raise TimeoutError('Device did not acknowledge a completed display update')

async def main(args):
    sequence = int(time.time()) & 0xffff
    while True:
        try:
            device = await BleakScanner.find_device_by_address(args.address,timeout=12)
            if device is None: raise RuntimeError(f'CodexDesk {args.address} was not found')
            async with BleakClient(device,timeout=20) as client:
                print(f'Connected: {device.name} {device.address}',flush=True)
                while client.is_connected:
                    sequence = (sequence+1)&0xffff
                    await deliver(client,sequence)
                    if args.once: return
                    await asyncio.sleep(args.interval)
        except Exception as error:
            print(f'{datetime.now().isoformat(timespec="seconds")} ERROR: {error}',flush=True)
            if args.once: raise
            await asyncio.sleep(10)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Send current Codex usage to the DA14585 display over BLE.')
    parser.add_argument('--address',default=DEFAULT_ADDRESS)
    parser.add_argument('--interval',type=int,default=60)
    parser.add_argument('--once',action='store_true')
    args=parser.parse_args()
    if args.interval<10: parser.error('--interval must be at least 10 seconds')
    try: asyncio.run(main(args))
    except KeyboardInterrupt: pass
