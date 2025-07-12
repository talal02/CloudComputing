import io
import logging

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image
import torch
import torchvision.transforms as T
from torchvision.models import mobilenet_v2, MobileNet_V2_Weights

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI(title="Image Classification Service")

# Load the pre-trained MobileNetV2 model.
model = mobilenet_v2(weights=MobileNet_V2_Weights.DEFAULT)
model.eval()

LABELS = MobileNet_V2_Weights.DEFAULT.meta["categories"]

preprocess = T.Compose([
    T.Resize(256),
    T.CenterCrop(224),
    T.ToTensor(),
    T.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
])

@app.post("/predict")
async def predict(image: UploadFile = File(...)):
    """
    Receives an image, preprocesses it, and returns the top-1 prediction.
    
    Args:
        image: An uploaded image file.
        
    Returns:
        A JSON object containing the predicted class label.
    """
    
    logging.info(f"Received request for image: {image.filename}")
    
    contents = await image.read()
    img = Image.open(io.BytesIO(contents))
    img_t = preprocess(img)
    batch_t = torch.unsqueeze(img_t, 0)
    with torch.no_grad():
        out = model(batch_t)
        
    _, index = torch.max(out, 1)
    prediction = LABELS[index[0]]
    
    logging.info(f"Prediction for {image.filename}: {prediction}")
    
    return {"prediction": prediction}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)
