import os
from PIL import Image

src = "/home/openclaw/notitia-finances/assets/moka-sheet.jpg"
im = Image.open(src)
w, h = im.size
print(f"Original size: {w}x{h}")

# 1. Happy sitting bottom-right (cutest main avatar)
im.crop((int(w*0.56), int(h*0.45), int(w*0.96), int(h*0.98))).save("/home/openclaw/notitia-finances/assets/moka-happy.png")

# 2. Main Avatar face (happy sitting head)
im.crop((int(w*0.58), int(h*0.46), int(w*0.88), int(h*0.75))).save("/home/openclaw/notitia-finances/assets/moka-avatar.png")

# 3. Fighter DBZ full standing left
im.crop((int(w*0.02), int(h*0.01), int(w*0.38), int(h*0.98))).save("/home/openclaw/notitia-finances/assets/moka-dbz-full.png")

# 4. Fighter arms crossed upper body
im.crop((int(w*0.02), int(h*0.01), int(w*0.38), int(h*0.52))).save("/home/openclaw/notitia-finances/assets/moka-arms-crossed.png")

# 5. DBZ Attack / flying strike
im.crop((int(w*0.28), int(h*0.01), int(w*0.66), int(h*0.60))).save("/home/openclaw/notitia-finances/assets/moka-attack.png")

# 6. Side profile / side eye look
im.crop((int(w*0.66), int(h*0.01), int(w*0.99), int(h*0.54))).save("/home/openclaw/notitia-finances/assets/moka-sideeye.png")

print("Crops completed successfully!")
