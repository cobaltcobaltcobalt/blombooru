class FullscreenImageViewer {
    constructor() {
        this.overlay = null;
        this.image = null;
        this.wrapper = null;
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.isDragging = false;
        this.startX = 0;
        this.startY = 0;
        this.lastX = 0;
        this.lastY = 0;

        this.init();
    }

    init() {
        this.overlay = document.getElementById('fullscreen-overlay');
        this.image = document.getElementById('fullscreen-image');
        this.wrapper = document.getElementById('fullscreen-image-wrapper');

        this.image.addEventListener('dragstart', (e) => {
            e.preventDefault();
            return false;
        });

        this.image.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            return false;
        });

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.overlay.classList.contains('active')) {
                this.close();
            }
        });

        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay) {
                this.close();
            }
        });

        this.wrapper.addEventListener('click', (e) => {
            if (e.target === this.wrapper) {
                this.close();
            }
            e.stopPropagation();
        });

        this.wrapper.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? 0.9 : 1.1;
            this.zoom(delta, e.clientX, e.clientY);
        }, { passive: false });

        this.setupMouseEvents();
        this.setupTouchEvents();
    }

    setupMouseEvents() {
        this.image.addEventListener('mousedown', (e) => {
            e.preventDefault();
            if (this.scale > 1) {
                this.startDrag(e.clientX, e.clientY);
            }
        });

        document.addEventListener('mousemove', (e) => {
            if (this.isDragging) {
                this.drag(e.clientX, e.clientY);
            }
        });

        document.addEventListener('mouseup', () => {
            this.stopDrag();
        });
    }

    setupTouchEvents() {
        let touchDistance = 0;

        this.image.addEventListener('touchstart', (e) => {
            if (e.touches.length === 1) {
                if (this.scale > 1) {
                    this.startDrag(e.touches[0].clientX, e.touches[0].clientY);
                }
            } else if (e.touches.length === 2) {
                e.preventDefault();
                const dx = e.touches[0].clientX - e.touches[1].clientX;
                const dy = e.touches[0].clientY - e.touches[1].clientY;
                touchDistance = Math.sqrt(dx * dx + dy * dy);
            }
        }, { passive: false });

        this.image.addEventListener('touchmove', (e) => {
            if (e.touches.length === 1 && this.isDragging) {
                e.preventDefault();
                this.drag(e.touches[0].clientX, e.touches[0].clientY);
            } else if (e.touches.length === 2) {
                e.preventDefault();
                const dx = e.touches[0].clientX - e.touches[1].clientX;
                const dy = e.touches[0].clientY - e.touches[1].clientY;
                const newDistance = Math.sqrt(dx * dx + dy * dy);

                if (touchDistance > 0) {
                    const delta = newDistance / touchDistance;
                    const centerX = (e.touches[0].clientX + e.touches[1].clientX) / 2;
                    const centerY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
                    this.zoom(delta, centerX, centerY);
                }

                touchDistance = newDistance;
            }
        }, { passive: false });

        this.image.addEventListener('touchend', (e) => {
            if (e.touches.length === 0) {
                this.stopDrag();
                touchDistance = 0;
            }
        });
    }

    open(imageSrc) {
        this.image.src = imageSrc;
        this.overlay.classList.add('active');
        this.reset();

        this.image.onload = () => {
            this.sizeImageToViewport();
        };

        document.body.style.overflow = 'hidden';
    }

    sizeImageToViewport() {
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const imageRatio = this.image.naturalWidth / this.image.naturalHeight;
        const viewportRatio = viewportWidth / viewportHeight;

        if (viewportRatio > imageRatio) {
            this.image.style.width = 'auto';
            this.image.style.height = '98vh';
        } else {
            this.image.style.width = '98vw';
            this.image.style.height = 'auto';
        }
    }

    close() {
        this.overlay.classList.remove('active');
        this.reset();
        document.body.style.overflow = '';
    }

    reset() {
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.updateTransform();
    }

    zoom(delta, centerX, centerY) {
        const oldScale = this.scale;
        this.scale *= delta;
        this.scale = Math.max(1, Math.min(10, this.scale));

        if (this.scale === 1) {
            this.translateX = 0;
            this.translateY = 0;
        } else {
            const rect = this.image.getBoundingClientRect();
            const x = centerX - rect.left - rect.width / 2;
            const y = centerY - rect.top - rect.height / 2;

            const scaleChange = this.scale / oldScale - 1;
            this.translateX -= x * scaleChange;
            this.translateY -= y * scaleChange;

            this.constrainPosition();
        }

        this.updateTransform();
        this.updateCursor();
    }

    startDrag(x, y) {
        this.isDragging = true;
        this.startX = x - this.translateX;
        this.startY = y - this.translateY;
        this.lastX = x;
        this.lastY = y;
        this.image.classList.add('dragging');
    }

    drag(x, y) {
        if (!this.isDragging) return;

        this.translateX = x - this.startX;
        this.translateY = y - this.startY;

        this.constrainPosition();
        this.updateTransform();
    }

    stopDrag() {
        this.isDragging = false;
        this.image.classList.remove('dragging');
    }

    constrainPosition() {
        const rect = this.image.getBoundingClientRect();
        const maxX = (rect.width * this.scale - rect.width) / 2;
        const maxY = (rect.height * this.scale - rect.height) / 2;

        this.translateX = Math.max(-maxX, Math.min(maxX, this.translateX));
        this.translateY = Math.max(-maxY, Math.min(maxY, this.translateY));
    }

    updateTransform() {
        this.image.style.transform = `translate(${this.translateX}px, ${this.translateY}px) scale(${this.scale})`;
    }

    updateCursor() {
        if (this.scale > 1) {
            this.image.classList.add('zoomed');
            this.overlay.style.cursor = 'default';
        } else {
            this.image.classList.remove('zoomed');
            this.overlay.style.cursor = 'zoom-out';
        }
    }
}

// Global function for expand/collapse functionality
window.toggleExpand = function(id) {
    const truncated = document.getElementById(id + '-truncated');
    const full = document.getElementById(id + '-full');

    if (full.style.display === 'none') {
        truncated.style.display = 'none';
        full.style.display = 'inline';
    } else {
        truncated.style.display = 'inline';
        full.style.display = 'none';
    }
};
