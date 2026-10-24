class TagInputHelper {
    constructor() {
        this.tagValidationCache = new Map();
        this.tagCategoryCache = new Map();
        this.validationTimeouts = new Map();
        this.abortControllers = new Map();
        this.tooltipHelper = null;
        this._tooltipTimeout = null;

        window.addEventListener('tagCreated', (e) => {
            if (e.detail && e.detail.name) {
                this.tagValidationCache.set(e.detail.name, true);
                if (e.detail.category) {
                    this.tagCategoryCache.set(e.detail.name.toLowerCase().trim(), e.detail.category);
                }
            }
        });
    }

    isHideImpliedEnabled() {
        return localStorage.getItem('hideImpliedTags') === 'true';
    }

    setHideImpliedEnabled(enabled) {
        const boolVal = Boolean(enabled);
        localStorage.setItem('hideImpliedTags', boolVal ? 'true' : 'false');
        window.dispatchEvent(new CustomEvent('hideImpliedTagsChanged', {
            detail: { enabled: boolVal }
        }));
    }

    formatImpliedByGroups(groups) {
        if (!Array.isArray(groups) || groups.length === 0) return '';
        const formattedGroups = groups
            .filter(g => Array.isArray(g) && g.length > 0)
            .map(g => g.join(' + '));
        return formattedGroups.join(', ');
    }

    getTagCategory(name) {
        if (!name) return 'general';
        return this.tagCategoryCache.get(name.toLowerCase().trim()) || 'general';
    }

    async ensureTagCategories(names) {
        if (!Array.isArray(names) || names.length === 0) return;
        const missing = names
            .map(n => String(n || '').toLowerCase().trim())
            .filter(n => n && !this.tagCategoryCache.has(n));
        if (missing.length === 0) return;
        await this.checkTagsBatch(missing);
    }

    parseTriggerTagNames(groupsOrString) {
        if (Array.isArray(groupsOrString)) {
            const set = new Set();
            for (const grp of groupsOrString) {
                if (Array.isArray(grp)) {
                    for (const t of grp) {
                        const trimmed = String(t || '').trim();
                        if (trimmed) set.add(trimmed);
                    }
                } else if (typeof grp === 'string') {
                    for (const t of grp.split(/[,+]/)) {
                        const trimmed = t.trim();
                        if (trimmed) set.add(trimmed);
                    }
                }
            }
            return Array.from(set);
        }
        if (typeof groupsOrString === 'string') {
            const set = new Set();
            for (const t of groupsOrString.split(/[,+]/)) {
                const trimmed = t.trim();
                if (trimmed) set.add(trimmed);
            }
            return Array.from(set);
        }
        return [];
    }

    getImpliedByGroups(impliedTags, normalizedTag) {
        if (!impliedTags || !normalizedTag) return null;
        const key = normalizedTag.toLowerCase().trim();
        if (impliedTags instanceof Map) {
            return impliedTags.has(key) ? (impliedTags.get(key) || []) : null;
        }
        if (impliedTags instanceof Set) {
            return impliedTags.has(key) ? [] : null;
        }
        if (typeof impliedTags === 'object') {
            return Object.prototype.hasOwnProperty.call(impliedTags, key) ? (impliedTags[key] || []) : null;
        }
        return null;
    }

    getTooltipHelper() {
        if (!this.tooltipHelper && typeof TooltipHelper !== 'undefined') {
            this.tooltipHelper = new TooltipHelper({
                id: 'implied-tag-tooltip',
                delay: 150
            });
        }
        return this.tooltipHelper;
    }

    attachImpliedTagTooltip(containerElement, signal = null) {
        if (!containerElement) return;
        const listenerOptions = signal ? { signal } : undefined;

        const clearHover = () => {
            if (this._tooltipTimeout) {
                clearTimeout(this._tooltipTimeout);
                this._tooltipTimeout = null;
            }
            const helper = this.getTooltipHelper();
            if (helper) helper.hide();
        };

        containerElement.addEventListener('mouseover', (e) => {
            const span = e.target.closest('.implied-tag');
            if (!span || !containerElement.contains(span)) return;
            if (this._tooltipTimeout) {
                clearTimeout(this._tooltipTimeout);
            }
            this._tooltipTimeout = setTimeout(async () => {
                const helper = this.getTooltipHelper();
                if (!helper) return;
                const rawImpliedBy = span.dataset.impliedBy || '';
                const triggerNames = this.parseTriggerTagNames(rawImpliedBy);
                if (triggerNames.length === 0) {
                    helper.show(span, [{ name: 'implied', category: 'general' }], true);
                    return;
                }
                await this.ensureTagCategories(triggerNames);
                const tagObjects = triggerNames.map(name => ({
                    name,
                    category: this.getTagCategory(name)
                }));
                const titleText = (window.i18n && typeof window.i18n.t === 'function')
                    ? window.i18n.t('tags_gallery.implied_by')
                    : 'Implied By';
                helper.show(span, tagObjects, titleText || true);
            }, 150);
        }, listenerOptions);

        containerElement.addEventListener('mouseout', (e) => {
            const span = e.target.closest('.implied-tag');
            if (!span) return;
            if (e.relatedTarget && span.contains(e.relatedTarget)) return;
            clearHover();
        }, listenerOptions);

        containerElement.addEventListener('input', clearHover, listenerOptions);
        containerElement.addEventListener('keydown', clearHover, listenerOptions);
        containerElement.addEventListener('blur', clearHover, listenerOptions);
    }

    // Get plain text from contenteditable div
    getPlainTextFromDiv(div) {
        return div.textContent || '';
    }

    // Get cursor position in contenteditable element
    getCursorPosition(element) {
        const selection = window.getSelection();
        if (selection.rangeCount === 0) return 0;

        const range = selection.getRangeAt(0);
        const preCaretRange = range.cloneRange();
        preCaretRange.selectNodeContents(element);
        preCaretRange.setEnd(range.endContainer, range.endOffset);

        return preCaretRange.toString().length;
    }

    // Set cursor position in contenteditable element
    setCursorPosition(element, offset) {
        const selection = window.getSelection();
        const range = document.createRange();

        let currentOffset = 0;
        let found = false;

        const traverseNodes = (node) => {
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
        };

        try {
            traverseNodes(element);
            if (!found && element.lastChild) {
                range.setStartAfter(element.lastChild);
                range.collapse(true);
            } else if (!found && !element.lastChild) {
                range.setStart(element, 0);
                range.collapse(true);
            }
            selection.removeAllRanges();
            selection.addRange(range);
        } catch (e) {
            console.error('Error setting cursor:', e);
        }
    }

    // Check if a tag exists
    async checkTagExists(tagName) {
        if (!tagName || !tagName.trim()) return true;
        const normalized = tagName.toLowerCase().trim();

        try {
            const res = await fetch(`/api/tags/${encodeURIComponent(normalized)}`);
            if (res.ok) {
                try {
                    const tagData = await res.json();
                    if (tagData && tagData.category) {
                        this.tagCategoryCache.set(normalized, tagData.category);
                    }
                } catch (e) { }
                return true;
            }
            return false;
        } catch (e) {
            console.error('Error checking tag:', e);
            return false;
        }
    }

    // Check multiple tags at once
    async checkTagsBatch(tagNames) {
        if (!tagNames || tagNames.length === 0) return {};

        const chunkSize = 50;
        const uniqueNames = Array.from(new Set(tagNames.map(n => n.toLowerCase().trim()).filter(Boolean)));
        const result = {};

        for (let i = 0; i < uniqueNames.length; i += chunkSize) {
            const chunk = uniqueNames.slice(i, i + chunkSize);
            try {
                const namesParam = chunk.map(n => encodeURIComponent(n)).join(',');
                const res = await fetch(`/api/tags?names=${namesParam}`);
                if (!res.ok) continue;

                const tags = await res.json();
                chunk.forEach(n => result[n] = null);
                tags.forEach(t => {
                    const norm = t.name.toLowerCase().trim();
                    result[norm] = t;
                    if (t && t.category) {
                        this.tagCategoryCache.set(norm, t.category);
                    }
                });
            } catch (e) {
                console.error('Error checking tag batch chunk:', e);
            }
        }
        return result;
    }

    // Check if tag or alias exists (for admin)
    async checkTagOrAliasExists(tagName) {
        if (!tagName || !tagName.trim()) return false;
        const normalized = tagName.toLowerCase().trim();

        try {
            // Check if it's a tag
            const tagRes = await fetch(`/api/tags/${encodeURIComponent(normalized)}`);
            if (tagRes.ok) {
                return true;
            }

            // Check if it's an alias
            const aliasRes = await fetch(`/api/admin/check-alias?name=${encodeURIComponent(normalized)}`);
            if (aliasRes.ok) {
                const data = await aliasRes.json();
                return data.exists;
            }

            return false;
        } catch (e) {
            console.error('Error checking tag/alias:', e);
            return false;
        }
    }

    // Validate and style tags in a contenteditable input
    async validateAndStyleTags(inputElement, options = {}) {
        const {
            validationCache = this.tagValidationCache,
            checkFunction = null,
            invertLogic = false, // If true, invalid means exists (for admin new tags)
            allowWildcards = false, // If true, tokens containing * are never marked invalid
            highlightTags = null, // Set of tag names (lowercase) to highlight as new
            impliedTags = null // Map or object of lowercase tag -> implied_by groups
        } = options;

        const effectiveCheckFunction = checkFunction || ((tag) => this.checkTagExists(tag));

        if (!inputElement) return;

        const text = this.getPlainTextFromDiv(inputElement);
        const cursorPos = this.getCursorPosition(inputElement);

        // Split by whitespace
        const parts = text.split(/(\s+)/);
        const tags = [];

        // Check each non-whitespace part
        const uncachedTags = new Set();
        for (let part of parts) {
            if (part.trim()) {
                const normalized = part.trim().toLowerCase();
                if (!validationCache.has(normalized)) {
                    uncachedTags.add(normalized);
                }
            }
        }

        // Batch fetch uncached tags if possible (only when using default tag existence check)
        if (!checkFunction && uncachedTags.size > 0) {
            const results = await this.checkTagsBatch(Array.from(uncachedTags));
            for (let tag of uncachedTags) {
                if (results.hasOwnProperty(tag)) {
                    validationCache.set(tag, !!results[tag]);
                } else {
                    // Fallback to individual check if not in batch results
                    const exists = await effectiveCheckFunction(tag);
                    validationCache.set(tag, exists);
                }
            }
        } else if (uncachedTags.size > 0) {
            for (let tag of uncachedTags) {
                const exists = await effectiveCheckFunction(tag);
                validationCache.set(tag, exists);
            }
        }

        for (let part of parts) {
            if (part.trim()) {
                const normalized = part.trim().toLowerCase();
                const isValid = validationCache.get(normalized);
                const isWildcardPattern = allowWildcards && (normalized.includes('*') || normalized.includes('?'));
                const isHighlighted = highlightTags && highlightTags.has(normalized);
                const impliedByGroups = this.getImpliedByGroups(impliedTags, normalized);
                const isImplied = impliedByGroups !== null;
                const impliedByDisplay = isImplied ? this.formatImpliedByGroups(impliedByGroups) : '';

                let shouldMarkInvalid;
                if (invertLogic) {
                    // When invertLogic is true (e.g. creating new tags), existing tags are invalid (red).
                    shouldMarkInvalid = isValid;
                } else {
                    // Normal mode: valid if it exists in the DB or if it's a valid wildcard pattern.
                    shouldMarkInvalid = !(isValid || isWildcardPattern);
                }

                tags.push({
                    text: part,
                    isInvalid: shouldMarkInvalid,
                    isHighlighted: isHighlighted,
                    isImplied: isImplied,
                    impliedByDisplay: impliedByDisplay
                });
            } else {
                tags.push({ text: part, isWhitespace: true });
            }
        }

        // Build styled HTML with escaped content
        let html = '';
        for (let tag of tags) {
            if (tag.isWhitespace) {
                html += escapeHtml(tag.text);
            } else if (tag.isInvalid) {
                html += `<span class="invalid-tag">${escapeHtml(tag.text)}</span>`;
            } else if (tag.isHighlighted || tag.isImplied) {
                const classes = [];
                if (tag.isHighlighted) classes.push('new-tag');
                if (tag.isImplied) classes.push('implied-tag');
                const attr = tag.isImplied
                    ? ` data-implied-by="${escapeHtml(tag.impliedByDisplay)}"`
                    : '';
                html += `<span class="${classes.join(' ')}"${attr}>${escapeHtml(tag.text)}</span>`;
            } else {
                html += escapeHtml(tag.text);
            }
        }

        const currentText = this.getPlainTextFromDiv(inputElement);
        if (currentText !== text) {
            return;
        }

        // Update content if changed
        if (inputElement.innerHTML !== html) {
            const isFocused = document.activeElement === inputElement;
            inputElement.innerHTML = html || '';
            if (isFocused) {
                inputElement.focus();
            }
            this.setCursorPosition(inputElement, cursorPos);
        }
    }

    wildcardToRegex(pattern) {
        const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&');
        const regexStr = '^' + escaped.replace(/\*/g, '.*').replace(/\?/g, '.?') + '$';
        return new RegExp(regexStr, 'i');
    }

    pruneExpandedTriggers(inputElement, expandedTriggers, extraTags = []) {
        if (!(expandedTriggers instanceof Set) || expandedTriggers.size === 0 || !inputElement) {
            return;
        }
        const text = this.getPlainTextFromDiv(inputElement);
        const visibleTags = text.split(/\s+/).filter(t => t.length > 0);
        const activeLower = new Set(visibleTags.map(t => t.toLowerCase()));
        for (const extra of (extraTags || [])) {
            const lower = String(extra || '').toLowerCase().trim();
            if (lower) activeLower.add(lower);
        }
        for (const trig of Array.from(expandedTriggers)) {
            if (!activeLower.has(trig)) {
                expandedTriggers.delete(trig);
            }
        }
    }

    pruneImpliedTags(inputElement, impliedTags, extraTags = []) {
        if (!impliedTags || !inputElement) return;

        const text = this.getPlainTextFromDiv(inputElement);
        const visibleTags = text.split(/\s+/).filter(t => t.length > 0);
        const activeLower = new Set(visibleTags.map(t => t.toLowerCase()));
        for (const extra of (extraTags || [])) {
            const lower = String(extra || '').toLowerCase().trim();
            if (lower) activeLower.add(lower);
        }

        if (impliedTags instanceof Map) {
            for (const key of Array.from(impliedTags.keys())) {
                if (!activeLower.has(key.toLowerCase())) {
                    impliedTags.delete(key);
                }
            }
        } else if (impliedTags instanceof Set) {
            for (const key of Array.from(impliedTags)) {
                if (!activeLower.has(key.toLowerCase())) {
                    impliedTags.delete(key);
                }
            }
        } else if (typeof impliedTags === 'object') {
            for (const key of Object.keys(impliedTags)) {
                if (!activeLower.has(key.toLowerCase())) {
                    delete impliedTags[key];
                }
            }
        }
    }

    // Call POST /api/tag-implications/expand with the tags currently in inputElement.
    // Returns true if any implied tags were inserted or recorded (caller may want to re-validate).
    async expandImplications(inputElement, options = {}) {
        const {
            extraTags = [],
            expandedTriggers = null,
            impliedTags = null,
            onImplicationExpanded = null,
            hideImplied = false
        } = options;

        this.pruneExpandedTriggers(inputElement, expandedTriggers, extraTags);
        if (impliedTags) {
            this.pruneImpliedTags(inputElement, impliedTags, extraTags);
        }

        const text = this.getPlainTextFromDiv(inputElement);
        const visibleTags = text.split(/\s+/).filter(t => t.length > 0);
        const seenLower = new Set(visibleTags.map(t => t.toLowerCase()));
        const allCurrentTags = [...visibleTags];
        for (const extra of (extraTags || [])) {
            const lower = String(extra || '').toLowerCase().trim();
            if (lower && !seenLower.has(lower)) {
                seenLower.add(lower);
                allCurrentTags.push(extra);
            }
        }
        if (allCurrentTags.length === 0) return false;

        let newTagsPayload = null;
        if (expandedTriggers instanceof Set) {
            const unexpanded = allCurrentTags.filter(t => !expandedTriggers.has(t.toLowerCase()));
            if (unexpanded.length === 0) {
                return false;
            }
            newTagsPayload = unexpanded;
        }

        let data;
        try {
            const body = { tags: allCurrentTags };
            if (newTagsPayload !== null) {
                body.new_tags = newTagsPayload;
            }
            const response = await fetch('/api/tag-implications/expand', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            if (!response.ok) return false;
            data = await response.json();
        } catch (e) {
            console.error('Error expanding implications:', e);
            return false;
        }

        if (expandedTriggers instanceof Set && newTagsPayload) {
            for (const t of newTagsPayload) {
                expandedTriggers.add(t.toLowerCase());
            }
        }

        const impliedTagsList = (data.implied_tags || []).filter(name => {
            return !allCurrentTags.some(t => t.toLowerCase() === name.toLowerCase());
        });
        if (impliedTagsList.length === 0) return false;

        if (expandedTriggers instanceof Set) {
            for (const name of impliedTagsList) {
                expandedTriggers.add(name.toLowerCase());
            }
        }

        for (const name of impliedTagsList) {
            this.tagValidationCache.set(name.toLowerCase().trim(), true);
        }

        if (typeof onImplicationExpanded === 'function') {
            onImplicationExpanded(data.implied_by || {}, impliedTagsList, inputElement);
        }

        if (hideImplied) {
            return true;
        }

        const insertText = impliedTagsList.join(' ') + ' ';

        inputElement.focus();
        const sel = window.getSelection();
        if (!sel.rangeCount || !inputElement.contains(sel.anchorNode)) {
            const range = document.createRange();
            range.selectNodeContents(inputElement);
            range.collapse(false);
            sel.removeAllRanges();
            sel.addRange(range);
        }

        document.execCommand('insertText', false, insertText);
        return true;
    }

    // Setup tag input event listeners
    setupTagInput(inputElement, inputId, options = {}) {
        const {
            onValidate = null,
            validateDelay = 300,
            validationCache = this.tagValidationCache,
            checkFunction = null,
            invertLogic = false,
            expandImplications = true,
            allowWildcards = false, // If true, tokens containing * are never marked invalid
            getHighlightTags = null, // Function that returns a Set of tags to highlight
            getImpliedTags = null,
            getHiddenImpliedTags = null,
            getExpandedTriggers = null,
            onImplicationExpanded = null,
            isHideImpliedActive = null
        } = options;

        if (!inputElement) return;

        // Abort and replace any existing listeners for this inputId to prevent duplicates
        if (this.abortControllers.has(inputId)) {
            this.abortControllers.get(inputId).abort();
        }
        const controller = new AbortController();
        const { signal } = controller;
        this.abortControllers.set(inputId, controller);

        // Strip IDE-injected whitespace (newlines/indents) from empty inputs
        if (inputElement.textContent.trim() === '') {
            inputElement.innerHTML = '';
        }

        this.attachImpliedTagTooltip(inputElement, signal);

        // Handle input events
        inputElement.addEventListener('input', () => {
            const extraTags = getHiddenImpliedTags ? Array.from(getHiddenImpliedTags(inputElement) || []) : [];
            if (getExpandedTriggers) {
                const expandedTriggers = getExpandedTriggers(inputElement);
                this.pruneExpandedTriggers(inputElement, expandedTriggers, extraTags);
            }
            if (getImpliedTags) {
                const impliedTags = getImpliedTags(inputElement);
                this.pruneImpliedTags(inputElement, impliedTags, extraTags);
            }
            if (this.validationTimeouts.has(inputId)) {
                clearTimeout(this.validationTimeouts.get(inputId));
            }
            const timeout = setTimeout(async () => {
                const highlightTags = getHighlightTags ? getHighlightTags(inputElement) : null;
                const impliedTags = getImpliedTags ? getImpliedTags(inputElement) : null;
                await this.validateAndStyleTags(inputElement, {
                    validationCache,
                    checkFunction,
                    invertLogic,
                    allowWildcards,
                    highlightTags,
                    impliedTags
                });
                if (onValidate) onValidate();
            }, validateDelay);
            this.validationTimeouts.set(inputId, timeout);
        }, { signal });

        // Immediate validation and implications expansion on space
        inputElement.addEventListener('keyup', async (e) => {
            if (e.key === ' ') {
                const extraTags = getHiddenImpliedTags ? Array.from(getHiddenImpliedTags(inputElement) || []) : [];
                if (getExpandedTriggers) {
                    const expandedTriggers = getExpandedTriggers(inputElement);
                    this.pruneExpandedTriggers(inputElement, expandedTriggers, extraTags);
                }
                if (getImpliedTags) {
                    const impliedTags = getImpliedTags(inputElement);
                    this.pruneImpliedTags(inputElement, impliedTags, extraTags);
                }
                if (this.validationTimeouts.has(inputId)) {
                    clearTimeout(this.validationTimeouts.get(inputId));
                }

                let highlightTags = getHighlightTags ? getHighlightTags(inputElement) : null;
                let impliedTags = getImpliedTags ? getImpliedTags(inputElement) : null;
                await this.validateAndStyleTags(inputElement, {
                    validationCache,
                    checkFunction,
                    invertLogic,
                    allowWildcards,
                    highlightTags,
                    impliedTags
                });
                if (expandImplications) {
                    const expandedTriggers = getExpandedTriggers ? getExpandedTriggers(inputElement) : null;
                    const hideImplied = isHideImpliedActive
                        ? Boolean(isHideImpliedActive(inputElement))
                        : false;
                    const added = await this.expandImplications(inputElement, {
                        extraTags,
                        expandedTriggers,
                        impliedTags: getImpliedTags ? getImpliedTags(inputElement) : null,
                        onImplicationExpanded,
                        hideImplied
                    });
                    if (added) {
                        highlightTags = getHighlightTags ? getHighlightTags(inputElement) : null;
                        impliedTags = getImpliedTags ? getImpliedTags(inputElement) : null;
                        await this.validateAndStyleTags(inputElement, {
                            validationCache,
                            checkFunction,
                            invertLogic,
                            allowWildcards,
                            highlightTags,
                            impliedTags
                        });
                    }
                }
                if (onValidate) onValidate();
            }
        }, { signal });

        // Prevent default Enter behavior
        inputElement.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
            }
        }, { signal });

        // Paste as plain text
        inputElement.addEventListener('paste', (e) => {
            e.preventDefault();
            const text = e.clipboardData.getData('text/plain');
            document.execCommand('insertText', false, text);
        }, { signal });
    }

    // Get valid tags from input (filter out invalid ones)
    getValidTagsFromInput(inputElement, validationCache = this.tagValidationCache) {
        const text = this.getPlainTextFromDiv(inputElement);
        const allTags = text.split(/\s+/).filter(t => t.length > 0);

        const validTags = [];
        for (const tag of allTags) {
            const normalized = tag.toLowerCase().trim();
            const isValid = validationCache.get(normalized);
            if (isValid !== false) {
                validTags.push(tag);
            }
        }

        return validTags;
    }

    // Clear validation cache
    clearCache() {
        this.tagValidationCache.clear();
        this.tagCategoryCache.clear();
    }

    // Clear all timeouts
    clearTimeouts() {
        for (const timeout of this.validationTimeouts.values()) {
            clearTimeout(timeout);
        }
        this.validationTimeouts.clear();
        for (const controller of this.abortControllers.values()) {
            controller.abort();
        }
        this.abortControllers.clear();
    }

    // Cleanup
    destroy() {
        this.clearTimeouts();
        this.clearCache();
    }
}
