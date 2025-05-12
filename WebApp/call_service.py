# call_service.py
from flask import Flask, request, jsonify
from flask_cors import CORS
from twilio.rest import Client

app = Flask(__name__)
CORS(app)

# Twilio credentials (keep these out of git, e.g. env vars in real life)
TWILIO_SID   = "ACd73c364acd994664c98985562919d06a"
TWILIO_TOKEN = "b7b53c27d0d4d45ee63e184744165c95"
TWILIO_FROM  = "+14255539085"
client = Client(TWILIO_SID, TWILIO_TOKEN)

@app.route("/call", methods=["POST"])
def call_phone():
    to = request.form.get("to")
    if not to:
        return jsonify({"error": "Missing phone number"}), 400

    try:
        call = client.calls.create(
            to=to,
            from_=TWILIO_FROM,
            twiml="<Response><Say>This is a test call from PYNQ Accelerator demo.</Say></Response>"
        )
        return jsonify({"sid": call.sid}), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__=="__main__":
    app.run(host="0.0.0.0", port=5002)
