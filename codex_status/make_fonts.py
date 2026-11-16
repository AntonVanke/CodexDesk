from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import qrcode

ROOT = Path(__file__).resolve().parent

def generate():
    source = (ROOT/'firmware/display.c').read_text(encoding='utf-8')
    chinese = {c for c in source if '\u4e00' <= c <= '\u9fff'}
    out = ['struct glyph { uint16_t code, offset; uint8_t width, height; };']
    for size in (14, 20, 64):
        chars = sorted(set('0123456789-') if size == 64 else {chr(i) for i in range(32,127)} | chinese)
        font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', size)
        bits, entries = bytearray(), []
        for c in chars:
            width = max(1, round(font.getlength(c)))
            img = Image.new('1', (width, size+4))
            ImageDraw.Draw(img).text((0,0), c, font=font, fill=1, anchor='lt')
            data = img.tobytes()
            entries.append(f'{{{ord(c)},{len(bits)},{width},{size+4}}}')
            bits.extend(data)
        if len(bits) >= 65536: raise ValueError('Font offset overflow')
        out.append(f'static const uint8_t font{size}_bits[] = {{'+','.join(map(str,bits))+'};')
        out.append(f'static const struct glyph font{size}[] = {{'+','.join(entries)+'};')
    (ROOT/'firmware/fonts.inc').write_text('\n'.join(out),encoding='ascii')
    qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,border=4)
    qr.add_data('https://github.com/AntonVanke/CodexDesk/releases/latest')
    qr.make(fit=True)
    matrix=qr.get_matrix();size=len(matrix);stride=(size+7)//8
    bits=bytearray(size*stride)
    for y,row in enumerate(matrix):
        for x,value in enumerate(row):
            if value:bits[y*stride+x//8]|=0x80>>(x%8)
    (ROOT/'firmware/pairing_qr.inc').write_text(f'#define QR_SIZE {size}\nstatic const uint8_t qr_bits[]={{'+','.join(map(str,bits))+'};\n',encoding='ascii')

if __name__ == '__main__': generate()
