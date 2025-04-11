$(document).ready(function() {
  // ======== Canvas Setup ========
  const canvas = document.querySelector("#canvas");
  const context = canvas.getContext("2d");
  canvas.width = 280;
  canvas.height = 280;
  let Mouse = { x: 0, y: 0 };
  let lastMouse = { x: 0, y: 0 };

  context.fillStyle = "black";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "white";
  context.lineWidth = 15;
  context.lineJoin = context.lineCap = "round";

  canvas.addEventListener("mousemove", function(e) {
    lastMouse.x = Mouse.x;
    lastMouse.y = Mouse.y;
    Mouse.x = e.pageX - this.offsetLeft;
    Mouse.y = e.pageY - this.offsetTop;
  });

  canvas.addEventListener("mousedown", () => canvas.addEventListener("mousemove", onPaint));
  canvas.addEventListener("mouseup", () => canvas.removeEventListener("mousemove", onPaint));

  function onPaint() {
    context.beginPath();
    context.moveTo(lastMouse.x, lastMouse.y);
    context.lineTo(Mouse.x, Mouse.y);
    context.stroke();
  }

  // ======== Canvas Controls ========
  $("#predictButton").click(() => {
    predict(canvas.toDataURL("image/jpeg"), "cpu", "lenet");
  });
  $("#predictFpga").click(() => {
    predict(canvas.toDataURL("image/jpeg"), "fpga", "lenet");
  });
  $("#clearButton").click(() => {
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "black";
    context.fillRect(0, 0, canvas.width, canvas.height);
  });

  const slider = $("#myRange");
  $("#sliderValue").text(slider.val());
  slider.on("input", function() {
    $("#sliderValue").text(this.value);
    context.lineWidth = this.value;
  });

  // ======== Camera Capture ========
  let capturedData = null;
  $("#captureButton").click(() => {
    $.post("http://192.168.1.27:5000/capture")
      .done(data => {
        capturedData = data.img;
        $("#capturedImg").attr("src", capturedData).show();
      })
      .fail(err => console.error("Capture failed:", err));
  });
  $("#predictCpuCaptured").click(() => {
    if (!capturedData) {
      alert("No image captured!");
      return;
    }
    predict(capturedData, "cpu", "lenet");
  });
  $("#predictFpgaCaptured").click(() => {
    if (!capturedData) {
      alert("No image captured!");
      return;
    }
    predict(capturedData, "fpga", "lenet");
  });
  $("#clearCapturedImage").click(() => {
    capturedData = null;
    $("#capturedImg").hide().attr("src", "");
  });

  // ======== Call Button ========
  $("#callButton").click(() => {
    const to = $("#phoneInput").val().trim();
    if (!to) {
      alert("Please enter a valid phone number (E.164).");
      return;
    }
    $.post("http://192.168.1.27:5000/call", { to })
      .done(resp => alert("Calling… Call SID: " + resp.sid))
      .fail(err => alert("Call failed: " + (err.responseJSON?.error || err.statusText)));
  });

  // ======== General Predict & Update Table (Canvas or Captured) ========
  function predict(img, type = "cpu", net = "lenet") {
    $.post("http://192.168.1.27:5000/predict", { img, type, net })
      .done(data => updateTable(data, type, net))
      .fail(err => console.error("Predict failed:", err));
  }
  function updateTable(data, type, net) {
    const probs = softmax(data.res);
    const row = $(`#${net}${type}`);
    probs.forEach((p, i) => {
      row.children("td").eq(i + 1).text(changeTwoDecimal(p));
    });
    row.children("td").last().text(changeTwoDecimal(data.process_time));
  }

  // ======== Phone Number Segmentation (Static 10 Slots) ========
  let segmentedData = new Array(10).fill(null);
  $("#segmentButton").click(() => {
    if (!capturedData) {
      alert("No captured image available! Please capture an image first.");
      return;
    }
    $.post("http://192.168.1.27:5000/segment", { img: capturedData })
      .done(data => {
        const segments = data.segments || [];
        for (let i = 0; i < 10; i++) {
          if (i < segments.length) {
            segmentedData[i] = segments[i];
            $(`#digitImg${i+1}`).show().attr("src", segments[i]);
          } else {
            segmentedData[i] = null;
            $(`#digitImg${i+1}`).hide().attr("src", "");
          }
        }
      })
      .fail(err => console.error("Segmentation failed:", err));
  });

  // Attach individual "Predict CPU/FPGA" handlers for each digit slot
  for (let i = 1; i <= 10; i++) {
    // CPU button
    $(`#predict${i}cpu`).click(() => {
      if (!segmentedData[i-1]) {
        alert(`No digit loaded in slot ${i}`);
        return;
      }
      predictSegment(i-1, "cpu");
    });
    // FPGA button
    $(`#predict${i}fpga`).click(() => {
      if (!segmentedData[i-1]) {
        alert(`No digit loaded in slot ${i}`);
        return;
      }
      predictSegment(i-1, "fpga");
    });
  }

  // Predict a single segmented digit; returns the AJAX promise
  function predictSegment(index, type) {
    return $.post("http://192.168.1.27:5000/predict", { img: segmentedData[index], type, net: "lenet" })
      .done(data => updateSegmentSlot(data, index, type))
      .fail(err => console.error("Segmented digit predict failed:", err));
  }

  // Update the table for a given digit slot
  function updateSegmentSlot(data, index, type) {
    const i = index + 1; // HTML IDs are 1-based
    const probs = softmax(data.res);
    const tableId = `#digit${i}_${type}`;
    const row = $(tableId).find("tbody tr").first();
    probs.forEach((p, col) => {
      row.children("td").eq(col + 1).text(changeTwoDecimal(p));
    });
    row.children("td").eq(11).text(changeTwoDecimal(data.process_time));
  }

  // ======== NEW: Predict All CPU for All 10 Segmented Digits ========
  $("#predictAllCpu").click(() => {
    let chain = Promise.resolve();
    for (let i = 0; i < 10; i++) {
      if (segmentedData[i]) {
        chain = chain
          .then(() => predictSegment(i, "cpu"))
          .then(() => new Promise(resolve => setTimeout(resolve, 1000)));
      }
    }
    chain.then(() => console.log("All CPU predictions done."));
  });

  // ======== NEW: Predict All FPGA for All 10 Segmented Digits ========
  $("#predictAllFpga").click(() => {
    let chain = Promise.resolve();
    for (let i = 0; i < 10; i++) {
      if (segmentedData[i]) {
        chain = chain
          .then(() => predictSegment(i, "fpga"))
          .then(() => new Promise(resolve => setTimeout(resolve, 1000)));
      }
    }
    chain.then(() => console.log("All FPGA predictions done."));
  });

  // ======== NEW: Assemble 10-digit phone # from FPGA predictions ========
  $("#assembleFpgaNumber").click(() => {
    let phoneNumber = "";
    for (let i = 1; i <= 10; i++) {
      const row = $(`#digit${i}_fpga tbody tr`).first();
      let bestProb = -1;
      let bestDigit = 0;
      for (let digitVal = 0; digitVal <= 9; digitVal++) {
        const probText = row.children("td").eq(digitVal + 1).text();
        const prob = parseFloat(probText) || 0;
        if (prob > bestProb) {
          bestProb = prob;
          bestDigit = digitVal;
        }
      }
      phoneNumber += bestDigit;
    }
    $("#phoneInput").val(phoneNumber);
    alert("Assembled phone number: " + phoneNumber);
  });

  // Utility functions
  function softmax(arr) {
    const exps = arr.map(x => Math.exp(x / 100));
    const sum = exps.reduce((a, b) => a + b, 0);
    return exps.map(v => v / sum);
  }
  function changeTwoDecimal(x) {
    const n = parseFloat(x);
    return isNaN(n) ? 0 : Math.round(n * 100) / 100;
  }
});
