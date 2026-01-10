class AITagUtils {
    static extractAIData(metadata) {
        if (!metadata) return null;

        // Try ComfyUI format first
        const comfyData = this.extractComfyUIData(metadata);
        if (comfyData) {
            return comfyData;
        }

        // Try SwarmUI/A1111 format
        const locations = [
            metadata.parameters,
            metadata.Parameters,
            metadata.prompt
        ];

        for (const location of locations) {
            if (!location) continue;

            // If it's already an object, return it
            if (typeof location === 'object' && location !== null) {
                return location;
            }

            // If it's a string, try to parse as JSON
            if (typeof location === 'string') {
                // Try JSON parse
                try {
                    const parsed = JSON.parse(location);
                    // Make sure we got an object
                    if (typeof parsed === 'object' && parsed !== null) {
                        return parsed;
                    }
                } catch (e) {
                    // Not JSON - try to parse as A1111 parameter string
                    const a1111Data = this.parseA1111Parameters(location);
                    if (a1111Data && Object.keys(a1111Data).length > 0) {
                        return a1111Data;
                    }
                }
            }
        }

        // Additional fail-safe checks for specific formats that might be object roots
        if (metadata.sui_image_params) {
            return metadata.sui_image_params;
        }

        return null;
    }

    static extractAIPrompt(metadata) {
        const aiData = this.extractAIData(metadata);

        if (!aiData) {
            return null;
        }

        // Extract the positive prompt from the parsed AI data
        const promptLocations = [
            aiData.prompt,
            aiData.Prompt,
            aiData.positive_prompt,
            aiData.positive,
            aiData.sui_image_params?.prompt
        ];

        for (const location of promptLocations) {
            if (location && typeof location === 'string') {
                return location;
            }
        }

        // Fallback: if aiData has a prompt nested somewhere
        for (const [key, value] of Object.entries(aiData)) {
            if (key.toLowerCase().includes('prompt') &&
                !key.toLowerCase().includes('negative') &&
                typeof value === 'string') {
                return value;
            }
        }

        return null;
    }

    static parsePromptTags(prompt) {
        if (!prompt || typeof prompt !== 'string') return [];

        return prompt
            .split(',')
            .map(tag => tag.trim().replace(/\s+/g, '_').toLowerCase())
            .filter(tag => tag.length > 0);
    }

    // ==================== Internal Parsers ====================

    static extractComfyUIData(metadata) {
        // ComfyUI stores workflow in 'prompt' or 'workflow' fields
        let workflow = null;

        // Try to find ComfyUI workflow in 'prompt' field
        if (metadata.prompt) {
            try {
                const parsed = typeof metadata.prompt === 'string'
                    ? JSON.parse(metadata.prompt)
                    : metadata.prompt;

                // Check if it looks like a ComfyUI workflow (has numbered nodes)
                if (typeof parsed === 'object' && parsed !== null) {
                    const keys = Object.keys(parsed);
                    // ComfyUI workflows have numeric keys for nodes
                    if (keys.length > 0 && keys.some(k => !isNaN(k))) {
                        workflow = parsed;
                    }
                }
            } catch (e) {
                // Not JSON or not a ComfyUI workflow, ignore
            }
        }

        // Try 'workflow' field
        if (!workflow && metadata.workflow) {
            try {
                workflow = typeof metadata.workflow === 'string'
                    ? JSON.parse(metadata.workflow)
                    : metadata.workflow;
            } catch (e) {
                console.error('Failed to parse workflow:', e);
            }
        }

        if (!workflow) {
            return null;
        }

        // Parse ComfyUI workflow nodes
        return this.parseComfyUIWorkflow(workflow);
    }

    static parseComfyUIWorkflow(workflow) {
        const data = {};
        const promptNodes = [];
        let positiveNodeId = null;
        let negativeNodeId = null;

        // First pass: find the KSampler and identify which nodes are positive/negative
        Object.entries(workflow).forEach(([nodeId, node]) => {
            if (!node || !node.class_type) return;

            const inputs = node.inputs || {};

            // Find KSampler to identify positive/negative connections
            if (node.class_type === 'KSampler' || node.class_type === 'KSamplerAdvanced') {
                // positive and negative inputs are arrays like ["6", 0] (node_id, output_index)
                if (inputs.positive && Array.isArray(inputs.positive)) {
                    positiveNodeId = inputs.positive[0];
                }
                if (inputs.negative && Array.isArray(inputs.negative)) {
                    negativeNodeId = inputs.negative[0];
                }
            }
        });

        // Second pass: extract data from nodes
        Object.entries(workflow).forEach(([nodeId, node]) => {
            if (!node || !node.class_type) return;

            const inputs = node.inputs || {};

            // Extract prompts
            if (node.class_type === 'CLIPTextEncode') {
                const text = inputs.text;
                // Only use direct string values, not node references
                if (text && typeof text === 'string' && text.trim()) {
                    promptNodes.push({
                        nodeId: nodeId,
                        text: text,
                        isPositive: nodeId === positiveNodeId,
                        isNegative: nodeId === negativeNodeId
                    });
                }
            }

            // Extract checkpoint/model
            if (node.class_type === 'CheckpointLoaderSimple' || node.class_type === 'CheckpointLoader') {
                if (inputs.ckpt_name && typeof inputs.ckpt_name === 'string') {
                    data.checkpoint = inputs.ckpt_name;
                }
            }

            // Extract sampler settings
            if (node.class_type === 'KSampler' || node.class_type === 'KSamplerAdvanced') {
                if (inputs.seed !== undefined && typeof inputs.seed === 'number') {
                    data.seed = inputs.seed;
                }
                if (inputs.steps !== undefined && typeof inputs.steps === 'number') {
                    data.steps = inputs.steps;
                }
                if (inputs.cfg !== undefined && typeof inputs.cfg === 'number') {
                    data.cfg_scale = inputs.cfg;
                }
                if (inputs.sampler_name && typeof inputs.sampler_name === 'string') {
                    data.sampler = inputs.sampler_name;
                }
                if (inputs.scheduler && typeof inputs.scheduler === 'string') {
                    data.scheduler = inputs.scheduler;
                }
                if (inputs.denoise !== undefined && typeof inputs.denoise === 'number') {
                    data.denoise = inputs.denoise;
                }
            }

            // Extract VAE
            if (node.class_type === 'VAELoader') {
                if (inputs.vae_name && typeof inputs.vae_name === 'string') {
                    data.vae = inputs.vae_name;
                }
            }

            // Extract resolution from EmptyLatentImage or other image nodes
            if (node.class_type === 'EmptyLatentImage') {
                if (inputs.width && typeof inputs.width === 'number') {
                    data.width = inputs.width;
                }
                if (inputs.height && typeof inputs.height === 'number') {
                    data.height = inputs.height;
                }
                if (inputs.batch_size && typeof inputs.batch_size === 'number') {
                    data.batch_size = inputs.batch_size;
                }
            }

            // Extract LoRAs
            if (node.class_type === 'LoraLoader') {
                if (!data.loras) data.loras = [];
                const loraInfo = {
                    name: inputs.lora_name,
                    strength_model: inputs.strength_model,
                    strength_clip: inputs.strength_clip
                };
                // Only add if we have actual values (not node references)
                if (typeof loraInfo.name === 'string') {
                    data.loras.push(loraInfo);
                }
            }
        });

        // Process prompts using the identified positive/negative connections
        if (promptNodes.length > 0) {
            const positivePrompt = promptNodes.find(p => p.isPositive);
            const negativePrompt = promptNodes.find(p => p.isNegative);

            if (positivePrompt) {
                data.prompt = positivePrompt.text;
            }
            if (negativePrompt) {
                data.negative_prompt = negativePrompt.text;
            }

            // If we couldn't identify through connections, use fallback logic
            if (!positivePrompt && !negativePrompt) {
                if (promptNodes.length === 1) {
                    data.prompt = promptNodes[0].text;
                } else if (promptNodes.length === 2) {
                    // Fallback: use heuristics (negative prompts often contain certain keywords)
                    const likelyNegative = promptNodes.find(p =>
                        /\b(bad|worst|ugly|deformed|blurry|low quality|watermark)\b/i.test(p.text)
                    );
                    const likelyPositive = promptNodes.find(p => p !== likelyNegative);

                    if (likelyPositive) data.prompt = likelyPositive.text;
                    if (likelyNegative) data.negative_prompt = likelyNegative.text;

                    // If heuristics didn't work, just assign them
                    if (!likelyPositive && !likelyNegative) {
                        data.prompt = promptNodes[0].text;
                        data.negative_prompt = promptNodes[1].text;
                    }
                } else {
                    // Multiple prompts - label them by node ID
                    const promptTexts = promptNodes.map(p => `[Node ${p.nodeId}]\n${p.text}`);
                    data.prompt = promptTexts.join('\n\n---\n\n');
                }
            }

            // Handle case where we only found one of them
            if (!positivePrompt && positivePrompt !== negativePrompt) {
                const unidentified = promptNodes.filter(p => !p.isPositive && !p.isNegative);
                if (unidentified.length === 1) {
                    data.prompt = unidentified[0].text;
                }
            }
        }

        // Format LoRAs for display
        if (data.loras && data.loras.length > 0) {
            const loraList = data.loras.map(lora =>
                `${lora.name} (model: ${lora.strength_model || 'N/A'}, clip: ${lora.strength_clip || 'N/A'})`
            ).join(', ');
            data.loras = loraList;
        }

        // Only return if we found useful data
        if (Object.keys(data).length === 0) {
            return null;
        }

        return data;
    }

    static parseA1111Parameters(paramString) {
        // A1111 format is typically:
        // Positive prompt
        // Negative prompt: negative text here
        // Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 123456, Size: 512x512, Model: model_name

        const data = {};

        try {
            const lines = paramString.split('\n');
            let currentPrompt = '';
            let parsingNegative = false;

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i].trim();

                // Check if this line contains parameter key-value pairs
                if (line.toLowerCase().startsWith('negative prompt:')) {
                    // Save positive prompt if we have one
                    if (currentPrompt) {
                        data.prompt = currentPrompt.trim();
                    }
                    // Start collecting negative prompt
                    parsingNegative = true;
                    currentPrompt = line.substring(line.indexOf(':') + 1).trim();
                } else if (line.includes('Steps:') || line.includes('Sampler:') ||
                    line.includes('CFG scale:') || line.includes('Seed:') ||
                    line.includes('Size:') || line.includes('Model:')) {
                    // This is the parameters line
                    // Save any prompt we were building
                    if (currentPrompt) {
                        if (parsingNegative) {
                            data.negative_prompt = currentPrompt.trim();
                        } else {
                            data.prompt = currentPrompt.trim();
                        }
                        currentPrompt = '';
                    }

                    // Parse key-value pairs
                    const pairs = line.split(',').map(s => s.trim());
                    for (const pair of pairs) {
                        const colonIndex = pair.indexOf(':');
                        if (colonIndex > 0) {
                            const key = pair.substring(0, colonIndex).trim().toLowerCase().replace(/ /g, '_');
                            const value = pair.substring(colonIndex + 1).trim();

                            // Try to convert numbers
                            const numValue = parseFloat(value);
                            data[key] = isNaN(numValue) ? value : numValue;
                        }
                    }
                } else if (line) {
                    // Continue building the current prompt
                    if (currentPrompt) {
                        currentPrompt += '\n' + line;
                    } else {
                        currentPrompt = line;
                    }
                }
            }

            // Save any remaining prompt
            if (currentPrompt) {
                if (parsingNegative) {
                    data.negative_prompt = currentPrompt.trim();
                } else {
                    data.prompt = currentPrompt.trim();
                }
            }

            // If we only got a single string with no structure, just return it as prompt
            if (Object.keys(data).length === 0 && paramString.trim()) {
                return { prompt: paramString.trim() };
            }

        } catch (e) {
            console.error('Error parsing A1111 parameters:', e);
            // Fall back to returning the raw string as prompt
            return { prompt: paramString };
        }

        return data;
    }
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = AITagUtils;
}
