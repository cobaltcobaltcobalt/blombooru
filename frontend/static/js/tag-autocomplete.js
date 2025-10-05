class TagAutocomplete {
    constructor(inputElement) {
        this.input = inputElement;
        this.dropdown = null;
        this.currentFocus = -1;
        this.debounceTimer = null;
        
        this.init();
    }
    
    init() {
        // Create dropdown element
        this.dropdown = document.createElement('div');
        this.dropdown.className = 'autocomplete-dropdown';
        this.input.parentNode.appendChild(this.dropdown);
        
        // Setup event listeners
        this.input.addEventListener('input', (e) => this.onInput(e));
        this.input.addEventListener('keydown', (e) => this.onKeyDown(e));
        
        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            if (e.target !== this.input) {
                this.hideDropdown();
            }
        });
    }
    
    onInput(e) {
        clearTimeout(this.debounceTimer);
        
        const value = this.getCurrentTag();
        
        if (value.length < 1) {
            this.hideDropdown();
            return;
        }
        
        this.debounceTimer = setTimeout(() => {
            this.fetchSuggestions(value);
        }, 200);
    }
    
    getCurrentTag() {
        const cursorPos = this.input.selectionStart;
        const text = this.input.value.substring(0, cursorPos);
        const tags = text.split(',');
        return tags[tags.length - 1].trim();
    }
    
    async fetchSuggestions(query) {
        try {
            const response = await fetch(`/api/tags/autocomplete?q=${encodeURIComponent(query)}`);
            const suggestions = await response.json();
            this.showSuggestions(suggestions);
        } catch (error) {
            console.error('Error fetching suggestions:', error);
        }
    }
    
    showSuggestions(suggestions) {
        if (suggestions.length === 0) {
            this.hideDropdown();
            return;
        }
        
        this.dropdown.innerHTML = '';
        
        suggestions.forEach((suggestion, index) => {
            const item = document.createElement('div');
            item.className = 'autocomplete-item';
            
            const name = document.createElement('span');
            name.className = `tag-name tag ${suggestion.category}`;
            name.textContent = suggestion.name;
            
            const count = document.createElement('span');
            count.className = 'tag-count';
            count.textContent = suggestion.count;
            
            item.appendChild(name);
            item.appendChild(count);
            
            item.addEventListener('click', () => {
                this.selectSuggestion(suggestion.name);
            });
            
            this.dropdown.appendChild(item);
        });
        
        this.dropdown.classList.add('show');
        this.currentFocus = -1;
    }
    
    hideDropdown() {
        this.dropdown.classList.remove('show');
        this.currentFocus = -1;
    }
    
    selectSuggestion(tagName) {
        const cursorPos = this.input.selectionStart;
        const text = this.input.value;
        const beforeCursor = text.substring(0, cursorPos);
        const afterCursor = text.substring(cursorPos);
        
        const tags = beforeCursor.split(',');
        tags[tags.length - 1] = ' ' + tagName;
        
        const newValue = tags.join(',') + ',' + afterCursor;
        this.input.value = newValue;
        
        // Set cursor position after the inserted tag
        const newCursorPos = tags.join(',').length + 1;
        this.input.setSelectionRange(newCursorPos, newCursorPos);
        
        this.hideDropdown();
        this.input.focus();
    }
    
    onKeyDown(e) {
        const items = this.dropdown.querySelectorAll('.autocomplete-item');
        
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            this.currentFocus++;
            this.setActive(items);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            this.currentFocus--;
            this.setActive(items);
        } else if (e.key === 'Enter') {
            if (this.currentFocus > -1 && items[this.currentFocus]) {
                e.preventDefault();
                items[this.currentFocus].click();
            }
        } else if (e.key === 'Escape') {
            this.hideDropdown();
        }
    }
    
    setActive(items) {
        if (!items || items.length === 0) return;
        
        // Remove active class from all items
        items.forEach(item => item.classList.remove('active'));
        
        // Wrap around
        if (this.currentFocus >= items.length) this.currentFocus = 0;
        if (this.currentFocus < 0) this.currentFocus = items.length - 1;
        
        // Add active class to current item
        items[this.currentFocus].classList.add('active');
        items[this.currentFocus].scrollIntoView({ block: 'nearest' });
    }
}

// Initialize tag autocomplete on all tag inputs
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.tag-input').forEach(input => {
        new TagAutocomplete(input);
    });
});
