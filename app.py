import os
import math
import uuid
import zipfile
from flask import Flask, render_template, request, jsonify
from PIL import Image, ImageDraw

app = Flask(__name__)

# CONFIGURATION
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'static/generated'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

def calculate_grid(width, height, num_pieces):
    """Calculates rows and columns to keep pieces roughly square."""
    aspect_ratio = width / height
    rows = int(math.sqrt(num_pieces / aspect_ratio))
    cols = int(num_pieces / max(rows, 1))
    if rows == 0: rows = 1
    if cols == 0: cols = 1
    return rows, cols

def create_print_guide(image_path, rows, cols, output_path):
    """Creates a single image with cut lines drawn on it."""
    with Image.open(image_path).convert("RGBA") as img:
        draw = ImageDraw.Draw(img)
        width, height = img.size
        piece_w = width / cols
        piece_h = height / rows

        # Draw Vertical Lines
        for c in range(1, cols):
            x = int(c * piece_w)
            # Draw a thick white line with a thin black line inside for visibility on any color
            draw.line([(x, 0), (x, height)], fill="white", width=3)
            draw.line([(x, 0), (x, height)], fill="black", width=1)

        # Draw Horizontal Lines
        for r in range(1, rows):
            y = int(r * piece_h)
            draw.line([(0, y), (width, y)], fill="white", width=3)
            draw.line([(0, y), (width, y)], fill="black", width=1)

        img.save(output_path)
        return output_path

def process_image(image_path, num_pieces, session_id):
    original_image = Image.open(image_path).convert("RGBA")
    img_w, img_h = original_image.size
    rows, cols = calculate_grid(img_w, img_h, num_pieces)
    piece_w = img_w / cols
    piece_h = img_h / rows
    
    session_dir = os.path.join(OUTPUT_FOLDER, session_id)
    pieces_dir = os.path.join(session_dir, "pieces")
    os.makedirs(pieces_dir, exist_ok=True)

    # 1. Generate Individual Square Pieces
    for r in range(rows):
        for c in range(cols):
            # Calculate exact coordinates
            left = c * piece_w
            upper = r * piece_h
            right = (c + 1) * piece_w
            lower = (r + 1) * piece_h
            
            # Crop
            piece = original_image.crop((left, upper, right, lower))
            
            # Save
            piece.save(os.path.join(pieces_dir, f"piece_{r}_{c}.png"))

    # 2. Generate the "Print Guide" (The image with lines)
    guide_filename = "print_guide_with_lines.png"
    guide_path = os.path.join(session_dir, guide_filename)
    create_print_guide(image_path, rows, cols, guide_path)

    # 3. Zip everything (Pieces folder + Print Guide)
    zip_path = os.path.join(session_dir, "puzzle_pack.zip")
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        # Add the guide image
        zipf.write(guide_path, guide_filename)
        # Add the pieces
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
    pieces = int(request.form.get('pieces', 20)) # Default to fewer pieces for square cut
    
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    session_id = str(uuid.uuid4())
    img_path = os.path.join(UPLOAD_FOLDER, f"{session_id}_{file.filename}")
    file.save(img_path)
    
    try:
        zip_path = process_image(img_path, pieces, session_id)
        # Clean up original upload
        os.remove(img_path)
        
        relative_zip_path = os.path.relpath(zip_path, 'static')
        return jsonify({'download_url': f"/static/{relative_zip_path}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)