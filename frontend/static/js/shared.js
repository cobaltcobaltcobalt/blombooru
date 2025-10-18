class SharedViewer extends MediaViewerBase {
    constructor(shareUuid) {
        super();
        this.shareUuid = shareUuid;
        
        this.init();
    }

    init() {
        this.initFullscreenViewer();    
        this.loadSharedContent();
        this.setupAgeVerification();
    }

    async loadSharedContent() {
        try {
            const response = await fetch(`/api/shared/${this.shareUuid}`);
            const data = await response.json();
            
            if (data.type === 'media') {
                this.currentMedia = data.data;
                this.renderSharedMedia(this.currentMedia);
                
                // Check if content is explicit and show age verification
                if (this.currentMedia.rating === 'explicit') {
                    this.showAgeVerification();
                }
            }
        } catch (error) {
            console.error('Error loading shared content:', error);
            this.showErrorMessage();
        }
    }

    showErrorMessage() {
        const container = this.el('shared-content');
        container.innerHTML = `
            <div class="text-center py-16">
                <h2 class="text-lg font-bold mb-2">Content Not Found</h2>
                <p class="text-xs text-secondary">This shared link is invalid or has been removed.</p>
            </div>
        `;
    }

    setupAgeVerification() {
        const yesBtn = this.el('age-confirm-yes');
        const noBtn = this.el('age-confirm-no');
        
        if (yesBtn) {
            yesBtn.addEventListener('click', () => this.confirmAge());
        }
        
        if (noBtn) {
            noBtn.addEventListener('click', () => this.denyAge());
        }
    }

    showAgeVerification() {
        const overlay = this.el('age-verification-overlay');
        const mediaContainer = document.querySelector('.lg\\:col-span-3 > div');
        
        // Blur the media
        if (mediaContainer) {
            mediaContainer.classList.add('media-blurred');
        }
        
        // Show overlay
        overlay.style.display = 'flex';
    }

    confirmAge() {
        const overlay = this.el('age-verification-overlay');
        const mediaContainer = document.querySelector('.lg\\:col-span-3 > div');
        
        overlay.style.display = 'none';
        if (mediaContainer) {
            mediaContainer.classList.remove('media-blurred');
        }
    }

    denyAge() {
        window.close();
        setTimeout(() => {
            window.location.href = 'about:blank';
        }, 100);
    }

    renderSharedMedia(media) {
        const container = this.el('shared-content');

        container.innerHTML = `
            <div class="grid grid-cols-1 lg:grid-cols-4 gap-4">
                <div class="lg:col-span-3">
                    <div class="surface p-4 border text-center">
                        ${this.getMediaHTML(media)}
                    </div>
                </div>

                <div class="lg:col-span-1">
                    <div class="surface p-3 border mb-4">
                        <h3 class="text-sm font-bold mb-3 pb-2 border-b">Information</h3>
                        <div id="media-info-content" class="text-xs"></div>
                    </div>

                    <div class="surface p-3 border mb-4">
                        <h3 class="text-sm font-bold mb-3 pb-2 border-b">Tags</h3>
                        <div id="tags-container"></div>
                    </div>

                    <div id="ai-metadata-section" style="display: none;" class="surface p-3 border mb-4">
                        <h3 class="text-sm font-bold mb-3 pb-2 border-b">AI Generation Data</h3>
                        <div id="ai-metadata-content" class="text-xs"></div>
                    </div>

                    <div class="surface p-3 border">
                        <h3 class="text-sm font-bold mb-3 pb-2 border-b">Actions</h3>
                        <div class="space-y-2">
                            <a id="download-btn" href="/api/shared/${this.shareUuid}/file" download="${media.filename}" 
                               class="block w-full px-3 py-2 surface-light hover:surface-light text text-center text-xs">
                                Download
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Render the data into the containers
        this.renderInfo(media, { isShared: true });
        this.renderTags(media, { clickable: false });
        this.renderAIMetadata(media, { showControls: false });
        
        // Add click listener for fullscreen (only for images/GIFs)
        if (media.file_type !== 'video') {
            this.setupImageClickHandler();
        }
    }

    getMediaHTML(media) {
        if (media.file_type === 'video') {
            return `
                <video controls loop style="max-width: 100%; max-height: 80vh; margin: 0 auto;">
                    <source src="/api/shared/${this.shareUuid}/file" type="${media.mime_type}">
                </video>
            `;
        } else {
            return `
                <img src="/api/shared/${this.shareUuid}/file" alt="${media.filename}" 
                     id="shared-media-image" 
                     style="max-width: 100%; max-height: 80vh; margin: 0 auto; cursor: pointer;">
            `;
        }
    }

    setupImageClickHandler() {
        setTimeout(() => {
            const sharedImage = this.el('shared-media-image');
            if (sharedImage && this.fullscreenViewer) {
                sharedImage.addEventListener('click', () => {
                    this.fullscreenViewer.open(`/api/shared/${this.shareUuid}/file`);
                });
            }
        }, 0);
    }
}
