/**
 * Divvy Tutorial System
 * A lightweight, self-contained spotlight tutorial for onboarding users
 * 
 * Features:
 * - Self-contained: injects its own CSS and HTML
 * - No external dependencies
 * - Fully configurable
 * - Keyboard navigation (Escape to skip, Arrow keys to navigate)
 * 
 * Usage:
 *   const tutorial = new Tutorial(steps, options);
 *   tutorial.start();
 */

class Tutorial {
    static STYLES_INJECTED = false;
    
    constructor(steps = [], options = {}) {
        this.steps = steps;
        this.currentStep = 0;
        this.isActive = false;
        
        // Default options
        this.options = {
            storageKey: 'tutorialCompleted',
            autoStart: true,
            autoStartDelay: 1000,
            padding: 8,
            showHelpButton: true,
            helpButtonPosition: { bottom: '24px', right: '24px' },
            texts: {
                skip: 'Saltar tour',
                next: 'Siguiente',
                finish: '¡Empezar!',
                helpButton: '?'
            },
            onComplete: null,
            onSkip: null,
            onStepChange: null,
            ...options
        };
        
        // Inject styles once
        if (!Tutorial.STYLES_INJECTED) {
            this.injectStyles();
            Tutorial.STYLES_INJECTED = true;
        }
        
        // Create DOM elements
        this.createElements();
        this.bindEvents();
        
        // Auto-start if enabled and not completed
        const completed = this.isCompleted();
        console.log('Tutorial init:', { 
            storageKey: this.options.storageKey, 
            completed: completed,
            autoStart: this.options.autoStart,
            storedValue: localStorage.getItem(this.options.storageKey)
        });
        
        if (this.options.autoStart && !completed) {
            console.log('Tutorial will auto-start in', this.options.autoStartDelay, 'ms');
            setTimeout(() => this.start(), this.options.autoStartDelay);
        }
    }
    
