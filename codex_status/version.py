APP_VERSION = '1.7.2'
FIRMWARE_VERSION = '1.6.0'


def version_tuple(value):
    return tuple(int(part) for part in value.removeprefix('v').split('.'))
