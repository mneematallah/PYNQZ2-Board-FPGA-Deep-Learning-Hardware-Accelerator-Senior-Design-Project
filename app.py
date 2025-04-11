from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
from PIL import Image
from io import BytesIO
import cv2
from twilio.rest import Client
import time
import numpy as np
import boto3
import os

# 1) Import the modules that define CPU/FPGA predict
from LeNet import lenet_cpu, lenet_fpga

# 2) Import Accelerator so we can attach a running DMA to it
from LeNet import Accelerator

# 3) Import PYNQ and load the overlay
from pynq import Overlay

app = Flask(__name__)
CORS(app)

# TWILIO configuration
#todo here

# Amazon Rekognition client configuration
#todo here
############################################
# FPGA Overlay Initialization
############################################
# Load your bitstream into the FPGA
overlay = Overlay("/home/xilinx/jupyter_notebooks/Pynq-Accelerator/LeNet/Bitstream.bit")
overlay.download()

# Start the DMA channels
dma = overlay.CNNIOT.CNN_dma
dma.sendchannel.start()
dma.recvchannel.start()

# Make sure Accelerator uses our started DMA
Accelerator.dma = dma

@app.route('/')
def hello_world():
    return "Hello world!"

@app.route('/predict', methods=['POST'])
def get_predict_cpu_lenet():
    net = request.form.get('net')
    process_type = request.form.get('type')
    base64_data = request.form.get('img').split(';base64,')[1]
    im = Image.open(BytesIO(base64.b64decode(base64_data))).resize((28,28)).convert('L')

    if net == "lenet" and process_type == "cpu":
        # CPU path
        res, process_time = lenet_cpu.predict(im)
    elif net == "lenet" and process_type == "fpga":
        # FPGA path: uses Accelerator.dma internally
        res, process_time = lenet_fpga.predict(im)
    else:
        # Unknown path
        res, process_time = [], 0.0

    return jsonify({"res": tuple(res), "process_time": process_time})

@app.route('/capture', methods=['POST'])
def capture_image():
    cap = cv2.VideoCapture(0)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return jsonify({"error": "Failed to capture image"}), 500

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # Apply thresholding and invert so digits become white on black
    _, bw = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)
    bw = cv2.bitwise_not(bw)

    success, buffer = cv2.imencode('.jpg', bw)
    if not success:
        return jsonify({"error": "Failed to encode image"}), 500

    jpg_as_text = base64.b64encode(buffer).decode('utf-8')
    return jsonify({"img": "data:image/jpeg;base64," + jpg_as_text})

@app.route('/call', methods=['POST'])
def call_phone():
    to_number = request.form.get('to')
    if not to_number:
        return jsonify({"error": "Missing phone number"}), 400

    call = twilio_client.calls.create(
        to=to_number,
        from_=TWILIO_FROM,
        twiml="<Response><Say>This is a test call from PYNQ Accelerator demo.</Say></Response>"
    )
    return jsonify({"sid": call.sid}), 202

@app.route('/predict_with_metrics', methods=['POST'])
def predict_with_metrics():
    net = request.form.get('net')
    process_type = request.form.get('type')
    base64_data = request.form.get('img').split(';base64,')[1]
    im = Image.open(BytesIO(base64.b64decode(base64_data))).resize((28, 28)).convert('L')

    start = time.time()
    if net == "lenet" and process_type == "cpu":
        res, process_time, feature_maps, timers = lenet_cpu.predict(im, return_feature_map=True)
    elif net == "lenet" and process_type == "fpga":
        res, process_time, feature_maps, timers = lenet_fpga.predict(im, return_feature_map=True)
    else:
        res, process_time, feature_maps, timers = [], 0.0, {}, {}

    end = time.time()
    inference_time = round((end - start) * 1000, 2)

    serialized_maps = {}
    try:
        for name, fmap in feature_maps.items():
            serialized_maps[name] = np.array(fmap).tolist()
    except Exception as e:
        print("Serialization error:", e)
        serialized_maps = {}

    return jsonify({
        "res": res.tolist() if isinstance(res, np.ndarray) else res,
        "process_time": inference_time,
        "feature_maps": serialized_maps,
        "timers": timers
    })

@app.route('/segment', methods=['POST'])
def segment_image():
    """
    Uses Amazon Rekognition to detect text in the image.
    We only consider 'WORD' detections (not 'LINE'),
    and we filter out non-digit characters. Each bounding box
    is subdivided by the number of digits recognized for that 'WORD'.
    """
    try:
        raw_form = request.form.get('img')
        base64_data = raw_form.split(';base64,')[1]
        image_bytes = base64.b64decode(base64_data)
        im = Image.open(BytesIO(image_bytes))
    except Exception as e:
        print("Error processing image:", e)
        return jsonify({"error": "Invalid image format"}), 400

    width, height = im.size

    # Call Rekognition
    try:
        response = rekognition_client.detect_text(Image={'Bytes': image_bytes})
    except Exception as e:
        print("Rekognition error:", e)
        return jsonify({"error": "Rekognition failed"}), 500

    digit_boxes = []
    for text_detection in response.get('TextDetections', []):
        # Only process WORD type
        if text_detection.get('Type') == 'WORD' and text_detection.get('Confidence', 0) >= 50:
            detected_text = text_detection.get('DetectedText', '')
            # Only keep digit characters
            filtered_text = ''.join(ch for ch in detected_text if ch.isdigit())
            n = len(filtered_text)
            if n > 0:
                bbox = text_detection.get('Geometry', {}).get('BoundingBox', {})
                for i in range(n):
                    char_left = bbox.get('Left', 0) + (bbox.get('Width', 0) * i / n)
                    char_width = bbox.get('Width', 0) / n
                    digit_boxes.append((
                        int(char_left * width),
                        int(bbox.get('Top', 0) * height),
                        int(char_width * width),
                        int(bbox.get('Height', 0) * height)
                    ))

    # Sort bounding boxes from left to right
    digit_boxes.sort(key=lambda b: b[0])

    segmented_images = []
    for (x, y, w, h) in digit_boxes:
        try:
            digit_roi = im.crop((x, y, x + w, y + h))
            digit_roi = digit_roi.resize((28, 28))
            buffer = BytesIO()
            digit_roi.save(buffer, format="JPEG")
            digit_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            segmented_images.append("data:image/jpeg;base64," + digit_base64)
        except Exception as e:
            print("Error processing digit crop:", e)

    return jsonify({"segments": segmented_images})

if __name__ == '__main__':
    app.run(host='192.168.1.27', port=5000)
