"""生成 itent 图标：黑底白字 ICO 格式"""
from PIL import Image, ImageDraw, ImageFont
import os

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 255))
draw = ImageDraw.Draw(img)

# 尝试用系统字体
font_paths = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",  # 粗体
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/consola.ttf",
]

text = "itent"
font = None
font_size = 48  # 小字体，确保完整显示

# 二分法找到最大能放入画布的字体大小
for fp in font_paths:
    if os.path.exists(fp):
        try:
            # 从大到小试，找到能完整放入 256x256 的字体大小
            for size in range(100, 20, -4):
                f = ImageFont.truetype(fp, size)
                bbox = draw.textbbox((0, 0), text, font=f)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                if tw <= SIZE * 0.85 and th <= SIZE * 0.6:
                    font = f
                    font_size = size
                    break
            if font:
                break
        except Exception:
            pass

if font is None:
    font = ImageFont.load_default()
    font_size = 36

# 居中绘制白字
bbox = draw.textbbox((0, 0), text, font=font)
tw = bbox[2] - bbox[0]
th = bbox[3] - bbox[1]
x = (SIZE - tw) // 2
y = (SIZE - th) // 2
draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

print(f"字体大小: {font_size}, 文字尺寸: {tw}x{th}")

# 保存为 ICO（含多种尺寸）
ico_path = os.path.join(os.path.dirname(__file__), "itent.ico")
sizes = [256, 128, 64, 48, 32, 16]
imgs = [img.resize((s, s), Image.LANCZOS) for s in sizes]
imgs[0].save(ico_path, format="ICO", sizes=[(s, s) for s in sizes])
print(f"ICO 已生成: {ico_path}")

# 同时保存 PNG 备用
png_path = os.path.join(os.path.dirname(__file__), "itent.png")
img.save(png_path, format="PNG")
print(f"PNG 已生成: {png_path}")
