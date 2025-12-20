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
    """Calculates rows and cols to keep pieces roughly square."""
    aspect_ratio = width / height
    rows = int(math.sqrt(num_pieces / aspect_ratio))
    cols = int(num_pieces / max(rows, 1))
    if rows == 0: rows = 1
    if cols == 0: cols = 1
    return rows, cols

def get_square_tab_points(length, is_tab=True):
    """
    Generates points for a rectangular tab.
    Returns list of (x, y) coordinates relative to the edge start (0,0).
    """
    # Tab dimensions (customizable)
    tab_width = length * 0.3    # Width of the tab neck
    tab_height = length * 0.2   # How far it sticks out
    
    # Calculate key X positions
    x1 = (length - tab_width) / 2
    x2 = x1 + tab_width
    
    # Y direction depends on tab vs hole
    y_offset = tab_height if is_tab else -tab_height
    
    # Define the 4 points of a square bump
    # 1. Start of tab neck
    p1 = (x1, 0)
    # 2. Corner out
    p2 = (x1, y_offset)
    # 3. Corner over
    p3 = (x2, y_offset)
    # 4. Return to edge
    p4 = (x2, 0)
    
    return [p1, p2, p3, p4]

def create_piece_mask(piece_w, piece_h, edge_shapes):
    """
    Creates the mask for a single piece.
    edge_shapes: (top, right, bottom, left). 0=Flat, 1=Tab, -1=Hole
    """
    # Padding to accommodate tabs sticking out
    padding = max(piece_w, piece_h) * 0.3
    mask_w = int(piece_w + padding * 2)
    mask_h = int(piece_h + padding * 2)
    
    mask = Image.new('L', (mask_w, mask_h), 0)
    draw = ImageDraw.Draw(mask)
    
    # Internal box corners (where the "straight" edges would be)
    tl = (padding, padding)
    tr = (padding + piece_w, padding)
    br = (padding + piece_w, padding + piece_h)
    bl = (padding, padding + piece_h)
    
    points = [tl]
    
    # --- Top Edge ---
    if edge_shapes[0] == 0:
        points.append(tr)
    else:
        tab_pts = get_square_tab_points(piece_w, is_tab=(edge_shapes[0] == 1))
        # Add points relative to TL
        for px, py in tab_pts:
            points.append((tl[0] + px, tl[1] - py)) # Subtract Y because up is negative
        points.append(tr)

    # --- Right Edge ---
    if edge_shapes[1] == 0:
        points.append(br)
    else:
        tab_pts = get_square_tab_points(piece_h, is_tab=(edge_shapes[1] == 1))
        # Rotate logic: X becomes Y, Y becomes -X (relative to edge)
        for px, py in tab_pts:
            points.append((tr[0] + py, tr[1] + px))
        points.append(br)

    # --- Bottom Edge ---
    if edge_shapes[2] == 0:
        points.append(bl)
    else:
        tab_pts = get_square_tab_points(piece_w, is_tab=(edge_shapes[2] == 1))
        # Bottom edge runs Right to Left
        for px, py in tab_pts:
             # Invert X logic because we are going backwards
            points.append((bl[0] + (piece_w - px), bl[1] + py))
        points.append(bl)

    # --- Left Edge ---
    if edge_shapes[3] != 0:
        tab_pts = get_square_tab_points(piece_h, is_tab=(edge_shapes[3] == 1))
        # Left edge runs Bottom to Top
        for px, py in tab_pts:
            points.append((tl[0] - py, tl[1] + (piece_h - px)))
            
    # Auto-close loop
    draw.polygon(points, fill=255)
    return mask, padding, points

