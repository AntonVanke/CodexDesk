from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import os
import struct
import subprocess
import time
import zlib

ROOT = Path(__file__).resolve().parent
SRC = ROOT/'firmware'
OUT = ROOT/'build'


def main():
    from make_fonts import generate
    generate()
    local = ROOT/'toolchain.local.json'
    paths = json.loads(local.read_text()) if local.exists() else {}
    sdk = Path(os.environ.get('RENESAS_SDK', paths.get('sdk', 'sdk')))
    llvm = Path(os.environ.get('ARM_LLVM', paths.get('llvm', 'llvm')))/'bin'
    manifest = json.loads((ROOT/'sdk-build.json').read_text())
    OUT.mkdir(exist_ok=True)
    includes = [SRC, SRC/'config', *(sdk/p for p in manifest['includes'])]

    def run(command):
        result = subprocess.run(list(map(str, command)), cwd=OUT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode:
            raise RuntimeError(result.stdout+result.stderr)
        return result.stdout

    units = [(sdk/u['source'], OUT/u['object'], u['flags']) for u in manifest['sources']]
    units.extend((p, OUT/(p.stem+'.o'), manifest['compiler']) for p in SRC.glob('*.c'))

    def compile_one(unit):
        source, output, flags = unit
        output.parent.mkdir(parents=True, exist_ok=True)
        run([llvm/'clang.exe', *flags, '-c', '-D__DA14585__',
             *(arg for path in includes for arg in ('-I', path)), source, '-o', output])
        return output

    with ThreadPoolExecutor(max_workers=6) as pool:
        objects = list(pool.map(compile_one, units))
    script = OUT/'link.lds'
    run([llvm/'clang.exe', '-E', '-P', '-c', '-D__DA14585__', '-I', SRC/'config',
         '-I', sdk/'sdk/common_project_files', '-I', sdk/'sdk/common_project_files/ldscripts', SRC/'memory.ld.S', '-o', script])
    flags = manifest['linker']
    index = flags.index('-T')
    del flags[index:index+2]
    run([llvm/'clang.exe', *flags, '-T', script, '-Wl,-eReset_Handler', f'-Wl,-Map={OUT/"codex_status.map"}',
         *objects, '-L', sdk/'sdk/common_project_files/misc', '-L', sdk/'sdk/platform/system_library/output/Keil_5',
         '-l:da14585_586.lib', '-o', OUT/'codex_status.elf'])
    run([llvm/'llvm-objcopy.exe', '-O', 'binary', OUT/'codex_status.elf', OUT/'codex_status.bin'])
    print(run([llvm/'llvm-size.exe', OUT/'codex_status.elf']))
    data = (OUT/'codex_status.bin').read_bytes()
    header = bytearray(b'\xff'*64)
    header[:2] = b'\x70\x51'
    struct.pack_into('<II', header, 4, len(data), zlib.crc32(data))
    header[12:28] = b'1.5.0\0'.ljust(16, b'\xff')
    struct.pack_into('<I', header, 28, int(time.time()))
    header[32] = 0
    (OUT/'codex_status.img').write_bytes(header+data)
    print('Firmware:', OUT/'codex_status.img')


if __name__ == '__main__':
    main()