    /**
     * Inject tutorial CSS styles
     */
    injectStyles() {
        const styles = document.createElement('style');
        styles.id = 'tutorial-styles';
        styles.textContent = `
            /* Tutorial Overlay */
            .tutorial-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                z-index: 9998;
                pointer-events: none;
                opacity: 0;
                visibility: hidden;
                transition: opacity 0.3s ease, visibility 0.3s ease;
            }
            
            .tutorial-overlay.active {
                pointer-events: auto;
                opacity: 1;
                visibility: visible;
            }
            
            .tutorial-spotlight {
                position: absolute;
                border-radius: 12px;
                box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.75);
                transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
                z-index: 9999;
                pointer-events: none;
                opacity: 0;
            }
            
            .tutorial-spotlight.visible {
                opacity: 1;
            }
            
            .tutorial-spotlight::before {
                content: '';
                position: absolute;
                inset: -4px;
                border: 2px solid #6366f1;
                border-radius: 14px;
                animation: tutorial-pulse-ring 2s ease-out infinite;
            }
            
            @keyframes tutorial-pulse-ring {
                0% { transform: scale(1); opacity: 1; }
                100% { transform: scale(1.1); opacity: 0; }
            }
            
            .tutorial-popover {
                position: absolute;
                background: #1e1e2e;
                border: 1px solid #3d3d5c;
                border-radius: 16px;
                padding: 1.25rem;
                max-width: 320px;
                box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
                z-index: 10000;
                opacity: 0;
                transform: translateY(10px);
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            }
            
            .tutorial-popover.active {
                opacity: 1;
                transform: translateY(0);
            }
            
            .tutorial-popover::before {
                content: '';
                position: absolute;
                width: 12px;
                height: 12px;
                background: #1e1e2e;
                border: 1px solid #3d3d5c;
                border-right: none;
                border-bottom: none;
                transform: rotate(45deg);
            }
            
            .tutorial-popover.arrow-top::before { top: -7px; left: 24px; }
            .tutorial-popover.arrow-bottom::before { bottom: -7px; left: 24px; transform: rotate(225deg); }
            .tutorial-popover.arrow-left::before { left: -7px; top: 24px; transform: rotate(-45deg); }
            .tutorial-popover.arrow-right::before { right: -7px; top: 24px; transform: rotate(135deg); }
            
            .tutorial-step-indicator {
                display: flex;
                gap: 6px;
                margin-bottom: 1rem;
            }
            
            .tutorial-step-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #3d3d5c;
                transition: all 0.2s;
            }
            
            .tutorial-step-dot.active {
                background: #6366f1;
                width: 24px;
                border-radius: 4px;
            }
            
            .tutorial-step-dot.completed {
                background: #10b981;
            }
            
            .tutorial-title {
                font-size: 1.1rem;
                font-weight: 600;
                color: #f5f5f5;
                margin-bottom: 0.5rem;
            }
            
            .tutorial-description {
                font-size: 0.9rem;
                color: #a0a0b0;
                line-height: 1.5;
                margin-bottom: 1rem;
            }
            
            .tutorial-actions {
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 0.75rem;
            }
            
            .tutorial-skip {
                background: none;
                border: none;
                color: #6b6b80;
                font-size: 0.85rem;
                cursor: pointer;
                padding: 0.5rem;
                transition: color 0.2s;
            }
            
            .tutorial-skip:hover {
                color: #a0a0b0;
            }
            
            .tutorial-next {
                background: #6366f1;
                color: white;
                border: none;
                padding: 0.6rem 1.25rem;
                border-radius: 8px;
                font-size: 0.9rem;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.2s;
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            
            .tutorial-next:hover {
                background: #818cf8;
                transform: translateY(-1px);
            }
            
            .tutorial-help-btn {
                position: fixed;
                width: 48px;
                height: 48px;
                border-radius: 50%;
                background: linear-gradient(135deg, #6366f1, #8b5cf6);
                border: none;
                color: white;
                font-size: 1.4rem;
                font-weight: bold;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 9000;
                transition: all 0.2s;
                box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4);
            }
            
            .tutorial-help-btn:hover {
                transform: scale(1.1);
                box-shadow: 0 6px 24px rgba(99, 102, 241, 0.5);
            }
        `;
        document.head.appendChild(styles);
    }
    
    /**
     * Create tutorial DOM elements
     */
    createElements() {
        // Main overlay container
        this.overlay = document.createElement('div');
        this.overlay.className = 'tutorial-overlay';
        this.overlay.id = 'tutorial-overlay';
        
        // Spotlight element
        this.spotlight = document.createElement('div');
        this.spotlight.className = 'tutorial-spotlight';
        
        // Popover element
        this.popover = document.createElement('div');
        this.popover.className = 'tutorial-popover';
        this.popover.innerHTML = `
            <div class="tutorial-step-indicator"></div>
            <div class="tutorial-title"></div>
            <div class="tutorial-description"></div>
            <div class="tutorial-actions">
                <button class="tutorial-skip">${this.options.texts.skip}</button>
                <button class="tutorial-next">
                    ${this.options.texts.next} <span>→</span>
                </button>
            </div>
        `;
        
        // Assemble
        this.overlay.appendChild(this.spotlight);
        this.overlay.appendChild(this.popover);
        document.body.appendChild(this.overlay);
        
        // Cache element references
        this.stepsContainer = this.popover.querySelector('.tutorial-step-indicator');
        this.titleEl = this.popover.querySelector('.tutorial-title');
        this.descEl = this.popover.querySelector('.tutorial-description');
        this.nextBtn = this.popover.querySelector('.tutorial-next');
        this.skipBtn = this.popover.querySelector('.tutorial-skip');
        
        // Create help button if enabled
        if (this.options.showHelpButton) {
            this.createHelpButton();
        }
    }
    
