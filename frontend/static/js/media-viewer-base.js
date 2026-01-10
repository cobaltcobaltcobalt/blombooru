class MediaViewerBase {
    constructor() {
        this.currentMedia = null;
        this.fullscreenViewer = null;
    }

    el(id) {
        return document.getElementById(id);
    }

    initFullscreenViewer() {
        this.fullscreenViewer = new FullscreenMediaViewer();
    }

    // Common rendering methods
    setupAIMetadataToggle() {
        const toggle = this.el('ai-metadata-toggle');

        if (toggle) {
            const newToggle = toggle.cloneNode(true);
            toggle.parentNode.replaceChild(newToggle, toggle);

            newToggle.addEventListener('click', (e) => {
                const content = this.el('ai-metadata-content');
                const chevron = this.el('ai-metadata-chevron');

                if (content) {
                    const isHidden = content.style.display === 'none';
                    content.style.display = isHidden ? 'block' : 'none';

                    if (chevron) {
                        chevron.style.transform = isHidden ? 'rotate(180deg)' : 'rotate(0deg)';
                    }
                }
            });
        }
    }

    renderInfo(media, options = {}) {
        const { downloadUrl, isShared } = options;

        let infoHTML = `
            <div class="info-row"><span>Filename</span><strong>${media.filename}</strong></div>
            <div class="info-row"><span>Type</span><strong>${media.file_type}</strong></div>
            <div class="info-row"><span>Size</span><strong>${this.formatFileSize(media.file_size)}</strong></div>
            <div class="info-row"><span>Dimensions</span><strong>${media.width}x${media.height}</strong></div>
            <div class="info-row"><span>Rating</span><strong>${media.rating}</strong></div>
            <div class="info-row"><span>Uploaded</span><strong>${new Date(media.uploaded_at).toLocaleDateString()}</strong></div>
            ${media.duration ? `<div class="info-row"><span>Duration</span><strong>${this.formatDuration(media.duration)}</strong></div>` : ''}
        `;

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

        // Handle rating select if present (for non-shared views)
        const ratingSelect = this.el('rating-select');
        if (ratingSelect) {
            ratingSelect.value = media.rating;
        }
    }

    renderTags(media, options = {}) {
        const { clickable = true } = options;
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
                clickable
                    ? `<a href="/?q=${encodeURIComponent(tag.name)}" class="tag ${category} tag-text">${tag.name}</a>`
                    : `<span class="tag ${category} tag-text">${tag.name}</span>`
            ).join('')}
                    </div>
                </div>
            `;
        });

        container.innerHTML = html || '<p class="text-xs text-secondary mb-3">No tags</p>';
    }

    async renderAIMetadata(media, options = {}) {
        const { showControls = false } = options;
        const section = this.el('ai-metadata-section');
        const content = this.el('ai-metadata-content');
        const appendBtn = this.el('append-ai-tags-btn');
        const aiMetadataShareToggle = this.el('ai-metadata-share-toggle');

        try {
            let url = `/api/media/${media.id}/metadata`;
            if (options.isShared && media.share_uuid) {
                url = `/api/shared/${media.share_uuid}/metadata`;
            } else if (options.isShared && this.shareUuid) {
                // Fallback if media object doesn't have share_uuid but the viewer does
                url = `/api/shared/${this.shareUuid}/metadata`;
            }

            const res = await fetch(url);
            if (!res.ok) {
                this.hideAIMetadata(section, appendBtn, aiMetadataShareToggle);
                return;
            }

            const metadata = await res.json();
            const aiData = AITagUtils.extractAIData(metadata);

            if (!aiData || Object.keys(aiData).length === 0) {
                this.hideAIMetadata(section, appendBtn, aiMetadataShareToggle);
                return;
            }

            if (showControls) {
                if (aiMetadataShareToggle) aiMetadataShareToggle.style.display = 'block';
                if (appendBtn && aiData) appendBtn.style.display = 'block';
            }

            const generatedHTML = this.generateAIMetadataHTML(aiData);
            content.innerHTML = generatedHTML;
            section.style.display = 'block';
            this.setupAIMetadataEvents();
        } catch (e) {
            console.error('Error rendering AI metadata:', e);
            this.hideAIMetadata(section, appendBtn, aiMetadataShareToggle);
        }
    }

    hideAIMetadata(section, appendBtn, aiMetadataShareToggle) {
        if (section) section.style.display = 'none';
        if (appendBtn) appendBtn.style.display = 'none';
        if (aiMetadataShareToggle) aiMetadataShareToggle.style.display = 'none';
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

    setupAIMetadataEvents() {
        const content = this.el('ai-metadata-content');
        if (!content) return;

        const newContent = content.cloneNode(true);
        content.parentNode.replaceChild(newContent, content);

        newContent.addEventListener('click', (e) => {
            if (e.target.classList.contains('ai-toggle-btn')) {
                const btn = e.target;
                const textDiv = btn.previousElementSibling;

                if (textDiv && textDiv.classList.contains('ai-text-content')) {
                    const isCollapsed = textDiv.classList.contains('is-collapsed');

                    if (isCollapsed) {
                        textDiv.classList.remove('is-collapsed');
                        btn.classList.add('is-expanded');
                        btn.firstChild.textContent = 'Show less ';
                    } else {
                        textDiv.classList.add('is-collapsed');
                        btn.classList.remove('is-expanded');
                        btn.firstChild.textContent = 'Show more ';
                    }
                }
            }
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
            .replace(/Negative Prompt/g, 'Negative Prompt')
            .replace(/Loras/g, 'LoRAs');
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    formatValue(value, isExpandable = true) {
        if (value === null || value === undefined) {
            return '<span class="text-secondary text-xs italic">Empty</span>';
        }

        if (typeof value === 'boolean') {
            return value
                ? '<span class="text text-xs">Yes</span>'
                : '<span class="text text-xs">No</span>';
        }

        if (Array.isArray(value)) {
            if (value.length === 0) return '<span class="text-secondary text-xs italic">None</span>';
            return value.map(v => this.escapeHtml(String(v))).join(', ');
        }

        if (typeof value === 'object') {
            try {
                return `<code class="block bg-surface-dark p-2 rounded text-xs overflow-x-auto">${this.escapeHtml(JSON.stringify(value, null, 2))}</code>`;
            } catch (e) {
                return '[Complex Object]';
            }
        }

        const str = String(value);
        const escaped = this.escapeHtml(str);

        const needsExpansion = isExpandable && (str.length > 200 || (str.match(/\n/g) || []).length > 4);

        if (needsExpansion) {
            return `
                <div class="ai-expandable-wrapper group">
                    <div class="ai-text-content is-collapsed">${escaped}</div>
                    <button type="button" class="ai-toggle-btn">Show more</button>
                </div>
            `;
        }

        return `<div class="ai-text-content">${escaped}</div>`;
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
window.toggleExpand = function (id) {
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
