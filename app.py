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


# Amazon Rekognition client configuration


############################################
# FPGA Overlay Initialization
############################################
overlay = Overlay("/home/xilinx/jupyter_notebooks/Pynq-Accelerator/LeNet/Bitstream.bit")
overlay.download()

dma = overlay.CNNIOT.CNN_dma
dma.sendchannel.start()
dma.recvchannel.start()
Accelerator.dma = dma


@app.route('/')
def hello_world():
  return "Hello world!"


@app.route('/predict', methods=['POST'])
def get_predict_cpu_lenet():
  net = request.form.get('net')
  process_type = request.form.get('type')
  base64_data = request.form.get('img').split(';base64,')[1]
  im = Image.open(BytesIO(base64.b64decode(base64_data))).resize((28, 28)).convert('L')

  if net == "lenet" and process_type == "cpu":
    res, process_time = lenet_cpu.predict(im)
  elif net == "lenet" and process_type == "fpga":
    res, process_time = lenet_fpga.predict(im)
  else:
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

  After we crop each digit, we re-threshold, find the bounding box
  of the digit, and center it on a 28x28 canvas to reduce pixelation
  and alignment issues.
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
    if text_detection.get('Type') == 'WORD' and text_detection.get('Confidence', 0) >= 50:
      detected_text = text_detection.get('DetectedText', '')
      # Keep only digits
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

  # Sort bounding boxes left to right
  digit_boxes.sort(key=lambda b: b[0])

  segmented_images = []
  for (x, y, w, h) in digit_boxes:
    try:
      # 1) Crop from original image and convert to grayscale
      digit_roi = im.crop((x, y, x + w, y + h)).convert('L')
      roi_np = np.array(digit_roi, dtype=np.uint8)

      # 2) Threshold to make digit clearer
      # You can tweak the threshold (128) if needed
      _, roi_bw = cv2.threshold(roi_np, 128, 255, cv2.THRESH_BINARY)

      # 3) Find bounding box of the nonzero pixels
      coords = cv2.findNonZero(roi_bw)
      if coords is None:
        # Blank crop => return a blank 28x28
        canvas = np.zeros((28, 28), dtype=np.uint8)
      else:
        x_min, y_min, box_w, box_h = cv2.boundingRect(coords)
        # Extract just the bounding box region
        cropped = roi_bw[y_min: y_min + box_h, x_min: x_min + box_w]

        # 4) Scale so largest dimension is 20
        # (common MNIST approach)
        height, width = cropped.shape
        max_dim = max(width, height)
        scale = 20.0 / float(max_dim)

        new_w = int(width * scale)
        new_h = int(height * scale)
        if new_w == 0: new_w = 1
        if new_h == 0: new_h = 1

        # Resize the cropped digit to new_w x new_h
        resized = cv2.resize(cropped, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # 5) Place into a fresh 28x28 canvas, centered
        canvas = np.zeros((28, 28), dtype=np.uint8)
        center_x = (28 - new_w) // 2
        center_y = (28 - new_h) // 2

        canvas[center_y: center_y + new_h, center_x: center_x + new_w] = resized

      # 6) Convert back to PIL and encode as base64
      digit_pil = Image.fromarray(canvas)
      buffer = BytesIO()
      digit_pil.save(buffer, format="JPEG")
      digit_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
      segmented_images.append("data:image/jpeg;base64," + digit_base64)

    except Exception as e:
      print("Error processing digit crop:", e)

  return jsonify({"segments": segmented_images})


if __name__ == '__main__':
  app.run(host='192.168.1.27', port=5000)
