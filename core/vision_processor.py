"""
SOVERYN Vision Processor
Analyzes images using Qwen2-VL-7B vision model
"""

import torch
from transformers import Qwen2VLForConditionalGeneration, AutoProcessor
from pathlib import Path

class VisionProcessor:
    def __init__(self):
        self.model = None
        self.processor = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
    def load_model(self):
        """Load Qwen2-VL-7B model"""
        if self.model is not None:
            return
        
        print("SOVEREIGN: Loading vision model qwen2-vl-7b")
        model_path = "C:/SOVERYN_Models/qwen2-vl-7b"
        
        try:
            from transformers import BitsAndBytesConfig
            
            # Configure 4-bit quantization
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4"
            )
            
            # Load processor
            self.processor = AutoProcessor.from_pretrained(
                model_path,
                use_fast=True
            )
            
            # Load model with proper quantization config
            self.model = Qwen2VLForConditionalGeneration.from_pretrained(
                model_path,
                quantization_config=quantization_config,
                device_map="auto",
                torch_dtype=torch.float16
            )
            
            print(f"SOVEREIGN: Vision model loaded successfully")
            
        except Exception as e:
            print(f"SOVEREIGN: Vision model load error: {e}")
            raise
    
    def analyze_image(self, image_path, prompt="Describe this image in detail."):
        """
        Analyze an image and return description
        
        Args:
            image_path: Path to image file
            prompt: Optional custom prompt
            
        Returns:
            str: Image description
        """
        try:
            # Load model if not already loaded
            self.load_model()
            
            # Prepare inputs
            from PIL import Image
            image = Image.open(image_path)
            
            # Create conversation format
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},
                        {"type": "text", "text": prompt}
                    ]
                }
            ]
            
            # Process inputs
            text_prompt = self.processor.apply_chat_template(messages, add_generation_prompt=True)
            inputs = self.processor(
                text=[text_prompt],
                images=[image],
                return_tensors="pt"
            ).to(self.device)
            
            # Generate description
            with torch.no_grad():
                output_ids = self.model.generate(
                    **inputs,
                    max_new_tokens=512,
                    do_sample=False
                )
            
            # Decode output
            generated_ids = [
                output_ids[len(input_ids):]
                for input_ids, output_ids in zip(inputs.input_ids, output_ids)
            ]
            
            description = self.processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=True
            )[0]
            
            print(f"SOVEREIGN: Vision analysis complete ({len(description)} chars)")
            return description
            
        except Exception as e:
            print(f"SOVEREIGN: Vision analysis error: {e}")
            return f"Error analyzing image: {str(e)}"
    
    def unload_model(self):
        """Unload vision model to free VRAM"""
        if self.model is not None:
            del self.model
            del self.processor
            self.model = None
            self.processor = None
            
            import gc
            torch.cuda.empty_cache()
            gc.collect()
            print("SOVEREIGN: Vision model unloaded")


# Global instance
_vision_processor = None

def get_vision_processor():
    """Get or create vision processor instance"""
    global _vision_processor
    if _vision_processor is None:
        _vision_processor = VisionProcessor()
    return _vision_processor

def analyze_image(image_path, prompt="Describe this image in detail."):
    """
    Convenience function to analyze an image
    
    Args:
        image_path: Path to image file
        prompt: Optional custom prompt
        
    Returns:
        str: Image description
    """
    processor = get_vision_processor()
    return processor.analyze_image(image_path, prompt)