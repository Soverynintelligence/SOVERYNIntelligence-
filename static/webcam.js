// SOVERYN Webcam Integration for Aetheria
// Provides real-time vision capabilities

class SoverynWebcam {
    constructor() {
        this.stream = null;
        this.video = null;
        this.canvas = null;
        this.isStreaming = false;
        this.continuousMode = false;
        this.continuousInterval = null;
    }

    async initialize() {
        try {
            // Request webcam access
            this.stream = await navigator.mediaDevices.getUserMedia({
                video: {
                    width: { ideal: 1280 },
                    height: { ideal: 720 },
                    facingMode: 'user'
                },
                audio: false
            });

            // Setup video element
            this.video = document.getElementById('webcamVideo');
            this.video.srcObject = this.stream;
            this.video.play();

            this.isStreaming = true;
            console.log('[Webcam] Initialized successfully');
            return true;

        } catch (error) {
            console.error('[Webcam] Error accessing camera:', error);
            alert('Could not access webcam. Please check permissions.');
            return false;
        }
    }

    stop() {
        if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
            this.isStreaming = false;
            
            if (this.video) {
                this.video.srcObject = null;
            }
            
            this.stopContinuous();
            console.log('[Webcam] Stopped');
        }
    }

    captureFrame() {
        if (!this.isStreaming || !this.video) {
            console.error('[Webcam] Not streaming');
            return null;
        }

        // Create canvas if doesn't exist
        if (!this.canvas) {
            this.canvas = document.createElement('canvas');
        }

        // Set canvas size to video dimensions
        this.canvas.width = this.video.videoWidth;
        this.canvas.height = this.video.videoHeight;

        // Draw current video frame to canvas
        const ctx = this.canvas.getContext('2d');
        ctx.drawImage(this.video, 0, 0);

        // Convert to base64 image
        const dataURL = this.canvas.toDataURL('image/jpeg', 0.8);
        
        console.log('[Webcam] Frame captured');
        return dataURL;
    }

    async analyzeCurrentView(prompt = "What do you see?") {
        const frame = this.captureFrame();
        if (!frame) {
            return null;
        }

        try {
            // Show loading indicator
            showVisionLoading();

            const response = await fetch('/analyze_webcam', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    image: frame,
                    prompt: prompt,
                    agent: currentAgent
                })
            });

            const data = await response.json();
            
            hideVisionLoading();
            
            if (data.description) {
                return data.description;
            } else {
                console.error('[Webcam] Analysis failed:', data.error);
                return null;
            }

        } catch (error) {
            console.error('[Webcam] Analysis error:', error);
            hideVisionLoading();
            return null;
        }
    }

    startContinuous(intervalSeconds = 10) {
        if (this.continuousInterval) {
            this.stopContinuous();
        }

        this.continuousMode = true;
        
        // Analyze immediately
        this.analyzeContinuous();
        
        // Then analyze every N seconds
        this.continuousInterval = setInterval(() => {
            this.analyzeContinuous();
        }, intervalSeconds * 1000);

        console.log(`[Webcam] Continuous mode started (${intervalSeconds}s interval)`);
    }

    stopContinuous() {
        if (this.continuousInterval) {
            clearInterval(this.continuousInterval);
            this.continuousInterval = null;
        }
        this.continuousMode = false;
        console.log('[Webcam] Continuous mode stopped');
    }

    async analyzeContinuous() {
        const description = await this.analyzeCurrentView("Describe what you see briefly.");
        
        if (description) {
            // Store in session context for Aetheria to reference
            window.currentVisionContext = description;
            
            // Update UI indicator
            updateVisionIndicator(description);
            
            console.log('[Webcam] Vision context updated:', description.substring(0, 50) + '...');
        }
    }
}

// UI Helper Functions
function showVisionLoading() {
    const indicator = document.getElementById('visionLoadingIndicator');
    if (indicator) {
        indicator.style.display = 'block';
    }
}

function hideVisionLoading() {
    const indicator = document.getElementById('visionLoadingIndicator');
    if (indicator) {
        indicator.style.display = 'none';
    }
}

function updateVisionIndicator(text) {
    const indicator = document.getElementById('visionContextIndicator');
    if (indicator) {
        indicator.textContent = '👁️ Seeing: ' + text.substring(0, 60) + '...';
        indicator.style.display = 'block';
    }
}

// Global instance
let soverynWebcam = null;

// Initialize when requested
async function initializeWebcam() {
    if (!soverynWebcam) {
        soverynWebcam = new SoverynWebcam();
    }
    
    const success = await soverynWebcam.initialize();
    return success;
}

async function captureAndAsk() {
    if (!soverynWebcam || !soverynWebcam.isStreaming) {
        alert('Please open the camera first!');
        return;
    }

    const customPrompt = document.getElementById('visionPrompt').value.trim();
    const prompt = customPrompt || "What do you see in this image?";

    const description = await soverynWebcam.analyzeCurrentView(prompt);
    
    if (description) {
        // Add to conversation as if Aetheria responded
        addMessageToUI('agent', description);
        
        // Clear prompt
        document.getElementById('visionPrompt').value = '';
    }
}
async function captureAndAsk() {
    if (!soverynWebcam || !soverynWebcam.isStreaming) {
        alert('Please open the camera first!');
        return;
    }

    const customPrompt = document.getElementById('visionPrompt').value.trim();
    const prompt = customPrompt || "What do you see in this image?";

    const description = await soverynWebcam.analyzeCurrentView(prompt);
    
    if (description) {
        addMessageToUI('user', `👁️ ${prompt}`);
        addMessageToUI('agent', description);
        
        // Save to conversation history so she remembers
        if (currentChatId && conversations[currentChatId]) {
            if (!conversations[currentChatId].messages) conversations[currentChatId].messages = [];
            conversations[currentChatId].messages.push(
                { role: 'user', content: `👁️ ${prompt}` },
                { role: 'agent', content: description }
            );
        }
        
        document.getElementById('visionPrompt').value = '';
    }
}
function toggleContinuousVision() {
    if (!soverynWebcam || !soverynWebcam.isStreaming) {
        alert('Please open the camera first!');
        return;
    }

    const btn = document.getElementById('continuousVisionBtn');
    
    if (!soverynWebcam.continuousMode) {
        soverynWebcam.startContinuous(10); // Update every 10 seconds
        btn.textContent = '⏸️ Pause Continuous';
        btn.style.background = 'rgba(231, 76, 60, 0.2)';
        btn.style.borderColor = 'rgba(231, 76, 60, 0.4)';
        btn.style.color = '#e74c3c';
    } else {
        soverynWebcam.stopContinuous();
        btn.textContent = '▶️ Start Continuous';
        btn.style.background = 'rgba(52, 152, 219, 0.2)';
        btn.style.borderColor = 'rgba(52, 152, 219, 0.4)';
        btn.style.color = '#3498db';
    }
}

// Inject vision context into messages when continuous mode is active
function getVisionContext() {
    if (window.currentVisionContext && soverynWebcam && soverynWebcam.continuousMode) {
        return `\n\n[Current Visual Context: ${window.currentVisionContext}]`;
    }
    return '';
}
