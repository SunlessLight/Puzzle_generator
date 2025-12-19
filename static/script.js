const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('imageInput');
const preview = document.getElementById('preview');
const form = document.getElementById('puzzleForm');
const loading = document.getElementById('loading');
const result = document.getElementById('result');
const downloadLink = document.getElementById('downloadLink');
const resetBtn = document.getElementById('resetBtn');

// Click to upload
dropZone.addEventListener('click', () => fileInput.click());

// Drag & Drop visual effects
dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dragover');
});
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));

// Handle File Drop
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dragover');
    if (e.dataTransfer.files.length) {
        fileInput.files = e.dataTransfer.files;
        showPreview(fileInput.files[0]);
    }
});

// Handle File Selection via click
fileInput.addEventListener('change', () => {
    if (fileInput.files.length) showPreview(fileInput.files[0]);
});

function showPreview(file) {
    const reader = new FileReader();
    reader.onload = (e) => {
        preview.src = e.target.result;
        preview.style.display = 'block';
        dropZone.querySelector('p').style.display = 'none';
    };
    reader.readAsDataURL(file);
}

// Submit Form
form.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return alert("Please select an image first.");

    const formData = new FormData(form);

    // UI Updates
    form.classList.add('hidden');
    loading.classList.remove('hidden');

    try {
        const response = await fetch('/generate', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            downloadLink.href = data.download_url;
            loading.classList.add('hidden');
            result.classList.remove('hidden');
        } else {
            alert("Error: " + data.error);
            resetUI();
        }
    } catch (error) {
        console.error(error);
        alert("An error occurred.");
        resetUI();
    }
});

resetBtn.addEventListener('click', resetUI);

function resetUI() {
    result.classList.add('hidden');
    loading.classList.add('hidden');
    form.classList.remove('hidden');
    form.reset();
    preview.style.display = 'none';
    dropZone.querySelector('p').style.display = 'block';
}