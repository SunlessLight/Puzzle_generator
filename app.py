import os
import random
import math
import shutil
import uuid
import zipfile
from flask import Flask, render_template, request, send_file, jsonify
from PIL import Image, ImageDraw

app = Flask(__name__)

# CONFIGURATION
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'static/generated'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# --- PUZZLE LOGIC (Same core logic, adapted for web) ---

def calculate_grid(width, height, num_pieces):
    aspect_ratio = width / height
    rows = int(math.sqrt(num_pieces / aspect_ratio))
    cols = int(num_pieces / max(rows, 1))
    if rows == 0: rows = 1
    if cols == 0: cols = 1
    return rows, cols

def generate_bezier_tab(base_length, is_tab=True):
    # Simplified Bezier-like curve generation for tabs
    tab_height = base_length * 0.2
    neck_width = base_length * 0.2
    head_width = base_length * 0.35
    points = []
    steps = 20
    for i in range(steps + 1):
        t = i / steps
        x_linear = (t - 0.5) * base_length
        y_shape = math.sin(t * math.pi) * tab_height
        x_bulge = math.sin(t * math.pi * 2 - (math.pi/2)) * (head_width - neck_width) / 2
        x = ((t - 0.5) * neck_width) + (x_bulge if 0.2 < t < 0.8 else 0)
        y = y_shape if is_tab else -y_shape
        points.append((x, y))
    return points

def create_piece_mask(piece_w, piece_h, edge_shapes):
    padding = max(piece_w, piece_h) * 0.4
    mask_w = int(piece_w + padding * 2)
    mask_h = int(piece_h + padding * 2)
    mask = Image.new('L', (mask_w, mask_h), 0)
    draw = ImageDraw.Draw(mask)
    
    tl = (padding, padding)
    tr = (padding + piece_w, padding)
    br = (padding + piece_w, padding + piece_h)
    bl = (padding, padding + piece_h)
    
    points = []
    
    # Logic to build polygon points based on edge_shapes (Top, Right, Bottom, Left)
    # 0=Flat, 1=Tab, -1=Hole
    # (Simplified for brevity, uses the same logic as previous script)
    
    # TOP
    if edge_shapes[0] == 0: points.extend([tl, tr])
    else:
        points.append(tl)
        curve = generate_bezier_tab(piece_w, is_tab=(edge_shapes[0] == 1))
        cx, cy = (tl[0] + tr[0]) / 2, tl[1]
        for px, py in curve: points.append((cx + px, cy - py))
        points.append(tr)

    # RIGHT
    if edge_shapes[1] == 0: points.append(br)
    else:
        curve = generate_bezier_tab(piece_h, is_tab=(edge_shapes[1] == 1))
        cx, cy = tr[0], (tr[1] + br[1]) / 2
        for px, py in curve: points.append((cx + py, cy + px))
        points.append(br)

    # BOTTOM
    if edge_shapes[2] == 0: points.append(bl)
    else:
        curve = generate_bezier_tab(piece_w, is_tab=(edge_shapes[2] == 1))
        cx, cy = (bl[0] + br[0]) / 2, bl[1]
        for px, py in curve: points.append((cx - px, cy + py))
        points.append(bl)

    # LEFT
    if edge_shapes[3] != 0:
        curve = generate_bezier_tab(piece_h, is_tab=(edge_shapes[3] == 1))
        cx, cy = tl[0], (tl[1] + bl[1]) / 2
        for px, py in curve: points.append((cx - py, cy - px))
    
    draw.polygon(points, fill=255)
    return mask, int(padding)

def process_image(image_path, num_pieces, session_id):
    original_image = Image.open(image_path).convert("RGBA")
    img_w, img_h = original_image.size
    rows, cols = calculate_grid(img_w, img_h, num_pieces)
    piece_w, piece_h = img_w / cols, img_h / rows
    
    session_dir = os.path.join(OUTPUT_FOLDER, session_id)
    pieces_dir = os.path.join(session_dir, "pieces")
    os.makedirs(pieces_dir, exist_ok=True)

    vertical_edges = [[random.choice([1, -1]) for _ in range(cols - 1)] for _ in range(rows)]
    horizontal_edges = [[random.choice([1, -1]) for _ in range(cols)] for _ in range(rows - 1)]

    for r in range(rows):
        for c in range(cols):
            top = 0 if r == 0 else -horizontal_edges[r-1][c]
            right = 0 if c == cols - 1 else vertical_edges[r][c]
            bottom = 0 if r == rows - 1 else horizontal_edges[r][c]
            left = 0 if c == 0 else -vertical_edges[r][c-1]

            mask, padding = create_piece_mask(piece_w, piece_h, (top, right, bottom, left))
            crop_x, crop_y = int(c * piece_w - padding), int(r * piece_h - padding)
            
            piece_image = Image.new('RGBA', mask.size, (0, 0, 0, 0))
            src_x, src_y = max(0, crop_x), max(0, crop_y)
            src_w = min(img_w, crop_x + mask.size[0]) - src_x
            src_h = min(img_h, crop_y + mask.size[1]) - src_y
            
            if src_w > 0 and src_h > 0:
                chunk = original_image.crop((src_x, src_y, src_x + src_w, src_y + src_h))
                piece_image.paste(chunk, (src_x - crop_x, src_y - crop_y))
            
            piece_image.putalpha(mask)
            piece_image.save(os.path.join(pieces_dir, f"piece_{r}_{c}.png"))

    # Zip the folder
    zip_path = os.path.join(session_dir, "puzzle_pieces.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, _, files in os.walk(pieces_dir):
            for file in files:
                zipf.write(os.path.join(root, file), file)
    
    return zip_path

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    
    file = request.files['image']
    pieces = int(request.form.get('pieces', 100))
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    session_id = str(uuid.uuid4())
    img_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_{file.filename}")
    file.save(img_path)
    
    try:
        zip_path = process_image(img_path, pieces, session_id)
        # Clean up original upload
        os.remove(img_path)
        
        # Return the path to the zip file relative to static
        relative_zip_path = os.path.relpath(zip_path, 'static')
        # We return a URL that the frontend can download
        return jsonify({'download_url': f"/static/{relative_zip_path}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)