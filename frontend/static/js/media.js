class MediaViewer {
    constructor(mediaId) {
        this.mediaId = mediaId;
        this.currentMedia = null;
        this.tagValidationCache = new Map();
        this.validationTimeout = null;
        this.fullscreenViewer = null;
        
        this.init();
    }

    init() {
        this.initFullscreenViewer();
        this.loadMedia();
        this.setupEventListeners();
    }

    el(id) {
        return document.getElementById(id);
    }

    initFullscreenViewer() {
        this.fullscreenViewer = new FullscreenImageViewer();
    }

    async loadMedia() {
        try {
            const res = await fetch(`/api/media/${this.mediaId}`);
            this.currentMedia = await res.json();
            this.renderMedia(this.currentMedia);
            this.renderInfo(this.currentMedia);
            this.renderTags(this.currentMedia);

            // Hide AI metadata toggle by default
            const aiMetadataShareToggle = this.el('ai-metadata-share-toggle');
            if (aiMetadataShareToggle) {
                aiMetadataShareToggle.style.display = 'none';
            }

            await this.renderAIMetadata(this.currentMedia);
            
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

    renderInfo(m) {
        let infoHTML = `
            <div class="info-row"><span>Filename</span><strong>${m.filename}</strong></div>
            <div class="info-row"><span>Type</span><strong>${m.file_type}</strong></div>
            <div class="info-row"><span>Size</span><strong>${this.formatFileSize(m.file_size)}</strong></div>
            <div class="info-row"><span>Dimensions</span><strong>${m.width}x${m.height}</strong></div>
            <div class="info-row"><span>Rating</span><strong>${m.rating}</strong></div>
            <div class="info-row"><span>Uploaded</span><strong>${new Date(m.uploaded_at).toLocaleDateString()}</strong></div>
            ${m.duration ? `<div class="info-row"><span>Duration</span><strong>${this.formatDuration(m.duration)}</strong></div>` : ''}
        `;

        if (m.source) {
            infoHTML += `<div class="info-row"><span>Source</span><strong><a href="${m.source}" target="_blank" rel="noopener noreferrer" class="text-primary hover:underline" style="word-break: break-all;">${m.source}</a></strong></div>`;
        }

        this.el('media-info-content').innerHTML = infoHTML;

        const sel = this.el('rating-select');
        if (sel) sel.value = m.rating;
    }

    renderTags(m) {
        const container = this.el('tags-container');
        const groups = { artist: [], character: [], copyright: [], general: [], meta: [] };
        (m.tags || []).forEach(t => groups[t.category]?.push(t));
        
        let html = '';
        Object.entries(groups).forEach(([cat, tags]) => {
            if (!tags.length) return;
            tags.sort((a, b) => a.name.localeCompare(b.name));
            html += `
                <div class="tag-category">
                  <h4>${cat}</h4>
                  <div class="tag-list">
                    ${tags.map(t => `<a href="/?q=${encodeURIComponent(t.name)}" class="tag ${cat} tag-text">${t.name}</a>`).join('')}
                  </div>
                </div>
            `;
        });
        container.innerHTML = html || '<p class="text-xs text-secondary mb-3">No tags</p>';
        
        const input = this.el('tags-input');
        if (input) {
            input.textContent = (m.tags || []).map(t => t.name).join(' ');
            setTimeout(() => this.validateAndStyleTags(), 100);
        }
    }

    async renderAIMetadata(m) {
        const section = this.el('ai-metadata-section');
        const content = this.el('ai-metadata-content');
        const appendBtn = this.el('append-ai-tags-btn');
        const aiMetadataShareToggle = this.el('ai-metadata-share-toggle');

        try {
            const res = await fetch(`/api/media/${m.id}/metadata`);
            if (!res.ok) {
                section.style.display = 'none';
                if (appendBtn) appendBtn.style.display = 'none';
                if (aiMetadataShareToggle) aiMetadataShareToggle.style.display = 'none';
                return;
            }

            const metadata = await res.json();
            let aiData = this.extractAIData(metadata);

            if (!aiData || Object.keys(aiData).length === 0) {
                section.style.display = 'none';
                if (appendBtn) appendBtn.style.display = 'none';
                if (aiMetadataShareToggle) aiMetadataShareToggle.style.display = 'none';
                return;
            }

            if (app.isAdminMode && aiMetadataShareToggle) {
                aiMetadataShareToggle.style.display = 'block';
            }

            if (app.isAdminMode && appendBtn && aiData) {
                appendBtn.style.display = 'block';
            }

            content.innerHTML = this.generateAIMetadataHTML(aiData);
            section.style.display = 'block';
            this.setupExpandableListeners();
        } catch (e) {
            console.error('Error rendering AI metadata:', e);
            section.style.display = 'none';
            if (aiMetadataShareToggle) aiMetadataShareToggle.style.display = 'none';
        }
    }

    extractAIData(metadata) {
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

    addTooltipEvents(item, media, tooltipElement) {
        let hoverTimeout;
        item.addEventListener('mouseenter', () => {
            hoverTimeout = setTimeout(() => {
                if (media.tags && media.tags.length > 0) {
                    this.showTooltip(item, media.tags, tooltipElement);
                }
            }, 300);
        });

        item.addEventListener('mouseleave', () => {
            clearTimeout(hoverTimeout);
            this.hideTooltip(tooltipElement);
        });

        window.addEventListener('scroll', () => {
            if (tooltipElement.style.display === 'block') {
                this.positionTooltip(item, tooltipElement);
            }
        }, { passive: true });
    }

    createTooltip() {
        if (!document.getElementById('media-tooltip')) {
            const tooltip = document.createElement('div');
            tooltip.id = 'media-tooltip';
            tooltip.style.cssText = `
                position: absolute;
                background: rgba(0, 0, 0, 0.95);
                color: white;
                padding: 8px 12px;
                font-size: 13px;
                pointer-events: none;
                z-index: 10000;
                max-width: 300px;
                word-wrap: break-word;
                display: none;
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
            `;
            document.body.appendChild(tooltip);
        }
        return document.getElementById('media-tooltip');
    }

    showTooltip(element, tags, tooltipElement) {
        if (!tags || tags.length === 0) return;

        const sortedTags = tags
            .map(tag => tag.name || tag)
            .sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));

        const tagList = sortedTags.join(', ');
        tooltipElement.textContent = tagList;
        tooltipElement.style.display = 'block';
        this.positionTooltip(element, tooltipElement);
    }

    positionTooltip(element, tooltipElement) {
        const rect = element.getBoundingClientRect();
        const tooltipRect = tooltipElement.getBoundingClientRect();

        let top = rect.top - tooltipRect.height - 10;
        let left = rect.left + (rect.width / 2) - (tooltipRect.width / 2);

        if (top < 10) {
            top = rect.bottom + 10;
        }

        if (left < 10) {
            left = 10;
        } else if (left + tooltipRect.width > window.innerWidth - 10) {
            left = window.innerWidth - tooltipRect.width - 10;
        }

        top += window.scrollY;
        left += window.scrollX;

        tooltipElement.style.top = `${top}px`;
        tooltipElement.style.left = `${left}px`;
    }

    hideTooltip(tooltipElement) {
        if (tooltipElement) {
            tooltipElement.style.display = 'none';
        }
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

    setupExpandableListeners() {
        document.querySelectorAll('.expandable-text').forEach(container => {
            const newContainer = container.cloneNode(true);
            container.parentNode.replaceChild(newContainer, container);

            newContainer.addEventListener('click', function(e) {
                const selection = window.getSelection();
                if (selection && selection.toString().length > 0) {
                    return;
                }

                const id = this.id.replace('-container', '');
                window.toggleExpand(id);
            });

            newContainer.addEventListener('dblclick', function(e) {
                e.stopPropagation();
            });
        });
    }

    // Utility methods
    formatFileSize(bytes) {
        if (!bytes) return '0 Bytes';
        const k = 1024, sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i];
    }

    formatDuration(s) {
        const m = Math.floor(s / 60), sec = Math.floor(s % 60);
        return `${m}:${String(sec).padStart(2, '0')}`;
    }

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
                        <span class="text-truncated" id="${id}-truncated">${escaped.substring(0, 100)}...<br><span class="expand-indicator" style="user-select: none;">[click to expand]</span></span>
                        <span class="text-full" id="${id}-full" style="display: none;">${escaped}<br><span class="expand-indicator" style="user-select: none;">[click to collapse]</span></span>
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

    getPlainTextFromDiv(div) {
        return div.textContent || '';
    }

    getCursorPosition(element) {
        const selection = window.getSelection();
        if (selection.rangeCount === 0) return 0;
        
        const range = selection.getRangeAt(0);
        const preCaretRange = range.cloneRange();
        preCaretRange.selectNodeContents(element);
        preCaretRange.setEnd(range.endContainer, range.endOffset);
        
        return preCaretRange.toString().length;
    }

    setCursorPosition(element, offset) {
        const selection = window.getSelection();
        const range = document.createRange();
        
        let currentOffset = 0;
        let found = false;
        
        function traverseNodes(node) {
            if (found) return;
            
            if (node.nodeType === Node.TEXT_NODE) {
                const nodeLength = node.textContent.length;
                if (currentOffset + nodeLength >= offset) {
                    range.setStart(node, offset - currentOffset);
                    range.collapse(true);
                    found = true;
                    return;
                }
                currentOffset += nodeLength;
            } else {
                for (let child of node.childNodes) {
                    traverseNodes(child);
                    if (found) return;
                }
            }
        }
        
        try {
            traverseNodes(element);
            if (!found && element.lastChild) {
                range.setStartAfter(element.lastChild);
                range.collapse(true);
            }
            selection.removeAllRanges();
            selection.addRange(range);
        } catch (e) {
            console.error('Error setting cursor:', e);
        }
    }
}
