import os
import math
import uuid
import zipfile
import random
import gc
from flask import Flask, render_template, request, jsonify
from PIL import Image, ImageDraw

app = Flask(__name__)

# CONFIGURATION
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'static/generated'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def calculate_grid(width, height, num_pieces):
    aspect_ratio = width / height
    rows = int(math.sqrt(num_pieces / aspect_ratio))
    cols = int(num_pieces / max(rows, 1))
    return max(1, rows), max(1, cols)

def get_square_tab_points(length, is_tab=True):
    tab_width = length * 0.3
    tab_height = length * 0.2
    x1 = (length - tab_width) / 2
    x2 = x1 + tab_width
    y_offset = tab_height if is_tab else -tab_height
    return [(x1, 0), (x1, y_offset), (x2, y_offset), (x2, 0)]

def create_piece_mask(piece_w, piece_h, edge_shapes):
    padding = max(piece_w, piece_h) * 0.3
    mask_w, mask_h = int(piece_w + padding * 2), int(piece_h + padding * 2)
    mask = Image.new('L', (mask_w, mask_h), 0)
    draw = ImageDraw.Draw(mask)
    tl, tr, br, bl = (padding, padding), (padding + piece_w, padding), (padding + piece_w, padding + piece_h), (padding, padding + piece_h)
    points = [tl]

    # Top
    if edge_shapes[0] != 0:
        for px, py in get_square_tab_points(piece_w, (edge_shapes[0] == 1)):
            points.append((tl[0] + px, tl[1] - py))
    points.append(tr)
    # Right
    if edge_shapes[1] != 0:
        for px, py in get_square_tab_points(piece_h, (edge_shapes[1] == 1)):
            points.append((tr[0] + py, tr[1] + px))
    points.append(br)
    # Bottom
    if edge_shapes[2] != 0:
        for px, py in get_square_tab_points(piece_w, (edge_shapes[2] == 1)):
            points.append((bl[0] + (piece_w - px), bl[1] + py))
    points.append(bl)
    # Left
    if edge_shapes[3] != 0:
        for px, py in get_square_tab_points(piece_h, (edge_shapes[3] == 1)):
            points.append((tl[0] - py, tl[1] + (piece_h - px)))

    draw.polygon(points, fill=255)
    return mask, padding, points

def draw_cut_lines_on_full_image(img_data, rows, cols, output_path, h_edges, v_edges, margin_px):
    with img_data.copy().convert("RGB") as img:
        draw = ImageDraw.Draw(img)
        width, height = img.size 
        inner_w, inner_h = width - (2 * margin_px), height - (2 * margin_px)
        piece_w, piece_h = inner_w / cols, inner_h / rows

        def draw_contrasted_line(pts):
            draw.line(pts, fill=(0, 0, 0), width=3)
            draw.line(pts, fill=(255, 255, 255), width=1)

        # Draw Vertical internal cuts
        for r in range(rows):
            for c in range(1, cols):
                x_base, y_start, y_end = margin_px + (c * piece_w), margin_px + (r * piece_h), margin_px + ((r + 1) * piece_h)
                tab_pts = get_square_tab_points(piece_h, (v_edges[r][c-1] == 1))
                pts = [(x_base, y_start)] + [(x_base + py, y_start + px) for px, py in tab_pts] + [(x_base, y_end)]
                draw_contrasted_line(pts)

        # Draw Horizontal internal cuts
        for r in range(1, rows):
            for c in range(cols):
                y_base, x_start, x_end = margin_px + (r * piece_h), margin_px + (c * piece_w), margin_px + ((c + 1) * piece_w)
                tab_pts = get_square_tab_points(piece_w, (h_edges[r-1][c] == 1))
                pts = [(x_start, y_base)] + [(x_start + px, y_base + py) for px, py in tab_pts] + [(x_end, y_base)]
                draw_contrasted_line(pts)

        # Draw the Outer Frame Box LAST (to keep it clean)
        draw.rectangle([margin_px, margin_px, width - margin_px, height - margin_px], outline=(0, 0, 0), width=3)

        img.save(output_path, "JPEG", quality=85)
        return output_path

def process_image(image_path, num_pieces, session_id):
    with Image.open(image_path).convert("RGBA") as original_full:
        MAX_RES = 1000
        if max(original_full.size) > MAX_RES:
            original_full.thumbnail((MAX_RES, MAX_RES), Image.Resampling.LANCZOS)
        img_w, img_h = original_full.size
        margin_px = int(min(img_w, img_h) * 0.05)
        inner_w, inner_h = img_w - (2 * margin_px), img_h - (2 * margin_px)
        rows, cols = calculate_grid(inner_w, inner_h, num_pieces)
        piece_w, piece_h = inner_w / cols, inner_h / rows
        img_data = original_full.copy()

    session_dir = os.path.join(OUTPUT_FOLDER, session_id)
    pieces_dir = os.path.join(session_dir, "pieces")
    os.makedirs(pieces_dir, exist_ok=True)

    v_edges = [[random.choice([1, -1]) for _ in range(cols - 1)] for _ in range(rows)]
    h_edges = [[random.choice([1, -1]) for _ in range(cols)] for _ in range(rows - 1)]

    guide_path = os.path.join(session_dir, "PRINT_THIS_GUIDE.jpg")
    draw_cut_lines_on_full_image(img_data, rows, cols, guide_path, h_edges, v_edges, margin_px)

    for r in range(rows):
        for c in range(cols):
            edges = (0 if r==0 else -h_edges[r-1][c], 0 if c==cols-1 else v_edges[r][c], 0 if r==rows-1 else h_edges[r][c], 0 if c==0 else -v_edges[r][c-1])
            mask, padding, _ = create_piece_mask(piece_w, piece_h, edges)
            crop_x, crop_y = int(margin_px + (c * piece_w) - padding), int(margin_px + (r * piece_h) - padding)
            with Image.new('RGBA', mask.size, (0, 0, 0, 0)) as piece_img:
                src_x, src_y = max(0, crop_x), max(0, crop_y)
                src_w, src_h = min(img_w, crop_x + mask.size[0]) - src_x, min(img_h, crop_y + mask.size[1]) - src_y
                if src_w > 0 and src_h > 0:
                    chunk = img_data.crop((src_x, src_y, src_x + src_w, src_y + src_h))
                    piece_img.paste(chunk, (src_x - crop_x, src_y - crop_y))
                    chunk.close()
                piece_img.putalpha(mask)
                piece_img.save(os.path.join(pieces_dir, f"piece_{r}_{c}.png"), compress_level=1)
        gc.collect()

    zip_path = os.path.join(session_dir, "puzzle_pack.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        zipf.write(guide_path, "PRINT_THIS_GUIDE.jpg")
        for root, _, files in os.walk(pieces_dir):
            for file in files:
                zipf.write(os.path.join(root, file), os.path.join("individual_pieces", file))
    
    img_data.close()
    return zip_path

@app.route('/')
def index(): return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate():
    if 'image' not in request.files: return jsonify({'error': 'No image'}), 400
    file = request.files['image']
    try: pieces = int(request.form.get('pieces', 25))
    except: pieces = 25
    session_id = str(uuid.uuid4())
    img_path = os.path.join(UPLOAD_FOLDER, f"{session_id}.png")
    file.save(img_path)
    try:
        zip_path = process_image(img_path, pieces, session_id)
        os.remove(img_path)
        return jsonify({'download_url': f"/static/generated/{session_id}/puzzle_pack.zip"})
    except Exception as e: return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
