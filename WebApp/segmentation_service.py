# segmentation_service.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
from PIL import Image
from io import BytesIO
import cv2
import numpy as np
import boto3

app = Flask(__name__)
CORS(app)

# configure your AWS creds here
rekognition = boto3.client(
    "rekognition",
    region_name="us-east-1",
    aws_access_key_id="AKIASWCVOQZ6Q5K2A7AH",
    aws_secret_access_key="F+K7FZPKpG991HXOtxWqmpvOq0KOpzKTZtHDjl4/"
)

@app.route("/segment", methods=["POST"])
def segment():
    # 1) pull out the base64 JPEG
    raw = request.form["img"].split(";base64,")[1]
    img_bytes = base64.b64decode(raw)
    im = Image.open(BytesIO(img_bytes))
    width, height = im.size

    # 2) ask Rekognition for WORD boxes
    resp = rekognition.detect_text(Image={"Bytes": img_bytes})
    digit_boxes = []
    for det in resp.get("TextDetections", []):
        if det["Type"] == "WORD" and det["Confidence"] >= 50:
            filtered = "".join(ch for ch in det["DetectedText"] if ch.isdigit())
            n = len(filtered)
            if n > 0:
                bb = det["Geometry"]["BoundingBox"]
                for i in range(n):
                    left = bb["Left"] + bb["Width"] * i / n
                    w_box = bb["Width"] / n
                    digit_boxes.append((
                        int(left * width),
                        int(bb["Top"] * height),
                        int(w_box * width),
                        int(bb["Height"] * height)
                    ))

    # 3) sort left→right
    digit_boxes.sort(key=lambda b: b[0])

    segments = []
    for (x, y, w, h) in digit_boxes:
        # a) crop & make grayscale
        digit_roi = im.crop((x, y, x + w, y + h)).convert("L")
        roi_np = np.array(digit_roi, dtype=np.uint8)

        # b) re‐threshold to binary
        _, roi_bw = cv2.threshold(roi_np, 128, 255, cv2.THRESH_BINARY)

        # c) find tight bounding box of the white digit
        coords = cv2.findNonZero(roi_bw)
        if coords is None:
            canvas = np.zeros((28, 28), dtype=np.uint8)
        else:
            x0, y0, w0, h0 = cv2.boundingRect(coords)
            cut = roi_bw[y0 : y0 + h0, x0 : x0 + w0]

            # d) scale longest side to 20px
            max_dim = max(w0, h0)
            scale = 20.0 / max_dim
            new_w = max(1, int(w0 * scale))
            new_h = max(1, int(h0 * scale))

            # e) resize with INTER_AREA (same as old app.py)
            resized = cv2.resize(cut, (new_w, new_h), interpolation=cv2.INTER_AREA)

            # f) center on 28×28 canvas
            canvas = np.zeros((28, 28), dtype=np.uint8)
            cx = (28 - new_w) // 2
            cy = (28 - new_h) // 2
            canvas[cy : cy + new_h, cx : cx + new_w] = resized

        # g) back to PIL, encode as JPEG/base64
        digit_pil = Image.fromarray(canvas)
        buf = BytesIO()
        digit_pil.save(buf, format="JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        segments.append("data:image/jpeg;base64," + b64)

    return jsonify({"segments": segments})

if __name__ == "__main__":
    # listen on 0.0.0.0 so your board/browser can reach it
    app.run(host="0.0.0.0", port=5001)