    /**
     * Create floating help button
     */
    createHelpButton() {
        this.helpBtn = document.createElement('button');
        this.helpBtn.className = 'tutorial-help-btn';
        this.helpBtn.title = 'Ver tutorial';
        this.helpBtn.textContent = this.options.texts.helpButton;
        
        // Position
        Object.assign(this.helpBtn.style, this.options.helpButtonPosition);
        
        this.helpBtn.addEventListener('click', () => {
            this.reset();
            this.start();
        });
        
        document.body.appendChild(this.helpBtn);
    }
    
    /**
     * Bind event listeners
     */
    bindEvents() {
        this.nextBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.next();
        });
        this.skipBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            this.skip();
        });
        
        // Click on overlay (outside popover) to advance
        this.overlay.addEventListener('click', (e) => {
            if (e.target === this.overlay || e.target === this.spotlight) {
                this.next();
            }
        });
        
        // Prevent popover clicks from propagating
        this.popover.addEventListener('click', (e) => {
            e.stopPropagation();
        });
        
        // Keyboard navigation
        this._keyHandler = (e) => {
            if (!this.isActive) return;
            if (e.key === 'Escape') this.skip();
            if (e.key === 'ArrowRight' || e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.next();
            }
            if (e.key === 'ArrowLeft') this.prev();
        };
        document.addEventListener('keydown', this._keyHandler);
        
        // Handle window resize
        this._resizeHandler = () => {
            if (this.isActive) {
                // Re-position after a small delay
                setTimeout(() => this.showStep(this.currentStep), 100);
            }
        };
        window.addEventListener('resize', this._resizeHandler);
        
        // Also reposition on scroll
        this._scrollHandler = () => {
            if (this.isActive) {
                const step = this.steps[this.currentStep];
                if (step && step.element) {
                    const el = document.querySelector(step.element);
                    if (el) {
                        const rect = el.getBoundingClientRect();
                        const padding = this.options.padding;
                        this.spotlight.style.top = (rect.top - padding) + 'px';
                        this.spotlight.style.left = (rect.left - padding) + 'px';
                    }
                }
            }
        };
        window.addEventListener('scroll', this._scrollHandler, true);
    }
    
    /**
     * Check if tutorial was already completed
     */
    isCompleted() {
        return localStorage.getItem(this.options.storageKey) === 'true';
    }
    
    /**
     * Mark tutorial as completed
     */
    markCompleted() {
        localStorage.setItem(this.options.storageKey, 'true');
        console.log('Tutorial marked as completed:', this.options.storageKey);
    }
    
    /**
     * Reset tutorial completion status
     */
    reset() {
        localStorage.removeItem(this.options.storageKey);
    }
    
    /**
     * Start the tutorial
     */
    start() {
        console.log('Tutorial starting...');
        this.currentStep = 0;
        this.isActive = true;
        
        // Clear any lingering inline styles
        this.spotlight.style.cssText = '';
        this.popover.style.cssText = '';
        this.overlay.style.cssText = '';
        
        // Activate overlay (CSS handles visibility)
        this.overlay.classList.add('active');
        
        this.showStep(0);
    }
    
    /**
     * Clean up and hide all tutorial elements
     */
    cleanup() {
        this.isActive = false;
        
        // Remove all active/visible classes
        this.overlay.classList.remove('active');
        this.popover.classList.remove('active');
        this.spotlight.classList.remove('visible');
        
        // Force cleanup any inline styles
        this.spotlight.style.cssText = '';
        this.popover.style.cssText = '';
        this.overlay.style.cssText = '';
        
        // Ensure body scroll is restored
        document.body.style.overflow = '';
        
        console.log('Tutorial cleanup complete');
    }
    
    /**
     * End the tutorial (completed)
     */
    end() {
        this.cleanup();
        this.markCompleted();
        
        if (this.options.onComplete) {
            this.options.onComplete();
        }
    }
    
    /**
     * Skip the tutorial
     */
    skip() {
        this.cleanup();
        this.markCompleted();
        
        if (this.options.onSkip) {
            this.options.onSkip();
        }
    }
    
    /**
     * Go to next step
     */
    next() {
        this.currentStep++;
        if (this.currentStep >= this.steps.length) {
            this.end();
        } else {
            this.showStep(this.currentStep);
        }
    }
    
    /**
     * Go to previous step
     */
    prev() {
        if (this.currentStep > 0) {
            this.currentStep--;
            this.showStep(this.currentStep);
        }
    }
    
    /**
     * Go to specific step
     */
    goTo(stepIndex) {
        if (stepIndex >= 0 && stepIndex < this.steps.length) {
            this.currentStep = stepIndex;
            this.showStep(stepIndex);
        }
    }
    
    /**
     * Show a specific step
     */
    showStep(stepIndex) {
        const step = this.steps[stepIndex];
        if (!step) return;
        
        // Update step indicators
        this.renderStepIndicators(stepIndex);
        
        // Update content
        this.titleEl.innerHTML = step.title || '';
        this.descEl.textContent = step.description || '';
        
        // Update button text for last step
        const isLast = stepIndex === this.steps.length - 1;
        this.nextBtn.innerHTML = isLast 
            ? `${step.finishText || this.options.texts.finish} 🚀`
            : `${step.nextText || this.options.texts.next} <span>→</span>`;
        
        // Position elements
        this.positionElements(step);
        
        // Callback
        if (this.options.onStepChange) {
            this.options.onStepChange(stepIndex, step);
        }
    }
    
    /**
     * Render step indicator dots
     */
    renderStepIndicators(currentIndex) {
        this.stepsContainer.innerHTML = this.steps.map((_, i) => {
            let className = 'tutorial-step-dot';
            if (i === currentIndex) className += ' active';
            if (i < currentIndex) className += ' completed';
            return `<div class="${className}"></div>`;
        }).join('');
    }
    
    /**
     * Position spotlight and popover
     */
    positionElements(step) {
        const padding = this.options.padding;
        
        if (step.element) {
            let targetEl = document.querySelector(step.element);
            
            // Try fallback element if main one not found
            if (!targetEl && step.fallback) {
                targetEl = document.querySelector(step.fallback);
            }
            
            if (targetEl) {
                // Check if element is visible
                const style = window.getComputedStyle(targetEl);
                if (style.display === 'none' || style.visibility === 'hidden') {
                    console.warn('Tutorial: Element hidden, centering popover', step.element);
                    this.showCenteredPopover();
                    return;
                }
                
                // Get initial rect
                let rect = targetEl.getBoundingClientRect();
                
                // Position immediately first
                this.spotlight.classList.add('visible');
                this.spotlight.style.top = (rect.top - padding) + 'px';
                this.spotlight.style.left = (rect.left - padding) + 'px';
                this.spotlight.style.width = (rect.width + padding * 2) + 'px';
                this.spotlight.style.height = (rect.height + padding * 2) + 'px';
                this.positionPopover(rect, step.position || 'bottom');
                
                // Then scroll into view and reposition
                targetEl.scrollIntoView({ 
                    behavior: 'smooth', 
                    block: 'center',
                    inline: 'nearest'
                });
                
                // Update position after scroll
                setTimeout(() => {
                    rect = targetEl.getBoundingClientRect();
                    this.spotlight.style.top = (rect.top - padding) + 'px';
                    this.spotlight.style.left = (rect.left - padding) + 'px';
                    this.spotlight.style.width = (rect.width + padding * 2) + 'px';
                    this.spotlight.style.height = (rect.height + padding * 2) + 'px';
                    this.positionPopover(rect, step.position || 'bottom');
                }, 400);
                return;
            } else {
                console.warn('Tutorial: Element not found', step.element);
            }
        }
        
        // Center if no element
        this.showCenteredPopover();
    }
    
    /**
     * Position popover relative to target element
     */
    positionPopover(rect, position) {
        this.popover.className = 'tutorial-popover active';
        this.popover.style.transform = '';
        
        const popoverWidth = 320;
        const popoverHeight = 200;
        const margin = 16;
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        
        let top, left;
        let arrowClass = '';
        
        // Calculate best position, with fallbacks
        switch (position) {
            case 'right':
                if (rect.right + margin + popoverWidth < viewportWidth) {
                    arrowClass = 'arrow-left';
                    top = Math.max(10, Math.min(rect.top, viewportHeight - popoverHeight - 10));
                    left = rect.right + margin;
                } else {
                    // Fallback to bottom
                    arrowClass = 'arrow-top';
                    top = Math.min(rect.bottom + margin, viewportHeight - popoverHeight - 10);
                    left = Math.max(10, Math.min(rect.left, viewportWidth - popoverWidth - 10));
                }
                break;
            case 'left':
                if (rect.left - margin - popoverWidth > 0) {
                    arrowClass = 'arrow-right';
                    top = Math.max(10, Math.min(rect.top, viewportHeight - popoverHeight - 10));
                    left = rect.left - popoverWidth - margin;
                } else {
                    // Fallback to bottom
                    arrowClass = 'arrow-top';
                    top = Math.min(rect.bottom + margin, viewportHeight - popoverHeight - 10);
                    left = Math.max(10, Math.min(rect.left, viewportWidth - popoverWidth - 10));
                }
                break;
            case 'top':
                if (rect.top - margin - popoverHeight > 0) {
                    arrowClass = 'arrow-bottom';
                    top = rect.top - popoverHeight - margin;
                    left = Math.max(10, Math.min(rect.left, viewportWidth - popoverWidth - 10));
                } else {
                    // Fallback to bottom
                    arrowClass = 'arrow-top';
                    top = Math.min(rect.bottom + margin, viewportHeight - popoverHeight - 10);
                    left = Math.max(10, Math.min(rect.left, viewportWidth - popoverWidth - 10));
                }
                break;
            case 'bottom':
            default:
                arrowClass = 'arrow-top';
                top = Math.min(rect.bottom + margin, viewportHeight - popoverHeight - 10);
                left = Math.max(10, Math.min(rect.left, viewportWidth - popoverWidth - 10));
                break;
        }
        
        this.popover.classList.add(arrowClass);
        this.popover.style.top = top + 'px';
        this.popover.style.left = left + 'px';
    }
    
    /**
     * Show popover in center of screen
     */
    showCenteredPopover() {
        this.spotlight.classList.remove('visible');
        this.popover.className = 'tutorial-popover active';
        this.popover.style.top = '50%';
        this.popover.style.left = '50%';
        this.popover.style.transform = 'translate(-50%, -50%)';
        this.popover.style.maxWidth = '360px';
        
        // Ensure popover is visible
        requestAnimationFrame(() => {
            this.popover.classList.add('active');
        });
    }
    
    /**
     * Add a step dynamically
     */
    addStep(step, index = null) {
        if (index !== null) {
            this.steps.splice(index, 0, step);
        } else {
            this.steps.push(step);
        }
        return this;
    }
    
    /**
     * Remove a step
     */
    removeStep(index) {
        this.steps.splice(index, 1);
        return this;
    }
    
    /**
     * Update steps
     */
    setSteps(steps) {
        this.steps = steps;
        return this;
    }
    
    /**
     * Destroy the tutorial instance
     */
    destroy() {
        document.removeEventListener('keydown', this._keyHandler);
        window.removeEventListener('resize', this._resizeHandler);
        window.removeEventListener('scroll', this._scrollHandler, true);
        this.overlay.remove();
        if (this.helpBtn) this.helpBtn.remove();
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Tutorial;
}
