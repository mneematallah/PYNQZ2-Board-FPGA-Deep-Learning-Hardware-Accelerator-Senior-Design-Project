from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
from PIL import Image
from io import BytesIO
from LeNet import lenet_cpu, lenet_fpga
import cv2

app = Flask(__name__)
CORS(app)

@app.route('/')
def hello_world():
    return "Hello world!"

@app.route('/predict', methods=['POST'])
def get_predict_cpu_lenet():
    net = request.form.get('net')            # "lenet"
    process_type = request.form.get('type')  # "cpu" or "fpga"
    base64_data = request.form.get('img').split(';base64,')[1]

    # Convert the base64 data to a PIL image
    # and do the final 28x28 grayscale for the model
    im = Image.open(BytesIO(base64.b64decode(base64_data))).resize((28, 28)).convert('L')

    if net == "lenet" and process_type == "cpu":
        res, process_time = lenet_cpu.predict(im)
    elif net == "lenet" and process_type == "fpga":
        res, process_time = lenet_fpga.predict(im)
    else:
        res = []
        process_time = 0.0

    return jsonify({
        "res": tuple(res),
        "process_time": process_time
    })

@app.route('/capture', methods=['POST'])
def capture_image():
    """
    Capture from USB camera, then:
      1) Convert to grayscale
      2) Threshold to black & white
      3) Invert so background is black, digit is white
      4) Encode as JPEG, return as base64
    """
    cap = cv2.VideoCapture(0)
    # Optional: cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    # Optional: cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    ret, frame = cap.read()
    cap.release()

    if not ret:
        return jsonify({"error": "Failed to capture image"}), 500

    # 1) Convert to grayscale
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 2) Threshold to black & white (adjust threshold value if needed)
    _, bw = cv2.threshold(gray, 128, 255, cv2.THRESH_BINARY)

    # 3) Invert: now the background is black, the digit is white
    bw = cv2.bitwise_not(bw)

    # Encode the final image as JPEG
    success, buffer = cv2.imencode('.jpg', bw)
    if not success:
        return jsonify({"error": "Failed to encode image"}), 500

    # Convert to base64 data URL
    jpg_as_text = base64.b64encode(buffer).decode('utf-8')
    return jsonify({"img": "data:image/jpeg;base64," + jpg_as_text})

if __name__ == '__main__':
    # Replace with your board's actual IP or use 0.0.0.0
    app.run(host='192.168.1.27', port=5000)