def draw_cut_lines_on_full_image(img_data, rows, cols, output_path, h_edges, v_edges, margin_px):
    """
    Draws the full grid inside an outer border frame with a visual overlay.
    """
    # We use RGBA here temporarily to allow for a transparent overlay effect
    with img_data.copy().convert("RGBA") as img:
        # Create a separate layer for the frame overlay
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)

        # Draw a semi-transparent white frame (180 = clearly visible but shows the photo)
        # Change 180 to 255 if you want it to be SOLID WHITE
        frame_color = (255, 255, 255, 50)
        width, height = img.size
        
        # --- NEW: VISUAL BORDER DRAWING ---
        # This draws a semi-transparent white frame over the margin area
        # Top margin
        draw_overlay.rectangle([0, 0, width, margin_px], fill=frame_color)
        # Bottom margin
        draw_overlay.rectangle([0, height - margin_px, width, height], fill=frame_color)
        # Left margin
        draw_overlay.rectangle([0, margin_px, margin_px, height - margin_px], fill=frame_color)
        # Right margin
        draw_overlay.rectangle([width - margin_px, margin_px, width, height - margin_px], fill=frame_color)
        
        # Alpha composite the overlay onto the image
        img = Image.alpha_composite(img, overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # Draw a sharp black line exactly where the frame ends and puzzle begins
        draw.rectangle(
            [margin_px, margin_px, width - margin_px, height - margin_px], 
            outline=(0, 0, 0), width=2
        )
        
        # Calculate the "Active Area" inside the border
        inner_w = width - (2 * margin_px)
        inner_h = height - (2 * margin_px)
        piece_w = inner_w / cols
        piece_h = inner_h / rows

        def draw_contrasted_line(pts):
            draw.line(pts, fill=(0, 0, 0), width=3)
            draw.line(pts, fill=(255, 255, 255), width=1)

        # 1. Draw Vertical Edges
        for r in range(rows):
            for c in range(1, cols):
                x_base = margin_px + (c * piece_w)
                y_start = margin_px + (r * piece_h)
                y_end = margin_px + ((r + 1) * piece_h)
                shape = v_edges[r][c-1]
                tab_pts = get_square_tab_points(piece_h, is_tab=(shape == 1))
                poly_pts = [(x_base, y_start)]
                for px, py in tab_pts:
                    poly_pts.append((x_base + py, y_start + px))
                poly_pts.append((x_base, y_end))
                draw_contrasted_line(poly_pts)

        # 2. Draw Horizontal Edges
        for r in range(1, rows):
            for c in range(cols):
                y_base = margin_px + (r * piece_h)
                x_start = margin_px + (c * piece_w)
                x_end = margin_px + ((c + 1) * piece_w)
                shape = h_edges[r-1][c]
                tab_pts = get_square_tab_points(piece_w, is_tab=(shape == 1))
                poly_pts = [(x_start, y_base)]
                for px, py in tab_pts:
                    poly_pts.append((x_start + px, y_base + py))
                poly_pts.append((x_end, y_base))
                draw_contrasted_line(poly_pts)

        # 3. Draw a crisp inner border line
        draw.rectangle(
            [margin_px, margin_px, width - margin_px, height - margin_px], 
            outline=(0, 0, 0), width=2
        )

        img.save(output_path, "JPEG", quality=85)
        return output_path

def process_image(image_path, num_pieces, session_id):
    with Image.open(image_path).convert("RGBA") as original_full:
        MAX_RES = 1000
        if max(original_full.size) > MAX_RES:
            original_full.thumbnail((MAX_RES, MAX_RES), Image.Resampling.LANCZOS)
        
        img_w, img_h = original_full.size
        
        # Set border to 5% of the smallest dimension
        margin_px = int(min(img_w, img_h) * 0.05)
        
        inner_w = img_w - (2 * margin_px)
        inner_h = img_h - (2 * margin_px)
        
        rows, cols = calculate_grid(inner_w, inner_h, num_pieces)
        piece_w, piece_h = inner_w / cols, inner_h / rows
        
        img_data = original_full.copy()

    session_dir = os.path.join(OUTPUT_FOLDER, session_id)
    pieces_dir = os.path.join(session_dir, "pieces")
    os.makedirs(pieces_dir, exist_ok=True)

    v_edges = [[random.choice([1, -1]) for _ in range(cols - 1)] for _ in range(rows)]
    h_edges = [[random.choice([1, -1]) for _ in range(cols)] for _ in range(rows - 1)]

    # --- STEP 1: GENERATE FRAME ---
    guide_path = os.path.join(session_dir, "PRINT_THIS_GUIDE.jpg")
    draw_cut_lines_on_full_image(img_data, rows, cols, guide_path, h_edges, v_edges, margin_px)

    # --- STEP 2: GENERATE PIECES (Offset by margin) ---
    for r in range(rows):
        for c in range(cols):
            # Same edge logic as before
            top = 0 if r == 0 else -h_edges[r-1][c]
            right = 0 if c == cols - 1 else v_edges[r][c]
            bottom = 0 if r == rows - 1 else h_edges[r][c]
            left = 0 if c == 0 else -v_edges[r][c-1]

            mask, padding, _ = create_piece_mask(piece_w, piece_h, (top, right, bottom, left))
            
            # The crop is now relative to the inner area (base + margin)
            crop_x = int(margin_px + (c * piece_w) - padding)
            crop_y = int(margin_px + (r * piece_h) - padding)
            
            with Image.new('RGBA', mask.size, (0, 0, 0, 0)) as piece_img:
                src_x, src_y = max(0, crop_x), max(0, crop_y)
                src_w = min(img_w, crop_x + mask.size[0]) - src_x
                src_h = min(img_h, crop_y + mask.size[1]) - src_y
                
                if src_w > 0 and src_h > 0:
                    chunk = img_data.crop((src_x, src_y, src_x + src_w, src_y + src_h))
                    piece_img.paste(chunk, (src_x - crop_x, src_y - crop_y))
                    chunk.close()
                
                piece_img.putalpha(mask)
                piece_img.save(os.path.join(pieces_dir, f"piece_{r}_{c}.png"), compress_level=1)
            
            if (r * cols + c) % 10 == 0:
                gc.collect()

    # --- STEP 3: ZIP ---
    zip_path = os.path.join(session_dir, "puzzle_pack.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        zipf.write(guide_path, "PRINT_THIS_GUIDE.jpg")
        for root, _, files in os.walk(pieces_dir):
            for file in files:
                zipf.write(os.path.join(root, file), os.path.join("individual_pieces", file))
    
    img_data.close()
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
    try:
        pieces = int(request.form.get('pieces', 25))
    except:
        pieces = 25

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    session_id = str(uuid.uuid4())
    img_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_{file.filename}")
    file.save(img_path)
    
    try:
        zip_path = process_image(img_path, pieces, session_id)
        os.remove(img_path)
        
        relative_zip_path = os.path.relpath(zip_path, 'static')
        return jsonify({'download_url': f"/static/{relative_zip_path}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
