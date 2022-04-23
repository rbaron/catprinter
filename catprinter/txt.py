import tempfile

from PIL import Image, ImageDraw, ImageFont


def text_to_image(text):
    # Fix newline characters that argparse escaped
    text = text.replace("\\n", "\n")
    font_path = "fonts/Roboto-Regular.ttf"
    font_size = 72
    width_scalar = 0.25

    font = ImageFont.truetype(font_path, font_size, encoding="utf-8")
    w, h = font.getsize_multiline(text)
    image = Image.new("L", (w, int(h+h*width_scalar)), 255)
    draw = ImageDraw.Draw(image)
    draw.text((0,0), text, fill="black", font=font)

    bits = None
    with tempfile.TemporaryFile() as fp:
        image.save(fp, "PNG")
        fp.seek(0)
        bits = fp.read()

    return bits
