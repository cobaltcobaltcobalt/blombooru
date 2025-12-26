class BulkWDTaggerModal extends BulkTagModalBase {
    constructor(options = {}) {
        super({
            id: 'bulk-wd-tagger-modal',
            title: 'Bulk AI Tag Prediction (WD Tagger)',
            classPrefix: 'bulk-wd-tagger',
            emptyMessage: 'No new tags could be predicted for the selected items.',
            ...options
        });

        this.settings = {
            generalThreshold: 0.35,
            characterThreshold: 0.85,
            hideRatingTags: true,
            characterTagsFirst: true,
            modelName: 'wd-eva02-large-tagger-v3'
        };

        this.init();
    }

    getStates() {
        return ['loading', 'content', 'empty', 'error', 'cancelled', 'download-confirm', 'downloading'];
    }

    getBodyHTML() {
        return `
            ${this.getSettingsHTML()}
            ${this.getDownloadConfirmHTML()}
            ${this.getDownloadingHTML()}
            ${this.getLoadingHTML('Initializing AI Tagger...')}
            ${this.getContentHTML()}
            ${this.getEmptyHTML()}
            ${this.getErrorHTML()}
            ${this.getCancelledHTML()}
        `;
    }

    getSettingsHTML() {
        const prefix = this.options.classPrefix;
        return `
            <div class="${prefix}-settings mb-4 p-3 surface-light border text-sm" style="display: none;">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div>
                        <label class="block text-xs text-secondary mb-1">General Confidence Threshold</label>
                        <input type="number" class="wd-general-threshold w-full px-2 py-1 border surface text-sm" 
                               min="0" max="1" step="0.05" value="${this.settings.generalThreshold}">
                    </div>
                    <div>
                        <label class="block text-xs text-secondary mb-1">Character Confidence Threshold</label>
                        <input type="number" class="wd-character-threshold w-full px-2 py-1 border surface text-sm" 
                               min="0" max="1" step="0.05" value="${this.settings.characterThreshold}">
                    </div>
                </div>
            </div>
        `;
    }

    getDownloadConfirmHTML() {
        const prefix = this.options.classPrefix;
        return `
            <div class="${prefix}-download-confirm text-center py-8" style="display: none;">
                <div class="mb-4">
                    <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="mx-auto text-warning">
                        <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                        <polyline points="7 10 12 15 17 10"></polyline>
                        <line x1="12" y1="15" x2="12" y2="3"></line>
                    </svg>
                </div>
                <p class="text-secondary mb-2">The AI model needs to be downloaded first.</p>
                <p class="text-secondary text-sm mb-4">
                    Model: <strong class="download-model-name">${this.settings.modelName}</strong><br>
                    Size: approximately <strong class="download-model-size">~850 MB</strong>
                </p>
                <div class="flex justify-center gap-2">
                    <button class="${prefix}-download-cancel px-4 py-2 surface-light text text-sm">
                        Cancel
                    </button>
                    <button class="${prefix}-download-confirm-btn px-4 py-2 bg-primary tag-text text-sm">
                        Download & Continue
                    </button>
                </div>
            </div>
        `;
    }

    getDownloadingHTML() {
        const prefix = this.options.classPrefix;
        return `
            <div class="${prefix}-downloading text-center py-8" style="display: none;">
                <div class="mb-4">
                    <div class="inline-block animate-spin rounded-full h-12 w-12 border-4 border-primary border-t-transparent"></div>
                </div>
                <p class="text-secondary mb-2">Downloading AI model...</p>
                <p class="text-secondary text-sm">This may take a few minutes depending on your connection.</p>
                <p class="text-secondary text-xs mt-2">Model files are cached locally for future use.</p>
            </div>
        `;
    }

    getFooterLeftHTML() {
        const prefix = this.options.classPrefix;
        return `
            <button class="${prefix}-toggle-settings px-3 py-2 surface-light text text-sm">
                Settings
            </button>
        `;
    }

    setupAdditionalEventListeners() {
        const prefix = this.options.classPrefix;

        // Settings toggle
        const toggleSettings = this.modalElement.querySelector(`.${prefix}-toggle-settings`);
        if (toggleSettings) {
            toggleSettings.addEventListener('click', () => {
                const settings = this.modalElement.querySelector(`.${prefix}-settings`);
                if (settings) {
                    settings.style.display = settings.style.display === 'none' ? 'block' : 'none';
                }
            });
        }

        // Download buttons
        const downloadCancelBtn = this.modalElement.querySelector(`.${prefix}-download-cancel`);
        if (downloadCancelBtn) {
            downloadCancelBtn.addEventListener('click', () => this.cancel());
        }

        const downloadConfirmBtn = this.modalElement.querySelector(`.${prefix}-download-confirm-btn`);
        if (downloadConfirmBtn) {
            downloadConfirmBtn.addEventListener('click', () => this.downloadModelAndContinue());
        }

        // Settings inputs
        const generalThreshold = this.modalElement.querySelector('.wd-general-threshold');
        if (generalThreshold) {
            generalThreshold.addEventListener('change', (e) => {
                this.settings.generalThreshold = parseFloat(e.target.value);
            });
        }

        const characterThreshold = this.modalElement.querySelector('.wd-character-threshold');
        if (characterThreshold) {
            characterThreshold.addEventListener('change', (e) => {
                this.settings.characterThreshold = parseFloat(e.target.value);
            });
        }
    }

    reset() {
        super.reset();
        const prefix = this.options.classPrefix;
        const settings = this.modalElement.querySelector(`.${prefix}-settings`);
        if (settings) settings.style.display = 'none';
    }

    async onShow() {
        await this.checkModelAndStart();
    }

    async checkModelAndStart() {
        this.showState('loading');
        this.updateProgress(0, 0, 'Checking AI model status...', '');

        try {
            const response = await this.fetchWithAbort(`/api/ai-tagger/model-status/${this.settings.modelName}`);

            if (this.isCancelled) return;

            if (!response.ok) {
                throw new Error('Failed to check model status');
            }

            const status = await response.json();

            if (status.is_downloaded || status.is_loaded) {
                await this.fetchTags();
            } else {
                const modelNameEl = this.modalElement.querySelector('.download-model-name');
                const modelSizeEl = this.modalElement.querySelector('.download-model-size');

                if (modelNameEl) modelNameEl.textContent = this.settings.modelName;
                if (modelSizeEl) modelSizeEl.textContent = status.download_size_mb
                    ? `~${status.download_size_mb} MB`
                    : 'Unknown';

                this.showState('download-confirm');
            }
        } catch (e) {
            if (e.name === 'AbortError') return;
            console.error('Error checking model status:', e);
            this.showError(`Failed to check model status: ${e.message}`);
        }
    }

    async downloadModelAndContinue() {
        this.showState('downloading');

        try {
            const response = await this.fetchWithAbort(`/api/ai-tagger/download/${this.settings.modelName}`, {
                method: 'POST'
            });

            if (this.isCancelled) return;

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || 'Download failed');
            }

            await this.fetchTags();
        } catch (e) {
            if (e.name === 'AbortError') return;
            console.error('Error downloading model:', e);
            this.showError(`Failed to download model: ${e.message}`);
        }
    }

    async fetchTags() {
        if (this.isCancelled) return;

        this.showState('loading');
        const prefix = this.options.classPrefix;
        const itemsContainer = this.modalElement.querySelector(`.${prefix}-items`);

        const selectedArray = Array.from(this.selectedItems);

        // Phase 1: Fetch media info
        const mediaInfoMap = new Map();
        let fetchProgress = 0;

        this.updateProgress(0, selectedArray.length, 'Fetching media info...', 'items fetched');

        const fetchMediaInfo = async (mediaId) => {
            if (this.isCancelled) return;
            try {
                const res = await this.fetchWithAbort(`/api/media/${mediaId}`);
                if (res.ok) {
                    const data = await res.json();
                    mediaInfoMap.set(mediaId, data);
                }
            } catch (e) {
                if (e.name === 'AbortError') throw e;
                console.error(`Error fetching media ${mediaId}:`, e);
            } finally {
                fetchProgress++;
                if (!this.isCancelled) {
                    this.updateProgress(fetchProgress, selectedArray.length, 'Fetching media info...', 'items fetched');
                }
            }
        };

        try {
            await this.processBatch(selectedArray, fetchMediaInfo, 10);
        } catch (e) {
            if (e.name === 'AbortError') return;
            throw e;
        }

        if (this.isCancelled) return;

        // Phase 2: Predict tags
        let processed = 0;
        this.updateProgress(0, selectedArray.length, 'Predicting tags with AI...', 'items processed');

        const predictItem = async (mediaId) => {
            if (this.isCancelled) return;
            try {
                const result = await this.predictMediaTags(mediaId, mediaInfoMap.get(mediaId));
                if (result) {
                    this.itemsData.push(result);
                }
            } catch (e) {
                if (e.name === 'AbortError') throw e;
                console.error(`Error predicting tags for media ${mediaId}:`, e);
            } finally {
                processed++;
                if (!this.isCancelled) {
                    this.updateProgress(processed, selectedArray.length, 'Predicting tags with AI...', 'items processed');
                }
            }
        };

        try {
            await this.processBatch(selectedArray, predictItem, 3);
        } catch (e) {
            if (e.name === 'AbortError') return;
            throw e;
        }

        if (this.isCancelled) return;

        if (this.itemsData.length === 0) {
            this.showState('empty');
            return;
        }

        // Phase 3: Validate tags
        const allTags = new Set();
        for (const item of this.itemsData) {
            item.predictedTags.forEach(tag => allTags.add(tag.toLowerCase()));
        }

        try {
            await this.validateTags(Array.from(allTags));
        } catch (e) {
            if (e.name === 'AbortError') return;
            throw e;
        }

        if (this.isCancelled) return;

        // Apply validated tags
        for (const item of this.itemsData) {
            item.newTags = item.predictedTags.filter(tag => {
                const resolved = this.getResolvedTag(tag);
                return resolved !== null;
            }).map(tag => {
                const resolved = this.getResolvedTag(tag);
                return resolved || tag;
            });
        }

        // Filter out items with no valid tags
        this.itemsData = this.itemsData.filter(item => item.newTags.length > 0);

        if (this.itemsData.length === 0) {
            this.showState('empty');
            return;
        }

        this.renderItems();
        await this.initializeInputHelpers(itemsContainer);

        if (this.isCancelled) return;

        this.showState('content');
        this.showSaveButton();
    }

    async predictMediaTags(mediaId, mediaData) {
        if (this.isCancelled) return null;

        try {
            const response = await this.fetchWithAbort(`/api/ai-tagger/predict/${mediaId}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    general_threshold: this.settings.generalThreshold,
                    character_threshold: this.settings.characterThreshold,
                    hide_rating_tags: this.settings.hideRatingTags,
                    character_tags_first: this.settings.characterTagsFirst,
                    model_name: this.settings.modelName
                })
            });

            if (!response.ok) {
                const error = await response.json().catch(() => ({}));
                throw new Error(error.detail || 'Prediction failed');
            }

            const result = await response.json();
            const currentTags = (mediaData?.tags || []).map(t => t.name || t);
            const currentTagsSet = new Set(currentTags.map(t => t.toLowerCase()));

            const predictedTags = result.tags
                .map(t => t.name.replace(/ /g, '_'))
                .filter(t => !currentTagsSet.has(t.toLowerCase()));

            if (predictedTags.length > 0) {
                return {
                    mediaId,
                    currentTags,
                    predictedTags,
                    filename: mediaData?.filename || `Media ${mediaId}`
                };
            }
        } catch (e) {
            if (e.name === 'AbortError') throw e;
            console.error(`Error predicting tags for media ${mediaId}:`, e);
        }
        return null;
    }

    async refreshSingleItem(index, inputElement) {
        const item = this.itemsData[index];
        if (!item || this.isCancelled) return;

        inputElement.style.opacity = '0.5';

        try {
            const mediaRes = await this.fetchWithAbort(`/api/media/${item.mediaId}`);
            const mediaData = mediaRes.ok ? await mediaRes.json() : { tags: [] };

            const result = await this.predictMediaTags(item.mediaId, mediaData);

            if (result && result.predictedTags.length > 0) {
                // Validate new tags
                for (const tag of result.predictedTags) {
                    if (!this.tagResolutionCache.has(tag.toLowerCase())) {
                        await this.validateAndCacheTag(tag.toLowerCase());
                    }
                }

                const validTags = result.predictedTags.filter(tag => {
                    const resolved = this.getResolvedTag(tag);
                    return resolved !== null;
                }).map(tag => {
                    const resolved = this.getResolvedTag(tag);
                    return resolved || tag;
                });

                if (validTags.length > 0) {
                    const existingTags = this.tagInputHelper
                        ? this.tagInputHelper.getValidTagsFromInput(inputElement)
                        : inputElement.textContent.trim().split(/\s+/).filter(t => t);

                    const existingSet = new Set(existingTags.map(t => t.toLowerCase()));
                    const toAdd = validTags.filter(t => !existingSet.has(t.toLowerCase()));

                    if (toAdd.length > 0) {
                        const newValue = [...existingTags, ...toAdd].join(' ');
                        inputElement.textContent = newValue;
                        this.triggerValidation(inputElement);
                    } else {
                        this.flashButton(index, 'var(--warning)');
                    }
                } else {
                    this.flashButton(index, 'var(--danger)');
                }
            } else {
                this.flashButton(index, 'var(--danger)');
            }
        } catch (e) {
            if (e.name === 'AbortError') return;
            console.error(e);
            this.flashButton(index, 'var(--danger)');
        } finally {
            inputElement.style.opacity = '1';
        }
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = BulkWDTaggerModal;
}
