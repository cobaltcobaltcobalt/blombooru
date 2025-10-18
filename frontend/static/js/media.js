class MediaViewer extends MediaViewerBase {
    constructor(mediaId) {
        super();
        this.mediaId = mediaId;
        this.tagValidationCache = new Map();
        this.validationTimeout = null;
        
        this.init();
    }

    init() {
        this.initFullscreenViewer();
        this.loadMedia();
        this.setupEventListeners();
    }

    async loadMedia() {
        try {
            const res = await fetch(`/api/media/${this.mediaId}`);
            this.currentMedia = await res.json();
            this.renderMedia(this.currentMedia);
            this.renderInfo(this.currentMedia);
            this.renderTags(this.currentMedia, { clickable: true });

            // Hide AI metadata toggle by default
            const aiMetadataShareToggle = this.el('ai-metadata-share-toggle');
            if (aiMetadataShareToggle) {
                aiMetadataShareToggle.style.display = 'none';
            }

            await this.renderAIMetadata(this.currentMedia, { 
                showControls: app.isAdminMode 
            });
            
            if (app.isAdminMode) {
                this.setupAdminMode();
            }
            
            if (this.currentMedia.is_shared) {
                this.showShareLink(this.currentMedia.share_uuid, this.currentMedia.share_ai_metadata);
            }
            
            await this.loadRelatedMedia();
        } catch (e) {
            console.error('loadMedia error', e);
        }
    }

    setupAdminMode() {
        this.el('edit-tags-section').style.display = 'block';
        this.el('edit-source-section').style.display = 'block';
        this.el('admin-actions').style.display = 'block';
        this.el('unshare-btn').style.display = 'block';
        this.setupTagInput();
        
        // Set source input value
        const sourceInput = this.el('source-input');
        if (sourceInput) {
            sourceInput.value = this.currentMedia.source || '';
        }
        
        // Initialize tag autocomplete
        const tagsInput = this.el('tags-input');
        if (tagsInput) {
            new TagAutocomplete(tagsInput, {
                multipleValues: true,
                onSelect: () => {
                    setTimeout(() => this.validateAndStyleTags(), 100);
                }
            });
            
            // Set initial tags
            tagsInput.textContent = (this.currentMedia.tags || []).map(t => t.name).join(' ');
            setTimeout(() => this.validateAndStyleTags(), 100);
        }
    }

    renderMedia(media) {
        const container = this.el('media-container');
        if (media.file_type === 'video') {
            container.innerHTML = `<video controls loop><source src="/api/media/${media.id}/file" type="${media.mime_type}"></video>`;
        } else {
            container.innerHTML = `<img src="/api/media/${media.id}/file" alt="${media.filename}" id="main-media-image">`;
            
            setTimeout(() => {
                const mainImage = this.el('main-media-image');
                if (mainImage) {
                    mainImage.addEventListener('click', () => {
                        this.fullscreenViewer.open(`/api/media/${media.id}/file`);
                    });
                }
            }, 0);
        }

        this.el('download-btn').href = `/api/media/${media.id}/file`;
        this.el('download-btn').download = media.filename;
    }

    setupTagInput() {
        const tagsInput = this.el('tags-input');
        if (!tagsInput) return;
        
        tagsInput.addEventListener('input', () => {
            clearTimeout(this.validationTimeout);
            this.validationTimeout = setTimeout(() => this.validateAndStyleTags(), 300);
        });
        
        tagsInput.addEventListener('keyup', (e) => {
            if (e.key === ' ') {
                clearTimeout(this.validationTimeout);
                this.validateAndStyleTags();
            }
        });
        
        tagsInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
            }
        });
        
        tagsInput.addEventListener('paste', (e) => {
            e.preventDefault();
            const text = e.clipboardData.getData('text/plain');
            document.execCommand('insertText', false, text);
        });
    }

    async validateAndStyleTags() {
        const tagsInput = this.el('tags-input');
        if (!tagsInput) return;
        
        const text = this.getPlainTextFromDiv(tagsInput);
        const cursorPos = this.getCursorPosition(tagsInput);
        
        const parts = text.split(/(\s+)/);
        const tags = [];
        
        for (let part of parts) {
            if (part.trim()) {
                const normalized = part.trim().toLowerCase();
                if (!this.tagValidationCache.has(normalized)) {
                    const exists = await this.checkTagExists(normalized);
                    this.tagValidationCache.set(normalized, exists);
                }
                tags.push({ text: part, isValid: this.tagValidationCache.get(normalized) });
            } else {
                tags.push({ text: part, isWhitespace: true });
            }
        }
        
        let html = '';
        for (let tag of tags) {
            if (tag.isWhitespace) {
                html += tag.text;
            } else if (tag.isValid === false) {
                html += `<span class="invalid-tag">${tag.text}</span>`;
            } else {
                html += tag.text;
            }
        }
        
        if (tagsInput.innerHTML !== html) {
            tagsInput.innerHTML = html || '';
            this.setCursorPosition(tagsInput, cursorPos);
        }
    }

    async checkTagExists(tagName) {
        if (!tagName || !tagName.trim()) return true;
        const normalized = tagName.toLowerCase().trim();
        
        try {
            const res = await fetch(`/api/tags/${encodeURIComponent(normalized)}`);
            return res.ok;
        } catch (e) {
            console.error('Error checking tag:', e);
            return false;
        }
    }

    async getTagOrAlias(tagName) {
        if (!tagName || !tagName.trim()) return null;
        const normalized = tagName.toLowerCase().trim();
        
        try {
            const res = await fetch(`/api/tags/${encodeURIComponent(normalized)}`);
            if (!res.ok) return null;
            
            const data = await res.json();
            return data.aliased_to || data.name;
        } catch (e) {
            console.error('Error fetching tag:', e);
            return null;
        }
    }

    async loadRelatedMedia() {
        if (!this.currentMedia || !this.currentMedia.tags || !this.currentMedia.tags.length) {
            this.hideRelatedMedia();
            return;
        }

        let generalTags = this.currentMedia.tags.filter(t => t.category === 'general');
    
        if (!generalTags.length) {
            this.hideRelatedMedia();
            return;
        }

        // Shuffle tags
        for (let i = generalTags.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [generalTags[i], generalTags[j]] = [generalTags[j], generalTags[i]];
        }

        const numTags = Math.min(2, Math.max(1, Math.floor(Math.random() * generalTags.length) + 1));
        const tagQuery = generalTags.slice(0, numTags).map(t => t.name).join(' ');

        try {
            const res = await fetch(`/api/search?q=${encodeURIComponent(tagQuery)}&limit=12`);
            const data = await res.json();
            const currentMediaId = parseInt(this.mediaId);
            const items = (data.items || []).filter(i => i.id !== currentMediaId);

            if (items.length === 0) {
                this.hideRelatedMedia();
                return;
            }

            this.renderRelatedMedia(items);
        } catch (e) {
            console.error('related error', e);
            this.hideRelatedMedia();
        }
    }

    renderRelatedMedia(items) {
        const relatedMediaEl = this.el('related-media');
        const relatedMediaSection = relatedMediaEl.parentElement;
        const params = new URLSearchParams(window.location.search);
        const queryString = params.toString();
        relatedMediaSection.style.display = 'block';

        const tooltipElement = this.createTooltip();
        relatedMediaEl.innerHTML = '';

        items.forEach(media => {
            const item = this.createRelatedMediaItem(media, queryString, tooltipElement);
            relatedMediaEl.appendChild(item);
        });
    }

    createRelatedMediaItem(media, queryString, tooltipElement) {
        const item = document.createElement('div');
        item.className = `gallery-item ${media.file_type}`;
        item.dataset.id = media.id;
        item.dataset.rating = media.rating;

        const link = document.createElement('a');
        link.href = `/media/${media.id}${queryString ? '?' + queryString : ''}`;

        const img = document.createElement('img');
        img.src = `/api/media/${media.id}/thumbnail`;
        img.alt = media.filename;
        img.loading = 'lazy';
        img.onerror = () => {
            console.error('Failed to load thumbnail for media:', media.id);
            img.src = '/static/images/no-thumbnail.png';
        };

        link.appendChild(img);
        item.appendChild(link);

        if (media.is_shared) {
            const shareIcon = document.createElement('div');
            shareIcon.className = 'share-icon';
            shareIcon.textContent = 'SHARED';
            item.appendChild(shareIcon);
        }

        this.addTooltipEvents(item, media, tooltipElement);
        return item;
    }

    hideRelatedMedia() {
        const relatedMediaEl = this.el('related-media');
        if (relatedMediaEl) {
            const relatedMediaSection = relatedMediaEl.parentElement;
            if (relatedMediaSection) {
                relatedMediaSection.style.display = 'none';
            }
        }
    }

    setupEventListeners() {
        this.el('edit-tags-form')?.addEventListener('submit', async (e) => {
            e.preventDefault();
            await this.saveTags();
        });

        this.el('save-source-btn')?.addEventListener('click', async () => {
            await this.saveSource();
        });

        this.el('rating-select')?.addEventListener('change', async (e) => {
            await this.updateRating(e.target.value);
        });

        this.el('share-btn')?.addEventListener('click', async () => {
            await this.shareMedia();
        });

        this.el('copy-share-link-btn')?.addEventListener('click', () => {
            this.copyShareLink();
        });

        this.el('unshare-btn')?.addEventListener('click', async () => {
            await this.unshareMedia();
        });

        this.el('delete-btn')?.addEventListener('click', async () => {
            await this.deleteMedia();
        });

        this.el('share-ai-metadata-toggle')?.addEventListener('change', async (e) => {
            await this.updateShareSettings(e.target.checked);
        });

        this.el('append-ai-tags-btn')?.addEventListener('click', async () => {
            await this.appendAITags();
        });
    }

    // Admin action methods
    async saveTags() {
        const tagsInput = this.el('tags-input');
        const text = this.getPlainTextFromDiv(tagsInput);
        const allTags = text.split(/\s+/).filter(t => t.length > 0);
        
        const validTags = [];
        for (const tag of allTags) {
            const normalized = tag.toLowerCase().trim();
            const isValid = this.tagValidationCache.get(normalized);
            if (isValid !== false) {
                validTags.push(tag);
            }
        }
        
        try {
            await app.apiCall(`/api/media/${this.mediaId}`, { 
                method: 'PATCH', 
                body: JSON.stringify({ tags: validTags }) 
            });
            location.reload();
        } catch (e) { 
            app.showNotification(e.message, 'error', 'Error updating tags'); 
        }
    }

    async saveSource() {
        const sourceInput = this.el('source-input');
        const sourceValue = sourceInput.value.trim();

        try {
            await app.apiCall(`/api/media/${this.mediaId}`, { 
                method: 'PATCH', 
                body: JSON.stringify({ source: sourceValue || null }) 
            });
            app.showNotification('Source updated successfully', 'success');
            location.reload();
        } catch (e) { 
            app.showNotification(e.message, 'error', 'Error updating source'); 
        }
    }

    async updateRating(rating) {
        try {
            await app.apiCall(`/api/media/${this.mediaId}`, { 
                method: 'PATCH', 
                body: JSON.stringify({ rating }) 
            });
        } catch (e) { 
            app.showNotification(e.message, 'error', 'Error updating rating'); 
        }
    }

    async shareMedia() {
        try {
            const res = await app.apiCall(`/api/media/${this.mediaId}/share`, { method: 'POST' });
            this.showShareLink(res.share_url.split('/').pop(), res.share_ai_metadata);
        } catch (e) { 
            app.showNotification(e.message, 'error', 'Error creating share link'); 
        }
    }

    copyShareLink() {
        this.el('share-link-input').select(); 
        document.execCommand('copy');
    }

    async unshareMedia() {
        if (!confirm('Are you sure you want to unshare this media? The share link will stop working.')) {
            return;
        }
        
        try {
            await app.apiCall(`/api/media/${this.mediaId}/share`, { method: 'DELETE' });
            this.el('share-link-section').style.display = 'none';
            this.el('share-btn').style.display = 'block';
            app.showNotification('Media successfully unshared', 'success');
        } catch (e) { 
            app.showNotification(e.message, 'error', 'Error removing share'); 
        }
    }

    async deleteMedia() {
        if (!confirm('Delete this media?')) return;
        try {
            await app.apiCall(`/api/media/${this.mediaId}`, { method: 'DELETE' });
            window.location.href = '/';
        } catch (e) { 
            app.showNotification(e.message, 'error', 'Error deleting media'); 
        }
    }

    async updateShareSettings(shareAIMetadata) {
        try {
            await app.apiCall(`/api/media/${this.mediaId}/share-settings?share_ai_metadata=${shareAIMetadata}`, { 
                method: 'PATCH'
            });
        } catch (err) {
            app.showNotification(err.message, 'error', 'Error updating share settings');
            const toggle = this.el('share-ai-metadata-toggle');
            if (toggle) toggle.checked = !toggle.checked;
        }
    }

    async appendAITags() {
        try {
            const res = await fetch(`/api/media/${this.mediaId}/metadata`);
            if (!res.ok) {
                app.showNotification('Could not load AI metadata', 'error');
                return;
            }
        
            const metadata = await res.json();
            const aiPrompt = this.extractAIPrompt(metadata);
        
            if (!aiPrompt || typeof aiPrompt !== 'string') {
                app.showNotification('No AI prompt found in metadata', 'error');
                return;
            }
        
            const promptTags = aiPrompt
                .split(',')
                .map(tag => tag.trim().replace(/\s+/g, '_'))
                .filter(tag => tag.length > 0);
        
            const validTags = [];
            for (const tag of promptTags) {
                const validTag = await this.getTagOrAlias(tag);
                if (validTag) {
                    validTags.push(validTag);
                }
            }
        
            if (validTags.length === 0) {
                app.showNotification('No valid tags found in AI prompt', 'error');
                return;
            }
        
            const tagsInput = this.el('tags-input');
            const currentText = this.getPlainTextFromDiv(tagsInput).trim();
            const currentTags = currentText ? currentText.split(/\s+/) : [];
        
            const existingTagsSet = new Set(currentTags.map(t => t.toLowerCase()));
            const newTags = validTags.filter(tag => !existingTagsSet.has(tag.toLowerCase()));
        
            if (newTags.length === 0) {
                app.showNotification('All AI tags are already present', 'info');
                return;
            }
        
            const allTags = [...currentTags, ...newTags];
            tagsInput.textContent = allTags.join(' ');
        
            await this.validateAndStyleTags();
            app.showNotification(`Appended ${newTags.length} tag(s) from AI prompt`, 'success');
        
        } catch (e) {
            console.error('Error appending AI tags:', e);
            app.showNotification('Error processing AI tags: ' + e.message, 'error');
        }
    }

    extractAIPrompt(metadata) {
        // Check various common structures for AI prompt
        const checkLocations = [
            metadata.parameters?.sui_image_params?.prompt,
            metadata.parameters?.prompt,
            metadata.parameters?.Prompt,
            metadata.Parameters?.sui_image_params?.prompt,
            metadata.Parameters?.prompt,
            metadata.Parameters?.Prompt,
            metadata.sui_image_params?.prompt,
            metadata.prompt,
            metadata.Prompt
        ];

        for (const location of checkLocations) {
            if (location) return location;
        }

        // Fallback: search through all nested objects
        for (const [key, value] of Object.entries(metadata)) {
            if (typeof value === 'object' && value !== null) {
                if (value.prompt || value.Prompt) {
                    return value.prompt || value.Prompt;
                }
                if (value.sui_image_params?.prompt) {
                    return value.sui_image_params.prompt;
                }
            }
        }

        return null;
    }

    showShareLink(uuid, shareAIMetadata) {
        this.el('share-link-input').value = `${window.location.origin}/shared/${uuid}`;
        this.el('share-link-section').style.display = 'block';
        this.el('share-btn').style.display = 'none';

        const aiMetadataToggle = this.el('share-ai-metadata-toggle');
        if (aiMetadataToggle) {
            aiMetadataToggle.checked = shareAIMetadata || false;
        }
    }
}
