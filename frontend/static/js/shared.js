class SharedViewer {
    constructor(shareUuid) {
        this.shareUuid = shareUuid;
        this.currentMedia = null;
        this.fullscreenViewer = null;
        
        this.init();
    }

    init() {
        this.initFullscreenViewer();    
        this.loadSharedContent();
        this.setupAgeVerification();
    }

    el(id) {
        return document.getElementById(id);
    }

    initFullscreenViewer() {
        this.fullscreenViewer = new FullscreenMediaViewer();
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
        // Try to close the tab/window, or navigate to about:blank
        window.close();
        // If window.close() doesn't work (some browsers block it), navigate away
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
        this.renderInfo(media);
        this.renderTags(media);
        this.renderAIMetadata(media);
        
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

    renderInfo(media) {
        let infoHTML = `
            <div class="info-row"><span>Filename</span><strong>${media.filename}</strong></div>
            <div class="info-row"><span>Type</span><strong>${media.file_type}</strong></div>
            <div class="info-row"><span>Size</span><strong>${this.formatFileSize(media.file_size)}</strong></div>
            <div class="info-row"><span>Dimensions</span><strong>${media.width}x${media.height}</strong></div>
            <div class="info-row"><span>Rating</span><strong>${media.rating}</strong></div>
            <div class="info-row"><span>Uploaded</span><strong>${new Date(media.uploaded_at).toLocaleDateString()}</strong></div>
            ${media.duration ? `<div class="info-row"><span>Duration</span><strong>${this.formatDuration(media.duration)}</strong></div>` : ''}
        `;

        // Add source if it exists
        if (media.source) {
            infoHTML += `
                <div class="info-row">
                    <span>Source</span>
                    <strong>
                        <a href="${media.source}" target="_blank" rel="noopener noreferrer" 
                           class="text-primary hover:underline" style="word-break: break-all;">
                            ${media.source}
                        </a>
                    </strong>
                </div>
            `;
        }

        this.el('media-info-content').innerHTML = infoHTML;
    }

    renderTags(media) {
        const container = this.el('tags-container');
        const groups = { artist: [], character: [], copyright: [], general: [], meta: [] };
        
        (media.tags || []).forEach(tag => {
            if (groups[tag.category]) {
                groups[tag.category].push(tag);
            }
        });
        
        let html = '';
        Object.entries(groups).forEach(([category, tags]) => {
            if (!tags.length) return;
            
            tags.sort((a, b) => a.name.localeCompare(b.name));
            
            html += `
                <div class="tag-category">
                    <h4>${category}</h4>
                    <div class="tag-list">
                        ${tags.map(tag => 
                            `<span class="tag ${category} tag-text">${tag.name}</span>`
                        ).join('')}
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = html || '<p class="text-xs text-secondary">No tags</p>';
    }

    async renderAIMetadata(media) {
        const section = this.el('ai-metadata-section');
        const content = this.el('ai-metadata-content');

        try {
            // Fetch metadata from the file
            const res = await fetch(`/api/media/${media.id}/metadata`);
            if (!res.ok) {
                section.style.display = 'none';
                return;
            }

            const metadata = await res.json();
            const aiData = this.extractAIData(metadata);

            // If no AI data found, hide section
            if (!aiData || Object.keys(aiData).length === 0) {
                section.style.display = 'none';
                return;
            }

            // Generate and display HTML
            content.innerHTML = this.generateAIMetadataHTML(aiData);
            section.style.display = 'block';

            // Add event listeners to expandable text elements
            this.setupExpandableListeners();
        } catch (e) {
            console.error('Error rendering AI metadata:', e);
            section.style.display = 'none';
        }
    }

    extractAIData(metadata) {
        // Check for AI parameters in common fields
        if (metadata.parameters) {
            return typeof metadata.parameters === 'string' 
                ? JSON.parse(metadata.parameters) 
                : metadata.parameters;
        } else if (metadata.Parameters) {
            return typeof metadata.Parameters === 'string' 
                ? JSON.parse(metadata.Parameters) 
                : metadata.Parameters;
        } else if (metadata.prompt) {
            return typeof metadata.prompt === 'string' 
                ? JSON.parse(metadata.prompt) 
                : metadata.prompt;
        }
        return null;
    }

    generateAIMetadataHTML(aiData) {
        let html = '';

        Object.entries(aiData).forEach(([key, value]) => {
            const sectionTitle = this.formatKey(key);

            html += `<div class="ai-section mb-3">`;
            html += `<h4 class="text-xs font-bold text-[var(--primary-color)] mb-2">${sectionTitle}</h4>`;
            
            if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
                html += `<div class="ml-2">`;
                Object.entries(value).forEach(([subKey, subValue]) => {
                    html += `
                        <div class="ai-data-row">
                            <span class="text-secondary">${this.formatKey(subKey)}:</span>
                            <div class="text">${this.formatValue(subValue, true)}</div>
                        </div>
                    `;
                });
                html += `</div>`;
            } else {
                html += `<div class="text ml-2">${this.formatValue(value, true)}</div>`;
            }

            html += `</div>`;
        });

        return html;
    }

    setupExpandableListeners() {
        document.querySelectorAll('.expandable-text').forEach(container => {
            // Clone to remove existing listeners
            const newContainer = container.cloneNode(true);
            container.parentNode.replaceChild(newContainer, container);

            // Add click listener
            newContainer.addEventListener('click', function(e) {
                // Check if text is being selected
                const selection = window.getSelection();
                if (selection && selection.toString().length > 0) {
                    return;
                }

                const id = this.id.replace('-container', '');
                window.toggleExpand(id);
            });

            // Prevent double-click from selecting text and triggering expand
            newContainer.addEventListener('dblclick', function(e) {
                e.stopPropagation();
            });
        });
    }

    // Utility methods
    formatKey(key) {
        return key
            .replace(/_/g, ' ')
            .replace(/([A-Z])/g, ' $1')
            .trim()
            .replace(/\b\w/g, c => c.toUpperCase())
            .replace(/Cfgscale/g, 'CFG Scale')
            .replace(/Cfg Scale/g, 'CFG Scale')
            .replace(/Vae/g, 'VAE')
            .replace(/Aspectratio/g, 'Aspect Ratio')
            .replace(/Aspect Ratio/g, 'Aspect Ratio')
            .replace(/Automaticvae/g, 'Automatic VAE')
            .replace(/Automatic Vae/g, 'Automatic VAE')
            .replace(/Negativeprompt/g, 'Negative Prompt')
            .replace(/Negative Prompt/g, 'Negative Prompt');
    }

    formatValue(value, isExpandable = true) {
        if (typeof value === 'boolean') {
            return value ? 'Yes' : 'No';
        }
        
        if (typeof value === 'string') {
            const escaped = value.replace(/</g, '&lt;').replace(/>/g, '&gt;');

            if (isExpandable && escaped.length > 100) {
                const id = 'expand-' + Math.random().toString(36).substr(2, 9);
                return `
                    <div class="expandable-text" id="${id}-container" style="cursor: pointer; user-select: text;">
                        <span class="text-truncated" id="${id}-truncated">
                            ${escaped.substring(0, 100)}...<br>
                            <span class="expand-indicator" style="user-select: none;">[click to expand]</span>
                        </span>
                        <span class="text-full" id="${id}-full" style="display: none;">
                            ${escaped}<br>
                            <span class="expand-indicator" style="user-select: none;">[click to collapse]</span>
                        </span>
                    </div>
                `;
            }
            return escaped;
        }
        
        if (Array.isArray(value)) {
            return value.join(', ');
        }
        
        return String(value);
    }

    formatFileSize(bytes) {
        if (!bytes) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
    }

    formatDuration(seconds) {
        const minutes = Math.floor(seconds / 60);
        const secs = Math.floor(seconds % 60);
        return `${minutes}:${String(secs).padStart(2, '0')}`;
    }
}

// Global function for expand/collapse functionality
window.toggleExpand = function(id) {
    const truncated = document.getElementById(id + '-truncated');
    const full = document.getElementById(id + '-full');

    if (full && truncated) {
        if (full.style.display === 'none') {
            truncated.style.display = 'none';
            full.style.display = 'inline';
        } else {
            truncated.style.display = 'inline';
            full.style.display = 'none';
        }
    }
};
