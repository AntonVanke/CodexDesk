import asyncio
from functools import reduce
from operator import xor
from pathlib import Path
import struct

MEM_DEV='8082caa8-41a6-4021-91c6-56f9b954cc34'
GPIO_MAP='724249f0-5ec3-4b5f-8804-42345af08651'
PATCH_LEN='9d84b9a3-000c-49d8-9183-855b673fda31'
PATCH_DATA='457871e8-d516-4ca1-9116-57d0b17b9cb2'
STATUS='5f78df94-798c-46f5-990a-b3eb6a065c88'
REVISION='00002a26-0000-1000-8000-00805f9b34fb'
QUOTA='cdc00002-7a2b-4f3d-9a10-145850000001'


async def upload_firmware(client, path, progress):
    data=Path(path).read_bytes()
    data+=bytes([reduce(xor,data,0)])
    notices=asyncio.Queue()
    await client.start_notify(STATUS,lambda _,value:notices.put_nowait(value[0]))
    async def expect(value):
        status=await asyncio.wait_for(notices.get(),30)
        if status!=value:
            raise RuntimeError(f'屏幕升级返回状态 0x{status:02X}')
    await client.write_gatt_char(MEM_DEV,struct.pack('<I',0x13000000),response=True)
    await expect(0x10)
    await client.write_gatt_char(GPIO_MAP,struct.pack('<I',0x05060300),response=True)
    progress(0,'正在传输固件')
    for offset in range(0,len(data),512):
        block=data[offset:offset+512]
        await client.write_gatt_char(PATCH_LEN,struct.pack('<H',len(block)),response=True)
        for start in range(0,len(block),20):
            await client.write_gatt_char(PATCH_DATA,block[start:start+20],response=False)
        await expect(2)
        progress((offset+len(block))*100//len(data),'正在传输固件')
    progress(100,'正在校验固件')
    await client.write_gatt_char(MEM_DEV,struct.pack('<I',0xfe000000),response=True)
    await expect(2)
    await client.write_gatt_char(QUOTA,b'CU\x03',response=True)
    progress(100,'升级完成，屏幕正在重启')
    await asyncio.sleep(1.5)
    await client.write_gatt_char(MEM_DEV,struct.pack('<I',0xfd000000),response=True)
