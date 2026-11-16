from winrt.windows.devices.bluetooth import BluetoothLEDevice, BluetoothAddressType
from winrt.windows.devices.enumeration import (
    DeviceInformation, DevicePairingKinds, DevicePairingProtectionLevel, DevicePairingResultStatus,
)


async def device_info(address):
    device = await BluetoothLEDevice.from_bluetooth_address_with_bluetooth_address_type_async(
        int(address.replace(':', ''), 16), BluetoothAddressType.RANDOM)
    info = await DeviceInformation.create_from_id_async(device.device_information.id)
    return device, info


async def pair_with_pin(address, pin):
    device, info = await device_info(address)
    try:
        if info.pairing.is_paired:
            await info.pairing.unpair_async()
            info = await DeviceInformation.create_from_id_async(device.device_information.id)
        custom = info.pairing.custom
        token = custom.add_pairing_requested(lambda _, args: args.accept_with_pin(pin))
        try:
            result = await custom.pair_with_protection_level_async(
                DevicePairingKinds.PROVIDE_PIN, DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION)
        finally:
            custom.remove_pairing_requested(token)
        if result.status not in (DevicePairingResultStatus.PAIRED, DevicePairingResultStatus.ALREADY_PAIRED):
            raise RuntimeError('蓝牙配对失败：'+result.status.name)
    finally:
        device.close()


async def unpair(address):
    device, info = await device_info(address)
    try:
        await info.pairing.unpair_async()
    finally:
        device.close()
