import os
import math
import uuid
import zipfile
import random
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

def draw_cut_lines_on_full_image(img_path, rows, cols, output_path, h_edges, v_edges):
    """
    Draws the full grid of rectangular cut lines onto the original image.
    This creates the "Master Sheet" for printing.
    """
    with Image.open(img_path).convert("RGBA") as img:
        draw = ImageDraw.Draw(img)
        width, height = img.size
        piece_w = width / cols
        piece_h = height / rows

        # Function to draw a line with a border (contrast)
        def draw_contrasted_line(pts):
            draw.line(pts, fill="black", width=4)
            draw.line(pts, fill="white", width=2)

        # 1. Draw Vertical Edges (between cols)
        for r in range(rows):
            for c in range(1, cols):
                x_base = c * piece_w
                y_start = r * piece_h
                y_end = (r + 1) * piece_h
                
                # Check the edge shape (defined in v_edges[r][c-1])
                shape = v_edges[r][c-1] # 1 or -1
                
                # Straight line logic
                p_start = (x_base, y_start)
                p_end = (x_base, y_end)
                
                # Get tab points
                tab_pts = get_square_tab_points(piece_h, is_tab=(shape == 1))
                
                # Convert tab points to global coordinates
                # For vertical edge, we move down Y, and "tab" moves in X
                poly_pts = [p_start]
                for px, py in tab_pts:
                    # px moves down the edge (Y), py moves out (X)
                    poly_pts.append((x_base + py, y_start + px))
                poly_pts.append(p_end)
                
                draw_contrasted_line(poly_pts)

        # 2. Draw Horizontal Edges (between rows)
        for r in range(1, rows):
            for c in range(cols):
                y_base = r * piece_h
                x_start = c * piece_w
                x_end = (c + 1) * piece_w
                
                shape = h_edges[r-1][c]
                
                p_start = (x_start, y_base)
                p_end = (x_end, y_base)
                
                tab_pts = get_square_tab_points(piece_w, is_tab=(shape == 1))
                
                poly_pts = [p_start]
                for px, py in tab_pts:
                    poly_pts.append((x_start + px, y_base + py))
                poly_pts.append(p_end)
                
                draw_contrasted_line(poly_pts)

        img.save(output_path)
        return output_path

def process_image(image_path, num_pieces, session_id):
    original_image = Image.open(image_path).convert("RGBA")
    img_w, img_h = original_image.size
    rows, cols = calculate_grid(img_w, img_h, num_pieces)
    piece_w, piece_h = img_w / cols, img_h / rows
    
    session_dir = os.path.join(OUTPUT_FOLDER, session_id)
    pieces_dir = os.path.join(session_dir, "pieces")
    os.makedirs(pieces_dir, exist_ok=True)

    # Define random interlocking pattern
    # 1=Tab (Right/Down), -1=Hole (Left/Up)
    # Be careful: a '1' on the right of piece A must meet a '-1' on the left of piece B
    # BUT, to simplify logic:
    # v_edges[r][c] represents the boundary between col c and col c+1
    # If v_edges is 1: Left piece has Tab, Right piece has Hole
    
    v_edges = [[random.choice([1, -1]) for _ in range(cols - 1)] for _ in range(rows)]
    h_edges = [[random.choice([1, -1]) for _ in range(cols)] for _ in range(rows - 1)]

    # 1. Generate Individual Pieces
    for r in range(rows):
        for c in range(cols):
            # Determine Edges
            # TOP
            if r == 0: top = 0
            else: top = -h_edges[r-1][c] # Invert the shape of the row above
            
            # RIGHT
            if c == cols - 1: right = 0
            else: right = v_edges[r][c]
            
            # BOTTOM
            if r == rows - 1: bottom = 0
            else: bottom = h_edges[r][c]
            
            # LEFT
            if c == 0: left = 0
            else: left = -v_edges[r][c-1] # Invert shape of col to left

            # Generate Mask
            mask, padding, _ = create_piece_mask(piece_w, piece_h, (top, right, bottom, left))
            
            # Cut from Original
            crop_x, crop_y = int(c * piece_w - padding), int(r * piece_h - padding)
            
            piece_img = Image.new('RGBA', mask.size, (0, 0, 0, 0))
            src_x, src_y = max(0, crop_x), max(0, crop_y)
            src_w = min(img_w, crop_x + mask.size[0]) - src_x
            src_h = min(img_h, crop_y + mask.size[1]) - src_y
            
            if src_w > 0 and src_h > 0:
                chunk = original_image.crop((src_x, src_y, src_x + src_w, src_y + src_h))
                piece_img.paste(chunk, (src_x - crop_x, src_y - crop_y))
            
            piece_img.putalpha(mask)
            piece_img.save(os.path.join(pieces_dir, f"piece_{r}_{c}.png"))

    # 2. Generate "Master Cut Sheet" (Full image with lines)
    guide_filename = "FULL_IMAGE_WITH_CUT_LINES.png"
    guide_path = os.path.join(session_dir, guide_filename)
    draw_cut_lines_on_full_image(image_path, rows, cols, guide_path, h_edges, v_edges)

    # 3. Zip
    zip_path = os.path.join(session_dir, "puzzle_pack.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        zipf.write(guide_path, guide_filename)
        for root, _, files in os.walk(pieces_dir):
            for file in files:
                zipf.write(os.path.join(root, file), os.path.join("individual_pieces", file))
    
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